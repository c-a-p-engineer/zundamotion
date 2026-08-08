"""Hardware encoder smoke probes and encoder selection policy."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from .ffmpeg_capability_listing import _list_encoders
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger

_NVENC_CACHE: Dict[str, bool] = {}
_QSV_CACHE: Dict[str, bool] = {}
_NVENC_TASKS: Dict[str, asyncio.Task] = {}
_NVENC_LOCK = asyncio.Lock()
_NVENC_DIAG_DUMPED = False


def _emit_nvenc_failure_hint(stderr: str) -> None:
    global _NVENC_DIAG_DUMPED
    if _NVENC_DIAG_DUMPED:
        return
    _NVENC_DIAG_DUMPED = True
    message = stderr or ""
    hints: List[str] = []
    if "Cannot load libnvidia-encode.so.1" in message:
        hints.append(
            "libnvidia-encode.so.1 が見つかりません。Docker なら `--gpus all` と "
            "`NVIDIA_DRIVER_CAPABILITIES=compute,utility,video`（または all）を指定し、"
            "NVIDIA Container Toolkit を有効化してください。"
        )
    match = re.search(r"minimum required Nvidia driver.*?([0-9.]+)", message, re.IGNORECASE)
    if match:
        hints.append(f"NVIDIA ドライバの最小要件は {match.group(1)} 以上です。ホスト側のドライバを更新してください。")
    if "No NVENC capable devices found" in message:
        hints.append("NVENC 対応 GPU が見つかりません。GPU が NVENC 対応か、コンテナに GPU が露出しているか確認してください。")
    if "Driver/library version mismatch" in message or "driver version is insufficient" in message.lower():
        hints.append("ドライバとライブラリのバージョン不一致が疑われます。ホスト側ドライバの更新と再起動を試してください。")
    if hints:
        logger.warning("[NVENC Hint] %s", " ".join(hints))
        logger.warning("[NVENC Hint] 確認コマンド: `nvidia-smi`, `ffmpeg -hide_banner -encoders | rg nvenc`")


async def _compute_nvenc(ffmpeg_path: str) -> bool:
    encoders = await _list_encoders(ffmpeg_path)
    if "h264_nvenc" not in encoders:
        logger.info("h264_nvenc not found in `ffmpeg -encoders` list.")
        return False
    cmd = [
        ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1",
        "-vcodec", "h264_nvenc", "-preset", "p1", "-f", "null", "-",
    ]
    try:
        await _run_ffmpeg_async(cmd, error_log_level=logging.WARNING)
        logger.info("h264_nvenc smoke test successful. NVENC is available.")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("h264_nvenc smoke test failed. NVENC is not available or not configured correctly. Falling back to CPU.")
        logger.debug("FFmpeg stderr for smoke test:\n%s", exc.stderr)
        _emit_nvenc_failure_hint(exc.stderr or "")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg command not found at '%s'.", ffmpeg_path)
        return False
    except Exception as exc:
        logger.error("An unexpected error occurred during NVENC smoke test: %s", exc)
        return False


async def is_nvenc_available(ffmpeg_path: str = "ffmpeg") -> bool:
    if ffmpeg_path in _NVENC_CACHE:
        return _NVENC_CACHE[ffmpeg_path]
    async with _NVENC_LOCK:
        if ffmpeg_path in _NVENC_CACHE:
            return _NVENC_CACHE[ffmpeg_path]
        task = _NVENC_TASKS.get(ffmpeg_path)
        if task is None:
            task = asyncio.create_task(_compute_nvenc(ffmpeg_path))
            _NVENC_TASKS[ffmpeg_path] = task
    try:
        result = await task
        _NVENC_CACHE[ffmpeg_path] = result
        return result
    finally:
        async with _NVENC_LOCK:
            _NVENC_TASKS.pop(ffmpeg_path, None)


async def is_qsv_available(ffmpeg_path: str = "ffmpeg") -> bool:
    if ffmpeg_path in _QSV_CACHE:
        return _QSV_CACHE[ffmpeg_path]
    encoders = await _list_encoders(ffmpeg_path)
    if " h264_qsv " not in f" {encoders} ":
        _QSV_CACHE[ffmpeg_path] = False
        return False
    cmd = [
        ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1",
        "-vcodec", "h264_qsv", "-f", "null", "-",
    ]
    try:
        await _run_ffmpeg_async(cmd, error_log_level=logging.WARNING)
        logger.info("h264_qsv smoke test successful. QSV is available.")
        result = True
    except subprocess.CalledProcessError as exc:
        logger.warning("h264_qsv smoke test failed. QSV is not available or not configured correctly. Falling back to CPU.")
        logger.debug("FFmpeg stderr for QSV smoke test:\n%s", exc.stderr)
        result = False
    except Exception as exc:
        logger.warning("h264_qsv smoke test failed unexpectedly: %s", exc)
        result = False
    _QSV_CACHE[ffmpeg_path] = result
    return result


async def get_hardware_encoder_kind(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    if await is_nvenc_available(ffmpeg_path):
        return "nvenc"
    encoders = await _list_encoders(ffmpeg_path)
    if (" h264_qsv " in f" {encoders} " or " hevc_qsv " in f" {encoders} ") and await is_qsv_available(ffmpeg_path):
        return "qsv"
    if (" h264_vaapi " in f" {encoders} " or " hevc_vaapi " in f" {encoders} ") and os.path.exists("/dev/dri"):
        return "vaapi"
    if " h264_videotoolbox " in f" {encoders} " or " hevc_videotoolbox " in f" {encoders} ":
        return "videotoolbox"
    if os.name == "nt" and (" h264_amf " in f" {encoders} " or " hevc_amf " in f" {encoders} "):
        return "amf"
    return None


def _software_options(quality: str) -> tuple[str, List[str]]:
    if quality == "speed":
        return "ultrafast", ["-preset", "ultrafast", "-crf", "30"]
    if quality == "balanced":
        return "medium", ["-preset", "medium", "-crf", "23"]
    return "slow", ["-preset", "slow", "-crf", "20"]


def _nvenc_options(quality: str) -> tuple[str, List[str]]:
    if quality == "speed":
        return "p1", ["-preset", "p1", "-cq", "30"]
    if quality == "balanced":
        return "p4", ["-preset", "p4", "-cq", "23"]
    return "p6", ["-preset", "p6", "-cq", "20"]


async def get_encoder_options(
    hw_encoder: str, quality: str, ffmpeg_path: str = "ffmpeg"
) -> Tuple[str, List[str]]:
    available = False if hw_encoder == "cpu" else await is_nvenc_available(ffmpeg_path)
    use_nvenc = available if hw_encoder in {"auto", "gpu"} else False
    if hw_encoder == "gpu" and not available:
        logger.warning("NVENC is not available, falling back to CPU.")
    if use_nvenc:
        preset, opts = _nvenc_options(quality)
        encoder = "h264_nvenc"
    else:
        preset, opts = _software_options(quality)
        encoder = "libx264"
    logger.info("Using Encoder: '%s', Preset: '%s', Quality setting: '%s'", encoder, preset, quality)
    return encoder, opts


async def _log_missing_encoders(ffmpeg_path: str) -> None:
    encoders = await _list_encoders(ffmpeg_path)
    checks = [
        ("QSV", (" h264_qsv ", " hevc_qsv ")),
        ("VAAPI", (" h264_vaapi ", " hevc_vaapi ")),
        ("VideoToolbox", (" h264_videotoolbox ", " hevc_videotoolbox ")),
        ("AMF", (" h264_amf ", " hevc_amf ")),
    ]
    padded = f" {encoders} "
    for label, names in checks:
        if not any(name in padded for name in names):
            logger.info("%s encoder not found.", label)


async def get_hw_encoder_kind_for_video_params(
    ffmpeg_path: str = "ffmpeg", hw_encoder: str = "auto",
) -> Optional[str]:
    force_off = os.getenv("DISABLE_HWENC", "0") == "1" or hw_encoder == "cpu"
    forced = (
        "nvenc" if os.getenv("FORCE_NVENC") == "1" else
        "qsv" if os.getenv("FORCE_QSV") == "1" else
        "vaapi" if os.getenv("FORCE_VAAPI") == "1" else None
    )
    if force_off:
        kind = None
    elif hw_encoder == "gpu":
        kind = forced or ("nvenc" if await is_nvenc_available(ffmpeg_path) else None)
        if kind is None:
            logger.warning("GPU encoding was requested, but NVENC is not available. Falling back to CPU.")
    elif forced:
        kind = forced
    else:
        kind = await get_hardware_encoder_kind(ffmpeg_path)
    if kind:
        logger.info("Using %s for video encoding.", kind.upper())
    elif force_off:
        logger.info("Hardware encoding disabled by DISABLE_HWENC=1. Falling back to CPU.")
    else:
        if not await is_nvenc_available(ffmpeg_path):
            logger.info("NVENC is not available. Checking other hardware encoders...")
            await _log_missing_encoders(ffmpeg_path)
        logger.info("No hardware encoder found. Falling back to CPU (libx264/libx265).")
    return kind
