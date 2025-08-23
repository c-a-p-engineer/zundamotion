# -*- coding: utf-8 -*-
"""
FFmpeg 7 対応のユーティリティ群（全文置き換え用）

ポイント
- 既定で `-threads 0`（自動スレッド化）＋ `-filter_threads N` ＋ `-filter_complex_threads N` を付与
- ハードウェアエンコーダは FFmpeg 7 の挙動にあわせて選択（NVENC: -cq / QSV: -global_quality / CPU: -crf）
- QSV/VAAPI でも **入力側の -hwaccel は原則付与しない**（drawtext/overlay 等を多用するためCPUフィルタと相性を取る）
  - つまり「デコード＋フィルタ＝CPU」「エンコードのみHW」という方針で安定化
- バージョン検出＆エンコーダ存在チェックを強化（`ffmpeg -encoders`）
- 動画長取得の専用関数（`get_media_duration`）を追加（従来の `get_audio_duration` を動画に誤用しない）
"""

import json
import os
import re
import subprocess
from typing import List, Optional, Tuple

from zundamotion.utils.logger import logger


# =========================================================
# 共通: スレッド＆FFmpeg検出
# =========================================================
def get_nproc_value() -> str:
    """利用可能なCPUコア数（>=1 を保証）を文字列で返す。"""
    try:
        n = os.cpu_count() or 1
        if n < 1:
            logger.warning("Could not detect CPU count, defaulting to 1 thread.")
            return "1"
        return str(n)
    except Exception as e:
        logger.error(f"Error getting nproc value: {e}, defaulting to 1 thread.")
        return "1"


def _run_ffmpeg(args: List[str]) -> subprocess.CompletedProcess:
    """ffmpeg/ffprobeを呼び出して CompletedProcess を返す（例外は上位で処理）。"""
    return subprocess.run(args, capture_output=True, text=True, check=True)


def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """FFmpeg のバージョン文字列（例: '7.0.2'）を返す。失敗時 None。"""
    try:
        result = _run_ffmpeg([ffmpeg_path, "-version"])
        m = re.search(r"ffmpeg version (\S+)", result.stdout)
        return m.group(1) if m else None
    except Exception as e:
        logger.error(f"Error getting FFmpeg version: {e}")
        return None


def _ffmpeg_major_version(ffmpeg_path: str = "ffmpeg") -> Optional[int]:
    v = get_ffmpeg_version(ffmpeg_path)
    if not v:
        return None
    # 例: '7.0.2-...'
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else None


def _list_encoders(ffmpeg_path: str = "ffmpeg") -> str:
    """`ffmpeg -encoders` の標準出力（小文字化）を返す。失敗時は空文字。"""
    try:
        result = _run_ffmpeg([ffmpeg_path, "-encoders"])
        return result.stdout.lower()
    except Exception as e:
        logger.error(f"Error listing FFmpeg encoders: {e}")
        return ""


# =========================================================
# ハードウェア検出（FFmpeg 7 向け）
# =========================================================
def get_hardware_encoder_kind(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    利用可能なH.264/HEVCハードウェア「エンコーダ」を判定して返す。
    優先順位: nvenc -> qsv -> vaapi -> videotoolbox -> amf
    戻り値: 'nvenc' | 'qsv' | 'vaapi' | 'videotoolbox' | 'amf' | None
    """
    encs = _list_encoders(ffmpeg_path)

    # まずNVENC
    if " h264_nvenc " in f" {encs} " or " hevc_nvenc " in f" {encs} ":
        return "nvenc"

    # 次にQSV
    if " h264_qsv " in f" {encs} " or " hevc_qsv " in f" {encs} ":
        return "qsv"

    # VAAPI
    if " h264_vaapi " in f" {encs} " or " hevc_vaapi " in f" {encs} ":
        return "vaapi"

    # Apple
    if " h264_videotoolbox " in f" {encs} " or " hevc_videotoolbox " in f" {encs} ":
        return "videotoolbox"

    # AMD AMF（主にWindows）
    if " h264_amf " in f" {encs} " or " hevc_amf " in f" {encs} ":
        return "amf"

    return None


# =========================================================
# エンコーダオプション（FFmpeg 7 向け）
# =========================================================
def get_video_encoder_options(
    ffmpeg_path: str = "ffmpeg",
) -> Tuple[List[str], List[str], List[str]]:
    """
    H.264/HEVC のエンコーダオプション（FFmpeg 7 向け推奨値）を返す。
    戻り値: (hw_accel_input_opts, h264_encoder_opts, hevc_encoder_opts)

    注意:
    - 本関数は **デコード＆フィルタはCPU** 想定。`-hwaccel` は返さない。
      （drawtext/overlay 等のCPUフィルタと混在時のトラブルを避けるため）
    - ハードウェア「エンコード」は積極的に使用。
    - 環境変数で強制切替可:
        DISABLE_HWENC=1 → CPU固定
        FORCE_NVENC=1, FORCE_QSV=1, FORCE_VAAPI=1 → 各HWエンコ強制
    """
    hw_force_off = os.getenv("DISABLE_HWENC", "0") == "1"

    hw_kind_env = (
        "nvenc"
        if os.getenv("FORCE_NVENC") == "1"
        else (
            "qsv"
            if os.getenv("FORCE_QSV") == "1"
            else "vaapi" if os.getenv("FORCE_VAAPI") == "1" else None
        )
    )

    hw_kind = (
        None
        if hw_force_off
        else (hw_kind_env or get_hardware_encoder_kind(ffmpeg_path))
    )

    # 入力側の -hwaccel は返さない（安定性重視）
    hw_accel_input_opts: List[str] = []

    # 既定はCPU（libx264/libx265）
    h264_opts = ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    hevc_opts = ["-c:v", "libx265", "-preset", "fast", "-crf", "28"]  # HEVCはCRF高め

    if hw_kind == "nvenc":
        # NVENC: FFmpeg 7 でも -cq を使用
        h264_opts = ["-c:v", "h264_nvenc", "-preset", "fast", "-cq", "23"]
        hevc_opts = ["-c:v", "hevc_nvenc", "-preset", "fast", "-cq", "28"]
        logger.info("Using NVENC for video encoding.")
    elif hw_kind == "qsv":
        # QSV: FFmpeg 7 では -global_quality を使用（-q は避ける）
        # 品質モードは 'icq' / 'la_icq' などあるが、汎用性重視でICQ相当の指定
        h264_opts = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"]
        hevc_opts = ["-c:v", "hevc_qsv", "-preset", "veryfast", "-global_quality", "28"]
        logger.info("Using QSV for video encoding.")
    elif hw_kind == "vaapi":
        # VAAPI: 明示的な -vaapi_device は「入力側HW化しない」方針のためここでは付けない
        # （CPUでフィルタ→hwエンコはVAAPI非対応が多い。ここでは素直にCPUにフォールバック推奨）
        # それでも使いたい場合は別途呼び出し元で format=nv12,hwupload,scale_vaapi 等を構成すること。
        h264_opts = ["-c:v", "h264_vaapi", "-qp", "23"]
        hevc_opts = ["-c:v", "hevc_vaapi", "-qp", "28"]
        logger.info(
            "Using VAAPI for video encoding (note: filtergraph must be VAAPI-friendly)."
        )
    elif hw_kind == "videotoolbox":
        # Apple VideoToolbox: CRFではなくビットレート指定が一般的
        h264_opts = ["-c:v", "h264_videotoolbox", "-b:v", "5M"]
        hevc_opts = ["-c:v", "hevc_videotoolbox", "-b:v", "5M"]
        logger.info("Using VideoToolbox for video encoding.")
    elif hw_kind == "amf":
        # AMD AMF
        h264_opts = [
            "-c:v",
            "h264_amf",
            "-quality",
            "balanced",
            "-qp_i",
            "23",
            "-qp_p",
            "23",
        ]
        hevc_opts = [
            "-c:v",
            "hevc_amf",
            "-quality",
            "balanced",
            "-qp_i",
            "28",
            "-qp_p",
            "28",
        ]
        logger.info("Using AMF for video encoding.")
    else:
        if hw_force_off:
            logger.info(
                "Hardware encoding disabled by DISABLE_HWENC=1. Falling back to CPU."
            )
        else:
            logger.info(
                "No hardware encoder found. Falling back to CPU (libx264/libx265)."
            )

    return hw_accel_input_opts, h264_opts, hevc_opts


def _threading_flags(ffmpeg_path: str = "ffmpeg") -> List[str]:
    """
    FFmpeg 7 を想定したスレッド設定を返す。
    -threads 0（自動）＋ filter_threads / filter_complex_threads = nproc
    """
    nproc = get_nproc_value()
    return [
        "-threads",
        "0",
        "-filter_threads",
        nproc,
        "-filter_complex_threads",
        nproc,
    ]


# =========================================================
# ffprobe 系
# =========================================================
def get_audio_duration(file_path: str) -> float:
    """音声ファイルの長さ（秒, 小数2桁丸め）。"""
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
        result = _run_ffmpeg(cmd)
        probe = json.loads(result.stdout)
        duration = float(probe["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e}\n{e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def get_media_duration(file_path: str) -> float:
    """音声/動画問わず、コンテナから長さ（秒）を取得。"""
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
        result = _run_ffmpeg(cmd)
        probe = json.loads(result.stdout)
        duration = float(probe["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e}\n{e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


from typing import Any, Dict, List, Optional, Tuple, TypedDict

# ... (既存のインポートは省略)


class VideoInfo(TypedDict, total=False):
    codec_name: str
    width: int
    height: int
    pix_fmt: str
    r_frame_rate: str
    fps: float


class AudioInfo(TypedDict, total=False):
    codec_name: str
    sample_rate: int
    channels: int
    channel_layout: str


class MediaInfo(TypedDict, total=False):
    video: Optional[VideoInfo]
    audio: Optional[AudioInfo]


# ... (既存の関数は省略)


def get_media_info(file_path: str) -> MediaInfo:
    """ffprobe 経由で動画/音声の主要なメタ情報を返す。"""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            file_path,
        ]
        result = _run_ffmpeg(cmd)
        info = json.loads(result.stdout)

        media_info: MediaInfo = {"video": None, "audio": None}

        for s in info.get("streams", []):
            if s.get("codec_type") == "video" and media_info["video"] is None:
                r_rate = s.get("r_frame_rate", "0/0")
                try:
                    num, den = map(int, r_rate.split("/"))
                    fps = float(num) / float(den) if den else 0.0
                except Exception:
                    fps = 0.0
                media_info["video"] = {
                    "codec_name": s.get("codec_name"),
                    "width": int(s.get("width", 0)),
                    "height": int(s.get("height", 0)),
                    "pix_fmt": s.get("pix_fmt"),
                    "r_frame_rate": r_rate,
                    "fps": fps,
                }
            elif s.get("codec_type") == "audio" and media_info["audio"] is None:
                media_info["audio"] = {
                    "codec_name": s.get("codec_name"),
                    "sample_rate": (
                        int(s.get("sample_rate", 0)) if s.get("sample_rate") else 0
                    ),
                    "channels": (int(s.get("channels", 0)) if s.get("channels") else 0),
                    "channel_layout": s.get("channel_layout"),
                }
        return media_info

    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


def compare_media_params(file_paths: List[str]) -> bool:
    """
    複数の動画ファイルの主要なパラメータ（コーデック、解像度、フレームレート、ピクセルフォーマット、
    サンプルレート、チャンネル数、チャンネルレイアウト）が全て一致するかどうかを判定する。
    """
    if not file_paths:
        return True  # ファイルがない場合は一致とみなす

    base_info_val: Optional[MediaInfo] = None
    for i, path in enumerate(file_paths):
        try:
            info = get_media_info(path)
            if i == 0:
                base_info_val = info
            else:
                if base_info_val is None:  # base_info_valがNoneの場合は比較できない
                    logger.warning(
                        f"Base media info is None, cannot compare with {path}"
                    )
                    return False

                # 動画ストリームの比較
                base_video = base_info_val.get("video")
                current_video = info.get("video")
                if base_video and current_video:
                    if not (
                        base_video.get("codec_name") == current_video.get("codec_name")
                        and base_video.get("width") == current_video.get("width")
                        and base_video.get("height") == current_video.get("height")
                        and base_video.get("pix_fmt") == current_video.get("pix_fmt")
                        and base_video.get("r_frame_rate")
                        == current_video.get("r_frame_rate")
                    ):
                        logger.warning(
                            f"Video parameters mismatch between {file_paths[0]} and {path}"
                        )
                        return False
                elif (base_video is not None) != (
                    current_video is not None
                ):  # 片方だけ動画ストリームがある場合
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
                        and base_audio.get("sample_rate")
                        == current_audio.get("sample_rate")
                        and base_audio.get("channels") == current_audio.get("channels")
                        and base_audio.get("channel_layout")
                        == current_audio.get("channel_layout")
                    ):
                        logger.warning(
                            f"Audio parameters mismatch between {file_paths[0]} and {path}"
                        )
                        return False
                elif (base_audio is not None) != (
                    current_audio is not None
                ):  # 片方だけ音声ストリームがある場合
                    logger.warning(
                        f"Audio stream presence mismatch between {file_paths[0]} and {path}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Error comparing media params for {path}: {e}")
            return False
    return True


def concat_videos_copy(
    input_paths: List[str], output_path: str, ffmpeg_path: str = "ffmpeg"
):
    """
    -f concat -c copy を使用して動画を再エンコードなしで結合する。
    事前に compare_media_params でパラメータの一致を確認していることを前提とする。
    """
    if not input_paths:
        logger.warning("No input paths provided for concat_videos_copy.")
        return

    list_file_path = "concat_list.txt"  # 一時ファイル名
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in input_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    cmd = [
        ffmpeg_path,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",  # 危険なファイルパスを許可（絶対パスを使用するため）
        "-i",
        list_file_path,
        "-c",
        "copy",
        output_path,
    ]

    try:
        proc = _run_ffmpeg(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(
            f"Successfully concatenated videos without re-encoding to {output_path}"
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Error concatenating videos with -c copy: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise
    finally:
        if os.path.exists(list_file_path):
            os.remove(list_file_path)


def has_audio_stream(file_path: str) -> bool:
    """動画に音声ストリームがあるか。"""
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
        result = _run_ffmpeg(cmd)
        probe = json.loads(result.stdout)
        return len(probe.get("streams", [])) > 0
    except subprocess.CalledProcessError as e:
        logger.error(
            f"Error running ffprobe to check audio stream for {file_path}: {e}\n{e.stderr}"
        )
        return False
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        return False


# =========================================================
# 変換・生成
# =========================================================
def normalize_video(
    input_path: str,
    output_path: str,
    target_fps: int = 30,
    target_ar: int = 48000,
    ffmpeg_path: str = "ffmpeg",
):
    """
    映像を標準フォーマット（30fps, 48kHz）に正規化。タイムスタンプも補正。
    - デコード＆フィルタ: CPU
    - エンコード: HWエンコ（存在すれば）/ CPU
    """
    video_filter = f"fps={target_fps},setpts=PTS-STARTPTS"
    audio_filter = f"aresample={target_ar},asetpts=PTS-STARTPTS"

    hw_in, h264_enc, _ = get_video_encoder_options(ffmpeg_path)

    cmd = [ffmpeg_path, "-y"]
    cmd.extend(_threading_flags(ffmpeg_path))
    # 入力側HWは付与しない（安定性重視）
    # cmd.extend(hw_in)
    cmd.extend(
        [
            "-i",
            input_path,
            "-vf",
            video_filter,
            "-af",
            audio_filter,
        ]
    )
    cmd.extend(h264_enc)
    cmd.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
    )

    try:
        proc = _run_ffmpeg(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully normalized {input_path} to {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error normalizing video {input_path}: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


def create_silent_audio(
    output_path: str,
    duration: float,
    sample_rate: int = 44100,
    channels: int = 2,
    ffmpeg_path: str = "ffmpeg",
):
    """
    指定秒数の無音WAVを作成（PCM s16le）。
    FFmpeg 7 では anullsrc の cl は 'mono' / 'stereo' 指定が安全。
    """
    cl = "mono" if channels == 1 else "stereo"
    cmd = [
        ffmpeg_path,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl={cl}",
        "-t",
        str(duration),
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    try:
        _run_ffmpeg(cmd)
        logger.debug(f"Created silent audio: {output_path} ({duration}s)")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error creating silent audio file {output_path}: {e}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        raise


def add_bgm_to_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    bgm_volume: float = 0.5,
    bgm_start_time: float = 0.0,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    video_duration: Optional[float] = None,
    ffmpeg_path: str = "ffmpeg",
):
    """
    BGM を動画にミックス。動画側に音声がなければBGMのみを載せる。
    - デコード＆フィルタ: CPU
    - 映像はコピー（`-c:v copy`）で再エンコード回避
    """
    if video_duration is None:
        video_duration = get_media_duration(video_path)

    bgm_duration = get_audio_duration(bgm_path)
    _ = min(video_duration, bgm_start_time + bgm_duration)  # 有効長（使い道があれば）

    cmd = [ffmpeg_path, "-y"]
    cmd.extend(_threading_flags(ffmpeg_path))
    cmd.extend(["-i", video_path, "-i", bgm_path, "-filter_complex"])

    video_has_audio = has_audio_stream(video_path)

    # BGM用フィルタ
    af = [f"volume={bgm_volume}"]
    if fade_in_duration > 0:
        af.append(f"afade=t=in:st=0:d={fade_in_duration}")
    if fade_out_duration > 0:
        st = max(0.0, bgm_duration - fade_out_duration)
        af.append(f"afade=t=out:st={st}:d={fade_out_duration}")
    bgm_chain = f"[1:a]{','.join(af)}[bgm_filtered]"
    delayed = f"[bgm_filtered]adelay={int(bgm_start_time * 1000)}:all=1[delayed_bgm]"

    if video_has_audio:
        # 元音声 + BGM をミックス
        filter_complex = f"{bgm_chain};{delayed};[0:a][delayed_bgm]amix=inputs=2:duration=shortest[aout]"
        cmd.append(filter_complex)
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
        # 元音声がない→ BGMのみ
        filter_complex = f"{bgm_chain};{delayed}"
        cmd.append(filter_complex)
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
        proc = _run_ffmpeg(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully added BGM to {video_path} -> {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding BGM to video: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


def apply_transition(
    input_video1_path: str,
    input_video2_path: str,
    output_path: str,
    transition_type: str,
    duration: float,
    offset: float,
    ffmpeg_path: str = "ffmpeg",
):
    """
    映像: xfade、音声: acrossfade でクロスフェード。
    - デコード＆フィルタ: CPU
    - エンコード: HW（存在すれば）/ CPU
    """
    has_a1 = has_audio_stream(input_video1_path)
    has_a2 = has_audio_stream(input_video2_path)

    _, h264_enc, _ = get_video_encoder_options(ffmpeg_path)

    cmd = [ffmpeg_path, "-y"]
    cmd.extend(_threading_flags(ffmpeg_path))
    cmd.extend(["-i", input_video1_path, "-i", input_video2_path])

    vf = f"[0:v][1:v]xfade=transition={transition_type}:duration={duration}:offset={offset}[v]"
    parts = [vf]

    if has_a1 and has_a2:
        af = (
            "[0:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a0];"
            "[1:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a1];"
            f"[a0][a1]acrossfade=d={duration}:c1=tri:c2=tri[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    elif has_a1:
        af = (
            "[0:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"afade=t=out:st={offset}:d={duration}[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    elif has_a2:
        delay_ms = int(offset * 1000)
        af = (
            "[1:a]aresample=async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"adelay={delay_ms}:all=1,afade=t=in:st=0:d={duration}[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", vf, "-map", "[v]"]

    # 映像エンコード設定（FFmpeg 7 推奨に準拠）
    cmd.extend(h264_enc)
    cmd.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
    )

    try:
        proc = _run_ffmpeg(cmd)
        logger.debug("FFmpeg stdout:\n%s", proc.stdout)
        logger.debug("FFmpeg stderr:\n%s", proc.stderr)
        logger.info(
            "Applied '%s' transition with audio crossfade: %s + %s -> %s",
            transition_type,
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


def mix_audio_tracks(
    audio_tracks: List[Tuple[str, float, float]],
    output_path: str,
    total_duration: float,
    ffmpeg_path: str = "ffmpeg",
):
    """
    複数音声（path, start_time(sec), volume）をミックスし MP3 で出力。
    """
    try:
        cmd = [ffmpeg_path, "-y"]
        cmd.extend(_threading_flags(ffmpeg_path))

        # 入力
        for track in audio_tracks:
            cmd.extend(["-i", track[0]])

        # フィルタ構築
        parts = []
        for i, (_, start, vol) in enumerate(audio_tracks):
            parts.append(f"[{i}:a]volume={vol},adelay={int(start * 1000)}:all=1[a{i}]")
        mix_in = "".join(f"[a{i}]" for i in range(len(audio_tracks)))
        parts.append(
            f"{mix_in}amix=inputs={len(audio_tracks)}:dropout_transition=0[aout]"
        )

        cmd.extend(["-filter_complex", ";".join(parts), "-map", "[aout]"])
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
        proc = _run_ffmpeg(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully mixed audio tracks to {output_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Error mixing audio tracks: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise
