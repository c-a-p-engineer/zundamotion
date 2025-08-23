# -*- coding: utf-8 -*-
import json
import os
import re
import subprocess
from pathlib import Path  # Add this import
from typing import Any, Dict, List, Optional, Tuple

from zundamotion.cache import CacheManager
from zundamotion.exceptions import PipelineError  # Add this import
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_utils import (  # Add this import
    _threading_flags,
    get_video_encoder_options,
)
from zundamotion.utils.logger import logger, time_log

# ========== 基本ユーティリティ ==========


def get_nproc_value() -> str:
    """利用可能CPU数（スレッド数目安）"""
    try:
        n = os.cpu_count()
        if not n or n < 1:
            logger.warning("Could not detect CPU count, defaulting to 1 thread.")
            return "1"
        return str(n)
    except Exception as e:
        logger.error(f"Error getting nproc value: {e}, defaulting to 1 thread.")
        return "1"


def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """FFmpegのバージョン文字列を返す"""
    try:
        r = subprocess.run(
            [ffmpeg_path, "-version"], capture_output=True, text=True, check=True
        )
        m = re.search(r"ffmpeg version (\S+)", r.stdout)
        return m.group(1) if m else None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Error getting FFmpeg version: {e}")
        return None


# ========== エンコーダ選択（ffmpeg7/QSV対応） ==========


def _qsv_device_available() -> bool:
    """Dockerなどで /dev/dri がマウントされているかの簡易判定"""
    return os.path.exists("/dev/dri/renderD128") or os.path.exists("/dev/dri/card0")


def _probe_qsv_encode(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    QSVエンコードが実際に初期化できるか、極小ジョブで実行して確認。
    成功: True / 失敗: False
    """
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=size=64x64:rate=30:duration=0.1:color=black",
        "-frames:v",
        "1",
        "-c:v",
        "h264_qsv",
        "-f",
        "null",
        "-",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        msg = (
            (e.stderr or "").strip().splitlines()[-1]
            if (e.stderr or "")
            else "qsv open failed"
        )
        logger.info(f"[Encoder] QSV probe failed: {msg}")
        return False


def _pick_encoder(ffmpeg_path: str = "ffmpeg") -> Dict[str, Any]:
    """
    FFmpeg7を前提に、QSV可否を実プローブしてから H.264/HEVC のオプションと pix_fmt を返す。
    返却:
      {
        "using_qsv": bool,
        "h264": ["-c:v", "...", ...],
        "hevc": ["-c:v", "...", ...],
        "pix_fmt": "nv12" or "yuv420p"
      }
    """
    force_cpu = os.environ.get("ZUNDAMOTION_FORCE_CPU") == "1"
    force_qsv = os.environ.get("ZUNDAMOTION_FORCE_QSV") == "1"

    use_qsv = False
    if not force_cpu:
        if _qsv_device_available() or force_qsv:
            use_qsv = _probe_qsv_encode(ffmpeg_path)

    if use_qsv:
        logger.info("Using QSV for video encoding.")
        return {
            "using_qsv": True,
            "h264": [
                "-c:v",
                "h264_qsv",
                "-preset",
                "veryfast",
                "-global_quality",
                "23",
            ],
            "hevc": [
                "-c:v",
                "hevc_qsv",
                "-preset",
                "veryfast",
                "-global_quality",
                "28",
            ],
            "pix_fmt": "nv12",
        }
    else:
        logger.info("Using CPU (libx264/libx265) for video encoding.")
        return {
            "using_qsv": False,
            "h264": ["-c:v", "libx264", "-preset", "fast", "-crf", "23"],
            "hevc": ["-c:v", "libx265", "-preset", "fast", "-crf", "28"],
            "pix_fmt": "yuv420p",
        }


# 既存コード互換: (hw_accel_options, h264_opts, hevc_opts) を返すAPIを維持
def get_video_encoder_options(
    ffmpeg_path: str = "ffmpeg",
) -> Tuple[List[str], List[str], List[str]]:
    """
    旧API互換。内部では実プローブした結果を使い、-hwaccel は返さない（フィルタとの相性問題回避）。
    """
    enc = _pick_encoder(ffmpeg_path)
    return [], enc["h264"], enc["hevc"]


# pix_fmt も欲しい場合のヘルパ
def get_encoder_and_pix_fmt(
    ffmpeg_path: str = "ffmpeg",
) -> Tuple[List[str], List[str], str, bool]:
    """
    (h264_opts, hevc_opts, pix_fmt, using_qsv) を返す
    """
    enc = _pick_encoder(ffmpeg_path)
    return enc["h264"], enc["hevc"], enc["pix_fmt"], enc["using_qsv"]


# ========== メディア情報/変換 ==========


def get_audio_duration(file_path: str) -> float:
    """ffprobeで音声(または動画)の長さを秒で取得"""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        probe = json.loads(result.stdout)
        return round(float(probe["format"]["duration"]), 2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e}")
        logger.error(e.stderr)
        raise
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def get_media_info(file_path: str) -> dict:
    """ffprobeで基本の video/audio 情報を返す"""
    try:
        cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)

        v = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
        )
        a = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None
        )

        media = {}
        if v:
            r = v.get("r_frame_rate", "0/0")
            num, den = (int(x) for x in r.split("/")) if "/" in r else (0, 0)
            fps = float(num) / float(den) if den else 0.0
            media["video"] = {
                "width": int(v.get("width", 0)),
                "height": int(v.get("height", 0)),
                "pix_fmt": v.get("pix_fmt"),
                "r_frame_rate": r,
                "fps": fps,
            }
        if a:
            media["audio"] = {
                "sample_rate": int(a.get("sample_rate", 0)),
                "channels": int(a.get("channels", 0)),
                "channel_layout": a.get("channel_layout"),
            }
        return media
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def normalize_video(
    input_path: str, output_path: str, target_fps: int = 30, target_ar: int = 48000
):
    """
    30fps・48kHzに正規化。PTS をリセット。
    """
    vf = f"fps={target_fps},setpts=PTS-STARTPTS"
    af = f"aresample={target_ar},asetpts=PTS-STARTPTS"

    h264_opts, _, pix_fmt, _ = get_encoder_and_pix_fmt()

    cmd = [
        "ffmpeg",
        "-y",
        "-threads",
        "0",
        "-filter_threads",
        get_nproc_value(),
        "-filter_complex_threads",
        get_nproc_value(),
        "-i",
        input_path,
        "-vf",
        vf,
        "-af",
        af,
    ]
    cmd.extend(h264_opts)
    cmd.extend(["-pix_fmt", pix_fmt, "-c:a", "aac", "-b:a", "192k", output_path])

    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully normalized {input_path} -> {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error normalizing video {input_path}: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


def create_silent_audio(
    output_path: str, duration: float, sample_rate: int = 44100, channels: int = 2
):
    """無音WAVの作成"""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl={channels}",
        "-t",
        str(duration),
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug(f"Created silent audio: {output_path} ({duration}s)")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error creating silent audio file {output_path}: {e}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        raise


def has_audio_stream(file_path: str) -> bool:
    """映像ファイルに音声ストリームがあるか"""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            file_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(r.stdout)
        return len(data.get("streams", [])) > 0
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Error running ffprobe to check audio stream for {file_path}: {e}"
        )
        logger.error(e.stderr)
        return False
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        return False


# ========== BGM 合成 ==========


def add_bgm_to_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    bgm_volume: float = 0.5,
    bgm_start_time: float = 0.0,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    video_duration: Optional[float] = None,
):
    """動画にBGMをミックス。元動画に音声が無ければBGMのみを載せる。"""
    if video_duration is None:
        video_duration = get_audio_duration(video_path)
    bgm_duration = get_audio_duration(bgm_path)

    nproc = get_nproc_value()
    cmd = [
        "ffmpeg",
        "-y",
        "-threads",
        "0",
        "-filter_threads",
        nproc,
        "-filter_complex_threads",
        nproc,
        "-i",
        video_path,
        "-i",
        bgm_path,
        "-filter_complex",
    ]

    video_has_audio = has_audio_stream(video_path)

    # BGM のボリューム／フェード
    afs: List[str] = [f"volume={bgm_volume}"]
    if fade_in_duration > 0:
        afs.append(f"afade=t=in:st=0:d={fade_in_duration}")
    if fade_out_duration > 0:
        st = max(0.0, bgm_duration - fade_out_duration)
        afs.append(f"afade=t=out:st={st}:d={fade_out_duration}")

    bgm_filter = f"[1:a]{','.join(afs)}[bgm_filtered]"
    delay = f"[bgm_filtered]adelay={int(bgm_start_time*1000)}:all=1[delayed_bgm]"

    if video_has_audio:
        # 元音声 + BGM
        fcs = f"{bgm_filter};{delay};[0:a][delayed_bgm]amix=inputs=2:duration=shortest[aout]"
        cmd.append(fcs)
        cmd.extend(
            [
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                output_path,
            ]
        )
    else:
        # BGMのみ
        fcs = f"{bgm_filter};{delay}"
        cmd.append(fcs)
        cmd.extend(
            [
                "-map",
                "0:v",
                "-map",
                "[delayed_bgm]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                output_path,
            ]
        )

    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully added BGM to {video_path} -> {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding BGM: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


# ========== トランジション（xfade / acrossfade） ==========


def apply_transition(
    input_video1_path: str,
    input_video2_path: str,
    output_path: str,
    transition_type: str,
    duration: float,
    offset: float,
):
    """
    xfade で映像、acrossfade で音声をクロス。ffmpeg7/QSVを考慮して自動でエンコーダ＆pix_fmtを選択。
    """
    has_audio1 = has_audio_stream(input_video1_path)
    has_audio2 = has_audio_stream(input_video2_path)

    # エンコーダ選択
    h264_opts, _, pix_fmt, using_qsv = get_encoder_and_pix_fmt()

    nproc = get_nproc_value()
    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-threads",
        "0",
        "-filter_threads",
        nproc,
        "-filter_complex_threads",
        nproc,
        "-i",
        input_video1_path,
        "-i",
        input_video2_path,
    ]

    vf = f"[0:v][1:v]xfade=transition={transition_type}:duration={duration}:offset={offset}[v]"
    parts = [vf]

    if has_audio1 and has_audio2:
        af = (
            "[0:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1];"
            f"[a0][a1]acrossfade=d={duration}:c1=tri:c2=tri[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    elif has_audio1:
        af = (
            "[0:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"afade=t=out:st={offset}:d={duration}[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    elif has_audio2:
        delay_ms = int(offset * 1000)
        af = (
            "[1:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},afade=t=in:st=0:d={duration}[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", vf, "-map", "[v]"]

    # エンコード設定（QSV なら nv12、CPU なら yuv420p）
    cmd.extend(h264_opts)
    cmd.extend(["-pix_fmt", pix_fmt, "-c:a", "aac", "-b:a", "192k", output_path])

    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug("FFmpeg stdout:\n%s", proc.stdout)
        logger.debug("FFmpeg stderr:\n%s", proc.stderr)
        logger.info(
            "Applied '%s' transition (d=%.2f, offset=%.2f): %s + %s -> %s",
            transition_type,
            duration,
            offset,
            input_video1_path,
            input_video2_path,
            output_path,
        )
    except subprocess.CalledProcessError as e:
        logger.error("Error applying transition: %s", e)
        logger.error("FFmpeg stdout:\n%s", e.stdout)
        logger.error("FFmpeg stderr:\n%s", e.stderr)
        raise


# ========== オーバーレイ位置計算 ==========


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
    overlay の x,y 式をアンカーとオフセットから算出
    """
    x_expr = "0"
    y_expr = "0"

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


# ========== 複数音源ミックス ==========


def mix_audio_tracks(
    audio_tracks: List[Tuple[str, float, float]],
    output_path: str,
    total_duration: float,
):
    """
    複数音源をボリューム＆ディレイ指定でミックス（libmp3lame 出力）
    audio_tracks = [(path, start_time_sec, volume), ...]
    """
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-threads",
            "0",
            "-filter_threads",
            get_nproc_value(),
            "-filter_complex_threads",
            get_nproc_value(),
        ]

        for i, t in enumerate(audio_tracks):
            cmd.extend(["-i", t[0]])

        # 各トラックに volume と delay を適用してから amix
        filter_complex = ""
        for i, (path, start_time, volume) in enumerate(audio_tracks):
            filter_complex += (
                f"[{i}:a]volume={volume},adelay={int(start_time*1000)}:all=1[a{i}];"
            )
        mix_inputs = "".join([f"[a{i}]" for i in range(len(audio_tracks))])
        filter_complex += (
            f"{mix_inputs}amix=inputs={len(audio_tracks)}:dropout_transition=0[aout]"
        )

        cmd.extend(["-filter_complex", filter_complex, "-map", "[aout]"])
        cmd.extend(
            [
                "-acodec",
                "libmp3lame",
                "-ab",
                "192k",
                "-t",
                str(total_duration),
                output_path,
            ]
        )

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.debug(f"FFmpeg stdout:\n{r.stdout}")
        logger.debug(f"FFmpeg stderr:\n{r.stderr}")
        logger.info(f"Successfully mixed audio tracks -> {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error mixing audio tracks: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


class FinalizePhase:
    def __init__(
        self, config: Dict[str, Any], temp_dir: Path, cache_manager: CacheManager
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager

    @time_log(logger)
    def run(
        self,
        scenes: List[Dict[str, Any]],
        timeline: Timeline,
        line_data_map: Dict[str, Dict[str, Any]],
        scene_video_paths: List[Path],  # Dict[str, Path] から List[Path] に変更
        used_voicevox_info: List[Tuple[int, str]],
    ) -> Path:
        """Phase 4: Finalize the video."""
        logger.info("FinalizePhase: Finalizing video...")

        if not scene_video_paths:
            raise PipelineError("No video clips to finalize.")

        # 結合リストファイルを作成
        concat_list_path = self.temp_dir / "concat_list.txt"
        total_expected_duration = 0.0
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for i, p in enumerate(scene_video_paths):
                f.write(f"file '{p.resolve()}'\n")
                try:
                    duration = get_audio_duration(str(p.resolve()))
                    logger.info(
                        f"FinalizePhase: Clip {i+1}: '{p.name}' duration: {duration:.2f}s"
                    )
                    total_expected_duration += duration
                except Exception as e:
                    logger.warning(
                        f"FinalizePhase: Could not get duration for '{p.name}': {e}"
                    )

        logger.info(
            f"FinalizePhase: Total expected duration from clips: {total_expected_duration:.2f}s"
        )

        output_video_path = self.temp_dir / "final_output.mp4"

        # FFmpeg concat デマルチプレクサを使用して動画を結合
        # ffmpeg_utils からスレッド設定を取得
        _, h264_enc, _ = get_video_encoder_options()
        threading_flags = _threading_flags()

        # FFmpeg concat フィルターを使用して動画を結合
        # ffmpeg_utils からスレッド設定を取得
        _, h264_enc, _ = get_video_encoder_options()
        threading_flags = _threading_flags()

        cmd = [
            "ffmpeg",
            "-y",
        ]
        cmd.extend(threading_flags)

        # 各シーン動画を個別の入力として追加
        for p in scene_video_paths:
            cmd.extend(["-i", str(p.resolve())])

        # concat フィルターの構築
        # 各入力ストリームを [i:v] と [i:a] として参照し、concat フィルターに渡す
        # v=1:a=1:shortest=1 で動画と音声を1つずつ出力し、最短のストリームに合わせる
        num_clips = len(scene_video_paths)

        # 動画ストリームと音声ストリームをそれぞれ concat する
        video_inputs = "".join([f"[{i}:v]" for i in range(num_clips)])
        audio_inputs = "".join([f"[{i}:a]" for i in range(num_clips)])

        filter_complex = (
            f"{video_inputs}concat=n={num_clips}:v=1:a=0[v_out];"
            f"{audio_inputs}concat=n={num_clips}:v=0:a=1[a_out]"
        )

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(
            ["-map", "[v_out]", "-map", "[a_out]"]
        )  # フィルターからの出力をマップ

        cmd.extend(h264_enc)
        cmd.extend(
            [
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",  # 最も短い入力ストリームの長さに合わせる
                str(output_video_path),  # Pathオブジェクトをstrに変換
            ]
        )

        logger.info(f"FinalizePhase: FFmpeg concat command: {' '.join(cmd)}")

        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
            logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
            logger.info(
                f"Successfully concatenated all scene videos to {output_video_path}"
            )

            # 最終動画の長さを取得してログに出力
            final_video_duration = get_audio_duration(str(output_video_path))
            logger.info(
                f"FinalizePhase: Final video '{output_video_path.name}' actual duration: {final_video_duration:.2f}s"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Error concatenating final video: {e}")
            logger.error(f"FFmpeg stdout:\n{e.stdout}")
            logger.error(f"FFmpeg stderr:\n{e.stderr}")
            raise PipelineError(f"Failed to finalize video: {e}")

        return output_video_path
