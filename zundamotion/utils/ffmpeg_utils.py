# -*- coding: utf-8 -*-
"""
FFmpeg 7 対応のユーティリティ群（全文置き換え用）

ポイント
- 既定で `-threads 0`（自動スレッド化）＋ `-filter_threads N` ＋ `-filter_complex_threads N` を付与
- ハードウェアエンコーダは FFmpeg 7 の挙動にあわせて選択（NVENC: -cq / QSV: -global_quality / CPU: -crf）
- QSV/VAAPI でも **入力側の -hwaccel は原則付与しない**（overlay 等を多用するためCPUフィルタと相性を取る）
  - つまり「デコード＋フィルタ＝CPU」「エンコードのみHW」という方針で安定化
- バージョン検出＆エンコーダ存在チェックを強化（`ffmpeg -encoders`）
- 動画長取得の専用関数（`get_media_duration`）を追加（従来の `get_audio_duration` を動画に誤用しない）
"""
from __future__ import annotations  # 循環参照を避けるため追加

import asyncio
import json
import os
import platform  # is_nvenc_available で利用
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path  # ここに移動
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from zundamotion.utils.logger import logger


# =========================================================
# データクラス
# =========================================================
@dataclass
class VideoParams:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    pix_fmt: str = "yuv420p"
    profile: str = "high"  # H.264/HEVC プロファイル (例: 'main', 'high')
    level: str = "4.2"  # H.264/HEVC レベル (例: '4.2')
    preset: str = (
        "medium"  # エンコーダプリセット (例: 'p4' for NVENC, 'veryfast' for libx264)
    )
    bitrate_kbps: Optional[int] = (
        None  # ビットレート (kbps)。指定しない場合は CRF/CQ を使用
    )
    crf: Optional[int] = (
        None  # CRF 値 (CPUエンコーダ用)。指定しない場合はデフォルト値を使用
    )
    cq: Optional[int] = None  # CQ 値 (NVENC用)。指定しない場合はデフォルト値を使用
    global_quality: Optional[int] = None  # QSV用。指定しない場合はデフォルト値を使用
    qp: Optional[int] = None  # VAAPI/AMF用。指定しない場合はデフォルト値を使用

    def to_ffmpeg_opts(self, hw_kind: Optional[str] = None) -> List[str]:
        opts: List[str] = []
        opts.extend(["-fps_mode", "cfr"])  # FPS固定
        opts.extend(["-r", str(self.fps)])
        opts.extend(["-s", f"{self.width}x{self.height}"])
        opts.extend(["-pix_fmt", self.pix_fmt])
        opts.extend(["-profile:v", self.profile])
        opts.extend(["-level:v", self.level])

        if hw_kind == "nvenc":
            opts.extend(["-c:v", "h264_nvenc"])
            opts.extend(["-preset", self.preset])
            if self.cq is not None:
                opts.extend(["-cq", str(self.cq)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-cq", "23"])  # デフォルト
        elif hw_kind == "qsv":
            opts.extend(["-c:v", "h264_qsv"])
            if self.global_quality is not None:
                opts.extend(["-global_quality", str(self.global_quality)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-global_quality", "23"])  # デフォルト
        elif hw_kind == "vaapi":
            opts.extend(["-c:v", "h264_vaapi"])
            if self.qp is not None:
                opts.extend(["-qp", str(self.qp)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-qp", "23"])  # デフォルト
        elif hw_kind == "amf":
            opts.extend(["-c:v", "h264_amf"])
            if self.qp is not None:
                opts.extend(["-qp", str(self.qp)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-qp", "23"])  # デフォルト
        elif hw_kind == "videotoolbox":
            opts.extend(["-c:v", "h264_videotoolbox"])
            if self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-b:v", "5M"])  # デフォルト
        else:  # CPU
            opts.extend(["-c:v", "libx264"])
            # Map NVENC-style presets (p7..p1) to libx264 presets if present
            preset = self.preset
            if isinstance(preset, str) and preset.startswith("p"):
                mapping = {
                    "p7": "ultrafast",
                    "p6": "veryfast",
                    "p5": "medium",
                    "p4": "slow",
                    "p3": "slower",
                    "p2": "veryslow",
                    "p1": "veryslow",
                }
                preset = mapping.get(preset, "medium")
            opts.extend(["-preset", preset])
            if self.crf is not None:
                opts.extend(["-crf", str(self.crf)])
            elif self.bitrate_kbps is not None:
                opts.extend(["-b:v", f"{self.bitrate_kbps}k"])
            else:
                opts.extend(["-crf", "23"])  # デフォルト

        return opts


@dataclass
class AudioParams:
    sample_rate: int = 48000
    channels: int = 2
    codec: str = "libmp3lame"  # デフォルトを libmp3lame に変更
    bitrate_kbps: int = 192

    def to_ffmpeg_opts(self) -> List[str]:
        opts: List[str] = []
        # libmp3lame が確実に有効化されている前提で、直接指定
        opts.extend(["-c:a", "libmp3lame"])
        opts.extend(["-b:a", f"{self.bitrate_kbps}k"])
        opts.extend(["-ar", str(self.sample_rate)])
        opts.extend(["-ac", str(self.channels)])
        # libmp3lame の品質オプションを追加 (ユーザー指定のビットレートを優先するため、-q:a は削除)
        # opts.extend(["-q:a", "2"]) # 可変ビットレート品質 (0-9, 2は高品質)

        return opts


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


async def _run_ffmpeg_async(args: List[str]) -> subprocess.CompletedProcess:
    """ffmpeg/ffprobeを非同期で呼び出して CompletedProcess を返す（例外は上位で処理）。"""
    try:
        logger.debug(f"Running FFmpeg command: {' '.join(args)}")
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stdout_str = stdout.decode(errors="ignore")
        stderr_str = stderr.decode(errors="ignore")

        if process.returncode != 0:
            logger.error(f"FFmpeg command failed with exit code {process.returncode}")
            logger.debug(f"Command: {' '.join(map(str, args))}")  # コマンドはDEBUGに
            if stdout_str:
                logger.debug(f"FFmpeg stdout:\n{stdout_str}")  # stdoutはDEBUGに
            if stderr_str:
                logger.debug(f"FFmpeg stderr:\n{stderr_str}")  # stderrはDEBUGに
            raise subprocess.CalledProcessError(
                process.returncode if process.returncode is not None else 0,
                args,
                output=stdout_str,
                stderr=stderr_str,
            )

        if stderr_str:
            logger.debug(f"FFmpeg stderr (on success):\n{stderr_str}")

        return subprocess.CompletedProcess(
            args, process.returncode, stdout_str, stderr_str
        )

    except FileNotFoundError:
        logger.error(
            f"FFmpeg or FFprobe command not found. Please ensure it's installed and in your PATH."
        )
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred while running FFmpeg command: {e}")
        raise


async def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """FFmpeg のバージョン文字列（例: '7.0.2'）を返す。失敗時 None。"""
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-version"])
        m = re.search(r"ffmpeg version (\S+)", result.stdout)
        return m.group(1) if m else None
    except Exception as e:
        logger.error(f"Error getting FFmpeg version: {e}")
        return None


async def _ffmpeg_major_version(ffmpeg_path: str = "ffmpeg") -> Optional[int]:
    v = await get_ffmpeg_version(ffmpeg_path)
    if not v:
        return None
    # 例: '7.0.2-...'
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else None


# =========================================================
# 同期ラッパー
# =========================================================
async def run_ffmpeg_async(cmd: List[str]) -> subprocess.CompletedProcess:
    """
    _run_ffmpeg_async の非同期ラッパー。
    CacheManager から呼び出されることを想定。
    """
    try:
        return await _run_ffmpeg_async(cmd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e.stderr[:500]}") from e
    except Exception as e:
        raise RuntimeError(f"ffmpeg execution failed: {e}") from e


# =========================================================
# ffprobe 系 (同期版)
# =========================================================
async def probe_media_params_async(path: Path) -> Dict[str, Any]:
    """
    ffprobeで最小限の情報を取得（非同期版）。
    CacheManager から呼び出されることを想定。
    """
    try:
        media_info = await get_media_info(str(path))

        result: Dict[str, Any] = {}
        video_info = media_info.get("video")
        if video_info:
            result["width"] = video_info.get("width")
            result["height"] = video_info.get("height")
            result["fps"] = video_info.get("fps")
            result["pix_fmt"] = video_info.get("pix_fmt")
            result["vcodec"] = video_info.get("codec_name")

        audio_info = media_info.get("audio")
        if audio_info:
            result["asr"] = audio_info.get("sample_rate")
            result["ach"] = audio_info.get("channels")
            result["acodec"] = audio_info.get("codec_name")
        return result
    except Exception as e:
        logger.error(f"Error probing media params for {path}: {e}")
        return {}


# =========================================================
# build_normalize_cmd (同期版)
# =========================================================
async def build_normalize_cmd_async(
    input_path: Path, output_path: Path, target_spec: Dict, use_copy: bool
) -> List[str]:
    """
    正規化のためのffmpegコマンドを構築（非同期版）。
    CacheManager から呼び出されることを想定。
    """
    if use_copy:
        # 完全一致時は -c copy（マップを明示）
        return [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            str(output_path),
        ]

    # 変換が必要な場合
    v = target_spec.get("video", {})
    a = target_spec.get("audio", {})

    # NVENC等の選択は既存ロジックを流用
    nvenc_available = await is_nvenc_available()
    vcodec = (
        "h264_nvenc"
        if nvenc_available and (v.get("codec") in [None, "h264"])
        else "libx264"
    )
    acodec = a.get("codec", "aac")

    args = ["ffmpeg", "-y", "-i", str(input_path), "-map", "0:v:0", "-map", "0:a:0?"]

    # 映像フィルタ（解像度・fps・pix_fmt）
    vf = []
    if v.get("width") and v.get("height"):
        vf.append(f"scale={v['width']}:{v['height']}:flags=bicubic")
    if v.get("fps"):
        args += ["-r", str(int(v["fps"]))]  # 出力fps

    if vf:
        args += ["-vf", ",".join(vf)]

    if v.get("pix_fmt"):
        args += ["-pix_fmt", v["pix_fmt"]]

    # コーデックと高速プリセット
    args += ["-c:v", vcodec, "-preset", "fast", "-tune", "zerolatency"]

    # 音声
    if a.get("sr"):
        args += ["-ar", str(int(a["sr"]))]
    if a.get("ch"):
        args += ["-ac", str(int(a["ch"]))]
    args += ["-c:a", acodec]

    args += [str(output_path)]
    return args


async def _list_encoders(ffmpeg_path: str = "ffmpeg") -> str:
    """`ffmpeg -encoders` の標準出力（小文字化）を返す。失敗時は空文字。"""
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-encoders"])
        return result.stdout.lower()
    except Exception as e:
        logger.error(f"Error listing FFmpeg encoders: {e}")
        return ""


async def _list_audio_encoders(ffmpeg_path: str = "ffmpeg") -> str:
    """`ffmpeg -encoders` の標準出力から音声エンコーダのみを抽出し、小文字化して返す。失敗時は空文字。"""
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-encoders"])
        audio_encoders = []
        for line in result.stdout.splitlines():
            # 例: "A....D aac                  AAC (Advanced Audio Coding)"
            # または "A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)"
            match = re.search(r"A\.{4}D\s+(\S+)\s+.*audio encoder", line)
            if match:
                audio_encoders.append(match.group(1).lower())
        return " ".join(audio_encoders)
    except Exception as e:
        logger.error(f"Error listing FFmpeg audio encoders: {e}")
        return ""


# =========================================================
# ハードウェア検出（FFmpeg 7 向け）
# =========================================================
_nvenc_availability_cache: Dict[str, bool] = {}
# 同一プロセス内での重複スモークテスト実行を防ぐためのタスクキャッシュとロック
_nvenc_availability_tasks: Dict[str, asyncio.Task] = {}
_nvenc_lock = asyncio.Lock()


async def is_nvenc_available(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    h264_nvencエンコーダが利用可能かスモークテストで確認する。
    - 最初の1回のみスモークテストを実施し、以降は結果をキャッシュ。
    - 並行呼び出し時も単一タスクに集約（同時多重実行を防止）。
    """
    # 既に判定済みなら即返す
    if ffmpeg_path in _nvenc_availability_cache:
        logger.debug(f"NVENC availability for '{ffmpeg_path}' retrieved from cache.")
        return _nvenc_availability_cache[ffmpeg_path]

    async def _compute() -> bool:
        # 'h264_nvenc' がエンコーダ一覧に存在するかを先に確認（高速失敗）
        try:
            encoders = await _list_encoders(ffmpeg_path)
            if "h264_nvenc" not in encoders:
                logger.info("h264_nvenc not found in `ffmpeg -encoders` list.")
                _nvenc_availability_cache[ffmpeg_path] = False
                return False
        except Exception as e:
            logger.error(f"Error listing FFmpeg encoders: {e}")
            _nvenc_availability_cache[ffmpeg_path] = False
            return False

        # スモークテスト（最速プリセットで極小フレームをエンコード）
        logger.info("Performing a quick smoke test for h264_nvenc...")
        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=128x128:d=0.1",
            "-vcodec",
            "h264_nvenc",
            "-preset",
            "p1",
            "-f",
            "null",
            "-",
        ]
        try:
            await _run_ffmpeg_async(cmd)
            logger.info("h264_nvenc smoke test successful. NVENC is available.")
            _nvenc_availability_cache[ffmpeg_path] = True
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(
                "h264_nvenc smoke test failed. NVENC is not available or not configured correctly. Falling back to CPU."
            )
            logger.debug(f"FFmpeg stderr for smoke test:\n{e.stderr}")
            _nvenc_availability_cache[ffmpeg_path] = False
            return False
        except FileNotFoundError:
            logger.error(f"ffmpeg command not found at '{ffmpeg_path}'.")
            _nvenc_availability_cache[ffmpeg_path] = False
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during NVENC smoke test: {e}")
            _nvenc_availability_cache[ffmpeg_path] = False
            return False

    # 並行呼び出しを単一化
    async with _nvenc_lock:
        # ロック獲得後に再確認（他のタスクでキャッシュされた可能性）
        if ffmpeg_path in _nvenc_availability_cache:
            return _nvenc_availability_cache[ffmpeg_path]
        task = _nvenc_availability_tasks.get(ffmpeg_path)
        if task is None:
            task = asyncio.create_task(_compute())
            _nvenc_availability_tasks[ffmpeg_path] = task

    try:
        result = await task
        return result
    finally:
        # 完了後はタスクキャッシュを掃除
        async with _nvenc_lock:
            _nvenc_availability_tasks.pop(ffmpeg_path, None)


async def has_cuda_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    """overlay_cuda と scale_cuda が使えるかを確認"""
    try:
        result = await _run_ffmpeg_async(  # subprocess.run を _run_ffmpeg_async に変更
            [ffmpeg_path, "-hide_banner", "-filters"]
        )
        out = result.stdout
        return ("overlay_cuda" in out) and (
            "scale_cuda" in out or "hwupload_cuda" in out
        )
    except Exception:
        return False


async def get_hardware_encoder_kind(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """
    利用可能なH.264/HEVCハードウェア「エンコーダ」を判定して返す。
    優先順位: nvenc -> qsv -> vaapi -> videotoolbox -> amf
    戻り値: 'nvenc' | 'qsv' | 'vaapi' | 'videotoolbox' | 'amf' | None
    """
    # まずNVENC (スモークテストで確認)
    if await is_nvenc_available(ffmpeg_path):
        return "nvenc"

    encs = await _list_encoders(ffmpeg_path)

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
async def get_encoder_options(
    hw_encoder: str, quality: str, ffmpeg_path: str = "ffmpeg"
) -> Tuple[str, List[str]]:
    """
    --hw-encoder と --quality の設定に基づき、エンコーダ名とffmpegオプションを返す。

    :return: (エンコーダ名, ffmpegオプションのリスト)
    """
    use_nvenc = False
    nvenc_available = await is_nvenc_available(ffmpeg_path)

    if hw_encoder == "auto":
        use_nvenc = nvenc_available
    elif hw_encoder == "gpu":
        use_nvenc = nvenc_available
        if not nvenc_available:
            logger.warning("NVENC is not available, falling back to CPU.")
    # hw_encoder == "cpu" の場合は use_nvenc は False のまま

    if use_nvenc:
        encoder = "h264_nvenc"
        if quality == "speed":
            preset = "p7"
            opts = ["-preset", preset, "-cq", "30"]
        elif quality == "balanced":
            preset = "p5"
            opts = ["-preset", preset, "-cq", "23"]
        else:  # quality
            preset = "p4"
            opts = ["-preset", preset, "-cq", "20"]
        logger.info(
            f"Using Encoder: '{encoder}', Preset: '{preset}', Quality setting: '{quality}'"
        )
    else:
        encoder = "libx264"
        if quality == "speed":
            preset = "ultrafast"
            opts = ["-preset", preset, "-crf", "30"]
        elif quality == "balanced":
            preset = "medium"
            opts = ["-preset", preset, "-crf", "23"]
        else:  # quality
            preset = "slow"
            opts = ["-preset", preset, "-crf", "20"]
        logger.info(
            f"Using Encoder: '{encoder}', Preset: '{preset}', Quality setting: '{quality}'"
        )

    return encoder, opts


async def get_hw_encoder_kind_for_video_params(
    ffmpeg_path: str = "ffmpeg",
) -> Optional[str]:
    """
    VideoParams.to_ffmpeg_opts で使用するためのハードウェアエンコーダの種類を判定して返す。
    環境変数による強制設定も考慮する。
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

    if hw_force_off:
        hw_kind = None
    elif hw_kind_env:
        hw_kind = hw_kind_env
    else:
        hw_kind = await get_hardware_encoder_kind(ffmpeg_path)
    if hw_kind:
        logger.info(f"Using {hw_kind.upper()} for video encoding.")
    elif hw_force_off:
        logger.info(
            "Hardware encoding disabled by DISABLE_HWENC=1. Falling back to CPU."
        )
    else:
        # フォールバックの具体的な理由をログに記録
        if not await is_nvenc_available(ffmpeg_path):
            logger.info("NVENC is not available. Checking other hardware encoders...")
            # 他のハードウェアエンコーダーのチェック結果を詳細にログに記録
            encoders = await _list_encoders(ffmpeg_path)
            if not (" h264_qsv " in f" {encoders} " or " hevc_qsv " in f" {encoders} "):
                logger.info("QSV encoder not found.")
            if not (
                " h264_vaapi " in f" {encoders} " or " hevc_vaapi " in f" {encoders} "
            ):
                logger.info("VAAPI encoder not found.")
            if not (
                " h264_videotoolbox " in f" {encoders} "
                or " hevc_videotoolbox " in f" {encoders} "
            ):
                logger.info("VideoToolbox encoder not found.")
            if not (" h264_amf " in f" {encoders} " or " hevc_amf " in f" {encoders} "):
                logger.info("AMF encoder not found.")
        logger.info("No hardware encoder found. Falling back to CPU (libx264/libx265).")
    return hw_kind


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


async def get_media_info(file_path: str) -> MediaInfo:
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
        result = await _run_ffmpeg_async(cmd)
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


async def get_audio_duration(file_path: str) -> float:
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
        result = await _run_ffmpeg_async(cmd)
        probe = json.loads(result.stdout)
        duration = float(probe["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e}\n{e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


async def get_media_duration(file_path: str) -> float:
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
        result = await _run_ffmpeg_async(cmd)
        probe = json.loads(result.stdout)
        duration = float(probe["format"]["duration"])
        return round(duration, 2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running ffprobe for {file_path}: {e}\n{e.stderr}")
        raise
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing ffprobe output for {file_path}: {e}")
        raise


async def compare_media_params(file_paths: List[str]) -> bool:
    """
    複数の動画ファイルの主要なパラメータ（コーデック、解像度、フレームレート、ピクセルフォーマット、
    サンプルレート、チャンネル数、チャンネルレイアウト）が全て一致するかどうかを判定する。
    """
    if not file_paths:
        return True  # ファイルがない場合は一致とみなす

    base_info_val: Optional[MediaInfo] = None
    for i, path in enumerate(file_paths):
        try:
            info = await get_media_info(path)
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
    ]
    if movflags_faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.extend([
        output_path,
    ])

    try:
        proc = await _run_ffmpeg_async(cmd)  # await を追加
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


async def has_audio_stream(file_path: str) -> bool:
    """動画に音声ストリームがあるか。"""
    media_info = await get_media_info(file_path)
    return media_info.get("audio") is not None


# =========================================================
# 変換・生成
# =========================================================


def generate_normalization_hash_data(
    input_path: Path, video_params: VideoParams, audio_params: AudioParams
) -> Dict[str, Any]:
    """
    動画正規化のためのハッシュ生成に必要なデータを辞書形式で返す。
    """
    return {
        "input_path": input_path,
        "video_params": video_params.__dict__,  # dataclass を辞書に変換
        "audio_params": audio_params.__dict__,  # dataclass を辞書に変換
    }


async def create_silent_audio(
    output_path: str,
    duration: float,
    audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg",
):
    """
    指定秒数の無音WAVを作成（PCM s16le）。
    FFmpeg 7 では anullsrc の cl は 'mono' / 'stereo' 指定が安全。
    """
    cl = "mono" if audio_params.channels == 1 else "stereo"
    cmd = [
        ffmpeg_path,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={audio_params.sample_rate}:cl={cl}",
        "-t",
        str(duration),
    ]
    cmd.extend(audio_params.to_ffmpeg_opts())
    cmd.extend([output_path])
    try:
        await _run_ffmpeg_async(cmd)
        logger.debug(f"Created silent audio: {output_path} ({duration}s)")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error creating silent audio file {output_path}: {e}")
        logger.error(f"STDOUT: {e.stdout}")
        logger.error(f"STDERR: {e.stderr}")
        raise


async def add_bgm_to_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    audio_params: AudioParams,
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
        video_duration = await get_media_duration(video_path)

    bgm_duration = await get_audio_duration(bgm_path)
    _ = min(video_duration, bgm_start_time + bgm_duration)  # 有効長（使い道があれば）

    cmd = [ffmpeg_path, "-y"]
    cmd.extend(_threading_flags(ffmpeg_path))
    cmd.extend(["-i", video_path, "-i", bgm_path, "-filter_complex"])

    video_has_audio = await has_audio_stream(video_path)

    # BGM用フィルタ
    af = [f"volume={bgm_volume}"]
    if fade_in_duration > 0:
        af.append(f"afade=t=in:st=0:d={fade_in_duration}")
    if fade_out_duration > 0:
        st = max(0.0, bgm_duration - fade_out_duration)
        af.append(f"afade=t=out:st={st}:d={fade_out_duration}")
    bgm_chain = f"[1:a]{','.join(af)}[bgm_filtered]"
    delayed = f"[bgm_filtered]adelay={int(bgm_start_time * 1000)}:all=1[delayed_bgm]"

    audio_opts = audio_params.to_ffmpeg_opts()

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
            ]
        )
        cmd.extend(audio_opts)
        cmd.extend(["-shortest", output_path])
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
            ]
        )
        cmd.extend(audio_opts)
        cmd.extend(["-shortest", output_path])

    try:
        proc = await _run_ffmpeg_async(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully added BGM to {video_path} -> {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding BGM to video: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


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
):
    """
    映像: xfade、音声: acrossfade でクロスフェード。
    - デコード＆フィルタ: CPU
    - エンコード: HW（存在すれば）/ CPU
    """
    has_a1 = await has_audio_stream(input_video1_path)
    has_a2 = await has_audio_stream(input_video2_path)

    hw_kind = await get_hw_encoder_kind_for_video_params(ffmpeg_path)
    video_opts = video_params.to_ffmpeg_opts(hw_kind)
    audio_opts = audio_params.to_ffmpeg_opts()

    cmd = [ffmpeg_path, "-y"]
    cmd.extend(_threading_flags(ffmpeg_path))
    cmd.extend(["-i", input_video1_path, "-i", input_video2_path])

    vf = f"[0:v][1:v]xfade=transition={transition_type}:duration={duration}:offset={offset}[v]"
    parts = [vf]

    if has_a1 and has_a2:
        af = (
            f"[0:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts=stereo[a0];"
            f"[1:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts=stereo[a1];"
            f"[a0][a1]acrossfade=d={duration}:c1=tri:c2=tri[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    elif has_a1:
        af = (
            f"[0:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts=stereo,"
            f"afade=t=out:st={offset}:d={duration}[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    elif has_a2:
        delay_ms = int(offset * 1000)
        af = (
            f"[1:a]aresample=async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:sample_rates={audio_params.sample_rate}:channel_layouts=stereo,"
            f"adelay={delay_ms}:all=1,afade=t=in:st=0:d={duration}[a]"
        )
        parts.append(af)
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", vf, "-map", "[v]"]

    # 映像エンコード設定
    cmd.extend(video_opts)
    cmd.extend(audio_opts)
    cmd.extend([output_path])

    try:
        proc = await _run_ffmpeg_async(cmd)
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


async def mix_audio_tracks(
    audio_tracks: List[Tuple[str, float, float]],
    output_path: str,
    total_duration: float,
    audio_params: AudioParams,  # audio_params を追加
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
                "-c:a",
                "libmp3lame",  # MP3コーデックを使用
                "-b:a",
                f"{audio_params.bitrate_kbps}k",  # AudioParams のビットレートを使用
                "-ar",
                str(audio_params.sample_rate),
                "-ac",
                str(audio_params.channels),
                "-t",
                str(total_duration),
                output_path,
            ]
        )

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        proc = await _run_ffmpeg_async(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully mixed audio tracks to {output_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Error mixing audio tracks: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


async def normalize_media(
    input_path: Path,
    video_params: VideoParams,
    audio_params: AudioParams,
    cache_manager: Any,  # CacheManager の循環インポートを避けるため Any を使用
    ffmpeg_path: str = "ffmpeg",
) -> Path:
    """
    背景・挿入動画を指定されたパラメータに正規化し、キャッシュする。
    キャッシュがHITすれば、変換処理をスキップしてキャッシュパスを返す。
    """
    # 既に当プロジェクトの正規化キャッシュ（temp_normalized_*.mp4）が入力の場合、自己再正規化を避ける
    try:
        if (
            input_path.is_file()
            and hasattr(cache_manager, "cache_dir")
            and input_path.parent.resolve() == cache_manager.cache_dir.resolve()
            and input_path.name.startswith("temp_normalized_")
            and input_path.suffix.lower() == ".mp4"
        ):
            # VideoParams/AudioParams から target_spec へ変換し、メタの target_spec と比較
            target_spec = {
                "video": {
                    "width": int(video_params.width),
                    "height": int(video_params.height),
                    "fps": int(video_params.fps),
                    "pix_fmt": video_params.pix_fmt,
                    "codec": "h264",  # normalize 側は h264 を基本に正規化
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
        logger.debug(
            f"Skip pre-check for already-normalized input due to error: {e}"
        )
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
                can_copy_video = True
                logger.debug(f"Video can be copied for {input_path}")
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
                cmd_local.extend(["-vf", f"fps={video_params.fps},setpts=PTS-STARTPTS"])
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
                video_filter = f"fps={video_params.fps},setpts=PTS-STARTPTS"
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
            return output_path
        except subprocess.CalledProcessError as e:
            # Detect NVENC-specific failure and fallback to CPU once
            msg = (e.stderr or "") + "\n" + (e.stdout or "")
            should_fallback = (
                "exit status 234" in msg
                or "exit code 234" in msg
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
