# -*- coding: utf-8 -*-
"""FFmpeg を用いた動画・音声処理の高水準ユーティリティ群。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ffmpeg_audio import has_audio_stream
from .ffmpeg_capabilities import (
    _threading_flags,
    get_ffmpeg_version,
    get_hw_encoder_kind_for_video_params,
)
from .ffmpeg_hw import get_profile_flags
from .ffmpeg_params import AudioParams, VideoParams
from .ffmpeg_probe import MediaInfo, get_media_info
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger


BACKGROUND_FIT_STRETCH = "stretch"
BACKGROUND_FIT_CONTAIN = "contain"
BACKGROUND_FIT_COVER = "cover"
BACKGROUND_FIT_WIDTH = "fit_width"
BACKGROUND_FIT_HEIGHT = "fit_height"

BACKGROUND_FIT_MODES = {
    BACKGROUND_FIT_STRETCH,
    BACKGROUND_FIT_CONTAIN,
    BACKGROUND_FIT_COVER,
    BACKGROUND_FIT_WIDTH,
    BACKGROUND_FIT_HEIGHT,
}

DEFAULT_BACKGROUND_ANCHOR = "middle_center"
DEFAULT_BACKGROUND_FILL_COLOR = "#000000"


def _to_expr(value: Any) -> str:
    """Convert numeric/string offsets into FFmpeg expression fragments."""

    if value is None:
        return "0"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _sanitize_anchor(anchor: Optional[str]) -> str:
    if not anchor:
        return DEFAULT_BACKGROUND_ANCHOR
    return str(anchor)


def build_background_fit_steps(
    *,
    width: int,
    height: int,
    fit_mode: str,
    fill_color: str,
    anchor: str,
    offset_x: str,
    offset_y: str,
    scale_flags: str,
) -> List[str]:
    """Return sequential FFmpeg filters for the requested background fit mode."""

    fit = (fit_mode or BACKGROUND_FIT_STRETCH).lower()
    if fit not in BACKGROUND_FIT_MODES:
        fit = BACKGROUND_FIT_STRETCH

    steps: List[str] = []

    if fit == BACKGROUND_FIT_STRETCH:
        steps.append(f"scale={width}:{height}:flags={scale_flags}")
        return steps

    if fit == BACKGROUND_FIT_CONTAIN:
        steps.append(
            "scale="
            f"{width}:{height}:flags={scale_flags}:force_original_aspect_ratio=decrease"
        )
        pad_x, pad_y = calculate_overlay_position(
            str(width),
            str(height),
            "iw",
            "ih",
            anchor,
            offset_x,
            offset_y,
        )
        steps.append(
            f"pad={width}:{height}:x={pad_x}:y={pad_y}:color={fill_color}"
        )
        return steps

    if fit == BACKGROUND_FIT_COVER:
        steps.append(
            "scale="
            f"{width}:{height}:flags={scale_flags}:force_original_aspect_ratio=increase"
        )
        crop_x, crop_y = calculate_overlay_position(
            "iw",
            "ih",
            str(width),
            str(height),
            anchor,
            offset_x,
            offset_y,
        )
        steps.append(f"crop={width}:{height}:{crop_x}:{crop_y}")
        return steps

    if fit == BACKGROUND_FIT_WIDTH:
        steps.append(f"scale={width}:-2:flags={scale_flags}")
        crop_height = f"min({height},ih)"
        crop_x, crop_y = calculate_overlay_position(
            "iw",
            "ih",
            str(width),
            crop_height,
            anchor,
            offset_x,
            offset_y,
        )
        steps.append(f"crop={width}:{crop_height}:{crop_x}:{crop_y}")
        pad_x, pad_y = calculate_overlay_position(
            str(width),
            str(height),
            "iw",
            "ih",
            anchor,
            offset_x,
            offset_y,
        )
        steps.append(
            f"pad={width}:{height}:x={pad_x}:y={pad_y}:color={fill_color}"
        )
        return steps

    if fit == BACKGROUND_FIT_HEIGHT:
        steps.append(f"scale=-2:{height}:flags={scale_flags}")
        crop_width = f"min({width},iw)"
        crop_x, crop_y = calculate_overlay_position(
            "iw",
            "ih",
            crop_width,
            str(height),
            anchor,
            offset_x,
            offset_y,
        )
        steps.append(f"crop={crop_width}:{height}:{crop_x}:{crop_y}")
        pad_x, pad_y = calculate_overlay_position(
            str(width),
            str(height),
            "iw",
            "ih",
            anchor,
            offset_x,
            offset_y,
        )
        steps.append(
            f"pad={width}:{height}:x={pad_x}:y={pad_y}:color={fill_color}"
        )
        return steps

    # Fallback to stretch if an unknown mode somehow slipped through validation.
    steps.append(f"scale={width}:{height}:flags={scale_flags}")
    return steps


def build_background_filter_complex(
    *,
    input_label: str,
    output_label: str,
    steps: List[str],
    apply_fps: bool,
    fps: int,
) -> List[str]:
    """Convert background fit steps into filter_complex statements."""

    if not steps:
        chain = f"[{input_label}]"
        chain += f"fps={fps}" if apply_fps else "null"
        chain += f"[{output_label}]"
        return [chain]

    parts: List[str] = []
    current = input_label
    for idx, step in enumerate(steps):
        is_last = idx == len(steps) - 1
        target = output_label if is_last else f"{output_label}_step{idx+1}"
        expr = step
        if is_last and apply_fps:
            expr = f"{expr},fps={fps}"
        parts.append(f"[{current}]{expr}[{target}]")
        current = target
    return parts


def compose_background_filter_expression(
    *,
    steps: List[str],
    apply_fps: bool,
    fps: int,
) -> str:
    """Compose a -vf filter string for standalone background processing."""

    if not steps:
        return f"fps={fps}" if apply_fps else "null"
    filters = steps.copy()
    if apply_fps:
        filters[-1] = f"{filters[-1]},fps={fps}"
    return ",".join(filters)


# =========================================================
async def compare_media_params(file_paths: List[str]) -> bool:
    """
    複数動画の主要パラメータ（コーデック/解像度/フレームレート/ピクセルフォーマット/
    サンプルレート/チャンネル数/チャンネルレイアウト）が全て一致するか判定する。
    """
    if not file_paths:
        return True  # ファイルがない場合は一致とみなす

    try:
        infos = await asyncio.gather(*(get_media_info(p) for p in file_paths))
    except Exception as e:
        logger.error(f"Error gathering media info: {e}")
        return False

    base_info_val: Optional[MediaInfo] = infos[0] if infos else None
    if base_info_val is None:
        logger.warning("Base media info is None, cannot compare")
        return False

    for info, path in zip(infos[1:], file_paths[1:]):
        # 動画ストリームの比較
        base_video = base_info_val.get("video")
        current_video = info.get("video")
        if base_video and current_video:
            if not (
                base_video.get("codec_name") == current_video.get("codec_name")
                and base_video.get("width") == current_video.get("width")
                and base_video.get("height") == current_video.get("height")
                and base_video.get("pix_fmt") == current_video.get("pix_fmt")
                and base_video.get("r_frame_rate") == current_video.get("r_frame_rate")
            ):
                logger.warning(
                    f"Video parameters mismatch between {file_paths[0]} and {path}"
                )
                return False
        elif (base_video is not None) != (current_video is not None):
            logger.warning(
                f"Video stream presence mismatch between {file_paths[0]} and {path}"
            )
            return False

        # 音声ストリームの比較
        base_audio = base_info_val.get("audio")
        current_audio = info.get("audio")
        if base_audio and current_audio:
            if not (
                base_audio.get("codec_name") == current_audio.get("codec_name")
                and base_audio.get("sample_rate") == current_audio.get("sample_rate")
                and base_audio.get("channels") == current_audio.get("channels")
                and base_audio.get("channel_layout") == current_audio.get("channel_layout")
            ):
                logger.warning(
                    f"Audio parameters mismatch between {file_paths[0]} and {path}"
                )
                return False
        elif (base_audio is not None) != (current_audio is not None):
            logger.warning(
                f"Audio stream presence mismatch between {file_paths[0]} and {path}"
            )
            return False

    return True


async def concat_videos_copy(
    input_paths: List[str],
    output_path: str,
    ffmpeg_path: str = "ffmpeg",
    movflags_faststart: bool = False,
):
    """
    -f concat -c copy を使用して動画を再エンコードなしで結合する。
    事前に compare_media_params でパラメータの一致を確認していることを前提とする。
    """
    if not input_paths:
        logger.warning("No input paths provided for concat_videos_copy.")
        return

    # 一時リストファイルは出力先と同じディレクトリに配置（I/O 局所性）
    try:
        h = hashlib.sha256("\n".join(input_paths).encode("utf-8")).hexdigest()[:16]
    except Exception:
        h = "ffconcat"
    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    list_file_path = os.path.join(out_dir, f".ffconcat_{h}.txt")
    # 事前に簡易I/Oメトリクスを収集（合計サイズ）
    total_bytes = sum(
        os.path.getsize(p) for p in input_paths if os.path.exists(p)
    )
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in input_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    cmd = [
        ffmpeg_path,
        "-y",
        *get_profile_flags(),
        "-f",
        "concat",
        "-safe",
        "0",  # 危険なファイルパスを許可（絶対パスを使用するため）
        "-i",
        list_file_path,
        "-c",
        "copy",
    ]
    if movflags_faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.extend([
        output_path,
    ])

    # 実行時間を計測
    t0 = time.time()
    try:
        proc = await _run_ffmpeg_async(cmd)  # await を追加
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        elapsed = time.time() - t0
        mb = total_bytes / (1024 * 1024) if total_bytes else 0.0
        thr = (mb / elapsed) if elapsed > 0 else 0.0
        logger.info(
            "[ConcatCopy] inputs=%d, size=%.1fMB, time=%.2fs, throughput=%.1fMB/s -> %s",
            len(input_paths),
            mb,
            elapsed,
            thr,
            output_path,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Error concatenating videos with -c copy: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise
    finally:
        if os.path.exists(list_file_path):
            os.remove(list_file_path)
async def apply_transition(
    input_video1_path: str,
    input_video2_path: str,
    output_path: str,
    transition_type: str,
    duration: float,
    offset: float,
    video_params: VideoParams,
    audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg",
    wait_padding: float = 0.0,
):
    """
    映像: xfade、音声: acrossfade でクロスフェード。
    - デコード＆フィルタ: CPU
    - エンコード: HW（存在すれば）/ CPU
    - 映像/音声ともにトランジション直前後へ構成済みのウェイトを自動付与
    """
    has_a1 = await has_audio_stream(input_video1_path)
    has_a2 = await has_audio_stream(input_video2_path)

    hw_kind = await get_hw_encoder_kind_for_video_params(ffmpeg_path)
    video_opts = video_params.to_ffmpeg_opts(hw_kind)
    audio_opts = audio_params.to_ffmpeg_opts()

    wait_padding = max(0.0, wait_padding)
    xfade_offset = max(0.0, offset + wait_padding)

    cmd = [ffmpeg_path, "-y", *get_profile_flags()]
    cmd.extend(_threading_flags(ffmpeg_path))
    cmd.extend(["-i", input_video1_path, "-i", input_video2_path])

    filter_parts = []

    v0_label = "0:v"
    v1_label = "1:v"
    if wait_padding > 0:
        filter_parts.append(
            f"[0:v]tpad=stop_mode=clone:stop_duration={wait_padding:.3f}[v0pad]"
        )
        filter_parts.append(
            f"[1:v]tpad=start_mode=clone:start_duration={wait_padding:.3f}[v1pad]"
        )
        v0_label = "v0pad"
        v1_label = "v1pad"

    filter_parts.append(
        f"[{v0_label}][{v1_label}]xfade=transition={transition_type}:duration={duration}:offset={xfade_offset:.3f}[v]"
    )

    audio_channels = max(1, int(audio_params.channels))
    channel_layout = "stereo" if audio_channels == 2 else f"{audio_channels}c"

    if has_a1 and has_a2:
        delay_ms = int(round(wait_padding * 1000))
        delay_values = "|".join(str(delay_ms) for _ in range(audio_channels)) or str(delay_ms)
        filter_parts.append(
            f"[0:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts={channel_layout},"
            f"apad=pad_dur={wait_padding:.3f}[a0pad]"
        )
        filter_parts.append(
            f"[1:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts={channel_layout},"
            f"adelay={delay_values},apad=pad_dur={wait_padding:.3f}[a1pad]"
        )
        filter_parts.append(
            f"[a0pad][a1pad]acrossfade=d={duration}:c1=tri:c2=tri[a]"
        )
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]", "-map", "[a]"]
    elif has_a1:
        filter_parts.append(
            f"[0:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts={channel_layout},"
            f"apad=pad_dur={wait_padding:.3f},"
            f"afade=t=out:st={xfade_offset:.3f}:d={duration}[a]"
        )
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]", "-map", "[a]"]
    elif has_a2:
        delay_ms = int(round(xfade_offset * 1000))
        filter_parts.append(
            f"[1:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts={channel_layout},"
            f"adelay={delay_ms}:all=1,apad=pad_dur={wait_padding:.3f},afade=t=in:st=0:d={duration}[a]"
        )
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", ";".join(filter_parts), "-map", "[v]"]

    # 映像エンコード設定
    cmd.extend(video_opts)
    cmd.extend(audio_opts)
    cmd.extend([output_path])

    try:
        proc = await _run_ffmpeg_async(cmd)
        logger.debug("FFmpeg stdout:\n%s", proc.stdout)
        logger.debug("FFmpeg stderr:\n%s", proc.stderr)
        logger.info(
            "Applied '%s' transition (wait_padding=%.2fs) with audio crossfade: %s + %s -> %s",
            transition_type,
            wait_padding,
            input_video1_path,
            input_video2_path,
            output_path,
        )
    except subprocess.CalledProcessError as e:
        logger.error("Error applying transition: %s", e)
        logger.error("FFmpeg stdout:\n%s", e.stdout)
        logger.error("FFmpeg stderr:\n%s", e.stderr)
        raise


def calculate_overlay_position(
    bg_width_expr: str,
    bg_height_expr: str,
    fg_width_expr: str,
    fg_height_expr: str,
    anchor: str,
    offset_x: str = "0",
    offset_y: str = "0",
) -> Tuple[str, str]:
    """
    overlay の配置式をアンカーとオフセットから計算。
    """
    x_expr = ""
    y_expr = ""

    if anchor == "top_left":
        x_expr, y_expr = "0", "0"
    elif anchor == "top_center":
        x_expr, y_expr = f"({bg_width_expr}-{fg_width_expr})/2", "0"
    elif anchor == "top_right":
        x_expr, y_expr = f"{bg_width_expr}-{fg_width_expr}", "0"
    elif anchor == "middle_left":
        x_expr, y_expr = "0", f"({bg_height_expr}-{fg_height_expr})/2"
    elif anchor == "middle_center":
        x_expr, y_expr = (
            f"({bg_width_expr}-{fg_width_expr})/2",
            f"({bg_height_expr}-{fg_height_expr})/2",
        )
    elif anchor == "middle_right":
        x_expr, y_expr = (
            f"{bg_width_expr}-{fg_width_expr}",
            f"({bg_height_expr}-{fg_height_expr})/2",
        )
    elif anchor == "bottom_left":
        x_expr, y_expr = "0", f"{bg_height_expr}-{fg_height_expr}"
    elif anchor == "bottom_center":
        x_expr, y_expr = (
            f"({bg_width_expr}-{fg_width_expr})/2",
            f"{bg_height_expr}-{fg_height_expr}",
        )
    elif anchor == "bottom_right":
        x_expr, y_expr = (
            f"{bg_width_expr}-{fg_width_expr}",
            f"{bg_height_expr}-{fg_height_expr}",
        )
    else:
        logger.warning(f"Unknown anchor point: {anchor}. Defaulting to top_left.")
        x_expr, y_expr = "0", "0"

    # オフセット加算
    if offset_x and offset_x != "0":
        x_expr = (
            f"{x_expr}{offset_x}"
            if offset_x.startswith("-")
            else f"{x_expr}+{offset_x}"
        )
    if offset_y and offset_y != "0":
        y_expr = (
            f"{y_expr}{offset_y}"
            if offset_y.startswith("-")
            else f"{y_expr}+{offset_y}"
        )

    return x_expr, y_expr
async def normalize_media(
    input_path: Path,
    video_params: VideoParams,
    audio_params: AudioParams,
    cache_manager: Any,  # CacheManager の循環インポートを避けるため Any を使用
    ffmpeg_path: str = "ffmpeg",
    *,
    fit_mode: str = BACKGROUND_FIT_STRETCH,
    fill_color: str = DEFAULT_BACKGROUND_FILL_COLOR,
    anchor: str = DEFAULT_BACKGROUND_ANCHOR,
    position: Optional[Dict[str, Any]] = None,
    scale_flags: str = "lanczos",
) -> Path:
    """
    背景・挿入動画を指定されたパラメータに正規化し、キャッシュする。
    キャッシュがHITすれば、変換処理をスキップしてキャッシュパスを返す。
    """
    pos_dict_raw = position or {}
    offset_x = _to_expr(pos_dict_raw.get("x", "0"))
    offset_y = _to_expr(pos_dict_raw.get("y", "0"))
    fit_mode_norm = (fit_mode or BACKGROUND_FIT_STRETCH).lower()
    anchor_norm = _sanitize_anchor(anchor)
    fill_norm = fill_color or DEFAULT_BACKGROUND_FILL_COLOR
    pos_norm = {"x": offset_x, "y": offset_y}

    # 入力が既に本プロジェクトの正規化仕様で生成されたMP4で、隣接する meta の target_spec が一致する場合は自己再正規化を避ける
    try:
        if input_path.is_file() and input_path.suffix.lower() == ".mp4":

            target_spec = {
                "video": {
                    "width": int(video_params.width),
                    "height": int(video_params.height),
                    "fps": int(video_params.fps),
                    "pix_fmt": video_params.pix_fmt,
                    "codec": "h264",
                    "background_fit": fit_mode_norm,
                    "background_fill_color": fill_norm,
                    "background_anchor": anchor_norm,
                    "background_position": pos_norm,
                },
                "audio": {
                    "sr": int(audio_params.sample_rate),
                    "ch": int(audio_params.channels),
                    "codec": audio_params.codec,
                },
            }
            meta_candidate = input_path.with_name(input_path.stem + ".meta.json")
            if meta_candidate.exists():
                with open(meta_candidate, "r", encoding="utf-8") as f:
                    meta_obj = json.load(f)
                cached_spec = meta_obj.get("target_spec")
                if cached_spec == target_spec:
                    logger.info(
                        f"[Cache] Skipping re-normalization for cached normalized file: {input_path}"
                    )
                    return input_path
    except Exception as e:
        logger.debug(f"Skip pre-check for already-normalized input due to error: {e}")
    # 入力ファイルのサイズと最終更新時刻を取得
    file_stat = input_path.stat()
    file_size = file_stat.st_size
    file_mtime = file_stat.st_mtime

    key_data = {
        "input_path": str(input_path.resolve()),
        "file_size": file_size,
        "file_mtime": file_mtime,
        "video_params": video_params.__dict__,
        "audio_params": audio_params.__dict__,
        "ffmpeg_version": await get_ffmpeg_version(
            ffmpeg_path
        ),  # FFmpegのバージョンもハッシュに含める
        "background_fit": fit_mode_norm,
        "background_fill_color": fill_norm,
        "background_anchor": anchor_norm,
        "background_position": pos_norm,
        "scale_flags": scale_flags,
    }

    cached_path = cache_manager.get_cache_path(key_data, "normalized", "mp4")

    if (
        not cache_manager.no_cache
        and not cache_manager.cache_refresh
        and cached_path.exists()
    ):
        logger.info(f"[Cache] Normalized hit: {cached_path}")
        return cached_path

    logger.info(f"[Cache] Normalized miss: {input_path} -> generating...")

    async def creator_func(output_path: Path) -> Path:
        input_media_info = await get_media_info(str(input_path))
        has_audio = await has_audio_stream(str(input_path))

        # コピーモードが利用可能かチェック
        can_copy_video = False
        can_copy_audio = False

        input_v = input_media_info.get("video")
        requires_fit = fit_mode_norm != BACKGROUND_FIT_STRETCH or offset_x != "0" or offset_y != "0"

        if input_v:
            # 解像度、FPS、ピクセルフォーマット、コーデックが一致するか
            if (
                input_v.get("width") == video_params.width
                and input_v.get("height") == video_params.height
                and input_v.get("fps") == video_params.fps
                and input_v.get("pix_fmt") == video_params.pix_fmt
                and input_v.get("codec_name")
                in ["h264", "hevc"]  # H.264/HEVCコーデックのみコピー対象
            ):
                can_copy_video = not requires_fit
                logger.debug(
                    "Video can%s be copied for %s (requires_fit=%s)",
                    "" if can_copy_video else "not",
                    input_path,
                    requires_fit,
                )
            else:
                logger.debug(
                    f"Video parameters mismatch for {input_path}. Input: {input_v}, Target: {video_params.__dict__}"
                )

        input_a = input_media_info.get("audio")
        if has_audio and input_a:
            # サンプルレート、チャンネル数、コーデックが一致するか
            if (
                input_a.get("sample_rate") == audio_params.sample_rate
                and input_a.get("channels") == audio_params.channels
                and input_a.get("codec_name") == audio_params.codec
            ):
                can_copy_audio = True
                logger.debug(f"Audio can be copied for {input_path}")
            else:
                logger.debug(
                    f"Audio parameters mismatch for {input_path}. Input: {input_a}, Target: {audio_params.__dict__}"
                )

        async def _build_cmd(disable_hwenc: bool = False) -> List[str]:
            cmd_local: List[str] = [ffmpeg_path, "-y"]
            cmd_local.extend(_threading_flags(ffmpeg_path))
            cmd_local.extend(["-i", str(input_path)])

            if can_copy_video and can_copy_audio:
                cmd_local.extend(["-c", "copy"])
                logger.info(
                    f"Using -c copy for both video and audio for {input_path}"
                )
            elif can_copy_video:
                cmd_local.extend(["-c:v", "copy"])
                if has_audio:
                    cmd_local.extend(
                        [
                            "-af",
                            f"aresample={audio_params.sample_rate},asetpts=PTS-STARTPTS",
                        ]
                    )
                    cmd_local.extend(audio_params.to_ffmpeg_opts())
                else:
                    cmd_local.extend(["-an"])
                logger.info(f"Using -c:v copy for video for {input_path}")
            elif can_copy_audio:
                cmd_local.extend(["-c:a", "copy"])
                cmd_local.extend(
                    [
                        "-af",
                        f"aresample={audio_params.sample_rate},asetpts=PTS-STARTPTS",
                    ]
                )  # 音声はコピーだが、サンプルレート調整は必要
                fit_steps = build_background_fit_steps(
                    width=int(video_params.width),
                    height=int(video_params.height),
                    fit_mode=fit_mode_norm,
                    fill_color=fill_norm,
                    anchor=anchor_norm,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    scale_flags=scale_flags,
                )
                composed = compose_background_filter_expression(
                    steps=fit_steps,
                    apply_fps=True,
                    fps=int(video_params.fps),
                )
                cmd_local.extend(["-vf", f"{composed},setpts=PTS-STARTPTS"])
                # HW検出（フォールバック用に環境変数を尊重）
                hw_kind_local = None
                if not disable_hwenc:
                    hw_kind_local = await get_hw_encoder_kind_for_video_params(
                        ffmpeg_path
                    )
                cmd_local.extend(video_params.to_ffmpeg_opts(hw_kind_local))
                logger.info(f"Using -c:a copy for audio for {input_path}")
            else:
                # 再エンコードが必要な場合
                fit_steps = build_background_fit_steps(
                    width=int(video_params.width),
                    height=int(video_params.height),
                    fit_mode=fit_mode_norm,
                    fill_color=fill_norm,
                    anchor=anchor_norm,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    scale_flags=scale_flags,
                )
                video_filter_core = compose_background_filter_expression(
                    steps=fit_steps,
                    apply_fps=True,
                    fps=int(video_params.fps),
                )
                video_filter = f"{video_filter_core},setpts=PTS-STARTPTS"
                audio_filter = (
                    f"aresample={audio_params.sample_rate},asetpts=PTS-STARTPTS"
                )

                # HW検出（フォールバック用に環境変数を尊重）
                hw_kind_local = None
                if not disable_hwenc:
                    hw_kind_local = await get_hw_encoder_kind_for_video_params(
                        ffmpeg_path
                    )
                video_opts = video_params.to_ffmpeg_opts(hw_kind_local)
                audio_opts = audio_params.to_ffmpeg_opts()

                cmd_local.extend(["-vf", video_filter])
                if has_audio:
                    cmd_local.extend(["-af", audio_filter])
                else:
                    cmd_local.extend(["-an"])

                cmd_local.extend(video_opts)
                if has_audio:
                    cmd_local.extend(audio_opts)
                logger.info(f"Re-encoding video and/or audio for {input_path}")

            cmd_local.extend([str(output_path)])
            return cmd_local

        # 1st try: allow hardware encoder
        cmd = await _build_cmd(disable_hwenc=False)
        try:
            await _run_ffmpeg_async(cmd)
            if Path(output_path).exists():
                logger.info(
                    f"Successfully normalized {input_path} to {output_path} (file exists)."
                )
            else:
                logger.error(
                    f"Failed to normalize {input_path} to {output_path} (file does NOT exist)."
                )
            # Write adjacent meta for re-normalization avoidance
            try:
                meta = {
                    "target_spec": {
                        "video": {
                            "width": int(video_params.width),
                            "height": int(video_params.height),
                            "fps": int(video_params.fps),
                            "pix_fmt": video_params.pix_fmt,
                            "codec": "h264",
                            "background_fit": fit_mode_norm,
                            "background_fill_color": fill_norm,
                            "background_anchor": anchor_norm,
                            "background_position": pos_norm,
                        },
                        "audio": {
                            "sr": int(audio_params.sample_rate),
                            "ch": int(audio_params.channels),
                            "codec": audio_params.codec,
                        },
                    }
                }
                meta_path = Path(output_path).with_name(Path(output_path).stem + ".meta.json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)
            except Exception as _e:
                logger.debug(f"Failed to write normalization meta: {_e}")
            return output_path
        except subprocess.CalledProcessError as e:
            # Detect NVENC-specific failure and fallback to CPU once
            msg = (e.stderr or "") + "\n" + (e.stdout or "")
            rc = getattr(e, "returncode", None)
            should_fallback = (
                "exit status 234" in msg
                or "exit code 234" in msg
                or rc == 234
                or "h264_nvenc" in msg
                or "nvenc" in msg.lower()
                or "No NVENC capable devices found" in msg
            )
            if not should_fallback:
                logger.error(f"Error normalizing media {input_path}: {e}")
                logger.error(f"FFmpeg stdout:\n{e.stdout}")
                logger.error(f"FFmpeg stderr:\n{e.stderr}")
                raise

            logger.warning(
                "NVENC failed during normalization. Falling back to libx264 and retrying once."
            )
            prev = os.environ.get("DISABLE_HWENC")
            os.environ["DISABLE_HWENC"] = "1"
            try:
                cmd_cpu = await _build_cmd(disable_hwenc=True)
                await _run_ffmpeg_async(cmd_cpu)
                if Path(output_path).exists():
                    logger.info(
                        f"Successfully normalized (fallback CPU) {input_path} -> {output_path}"
                    )
                else:
                    logger.error(
                        f"Failed to normalize (fallback CPU) {input_path} -> {output_path}"
                    )
                # Write adjacent meta for re-normalization avoidance (CPU fallback)
                try:
                    meta = {
                        "target_spec": {
                            "video": {
                                "width": int(video_params.width),
                                "height": int(video_params.height),
                                "fps": int(video_params.fps),
                                "pix_fmt": video_params.pix_fmt,
                                "codec": "h264",
                                "background_fit": fit_mode_norm,
                                "background_fill_color": fill_norm,
                                "background_anchor": anchor_norm,
                                "background_position": pos_norm,
                            },
                            "audio": {
                                "sr": int(audio_params.sample_rate),
                                "ch": int(audio_params.channels),
                                "codec": audio_params.codec,
                            },
                        }
                    }
                    meta_path = Path(output_path).with_name(Path(output_path).stem + ".meta.json")
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False)
                except Exception as _e:
                    logger.debug(f"Failed to write normalization meta (fallback): {_e}")
                return output_path
            finally:
                if prev is None:
                    os.environ.pop("DISABLE_HWENC", None)
                else:
                    os.environ["DISABLE_HWENC"] = prev

    return await cache_manager.get_or_create(
        key_data=key_data,
        file_name="normalized",
        extension="mp4",
        creator_func=creator_func,
    )
