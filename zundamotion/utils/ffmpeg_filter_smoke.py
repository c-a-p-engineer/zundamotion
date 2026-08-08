"""GPU filter smoke tests and capability diagnostics."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any, Dict, List, Optional

from .ffmpeg_capability_listing import (
    _list_ffmpeg_filters,
    get_preferred_cuda_scale_filter,
)
from .ffmpeg_filter_strings import build_scale_opencl_filter
from .ffmpeg_hw import set_hw_filter_mode
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger

_cuda_smoke_result: Optional[bool] = None
_cuda_smoke_lock = asyncio.Lock()
_cuda_scale_only_smoke_result: Optional[bool] = None
_cuda_scale_only_smoke_lock = asyncio.Lock()
_opencl_smoke_result: Optional[bool] = None
_opencl_smoke_lock = asyncio.Lock()
_opencl_scale_only_smoke_result: Optional[bool] = None
_opencl_scale_only_smoke_lock = asyncio.Lock()
_cuda_diag_dumped = False


def _cuda_scale_candidates(filters: str, primary: str) -> List[str]:
    names = [primary]
    for candidate in ("scale_cuda", "scale_npp"):
        if candidate in filters and candidate not in names:
            names.append(candidate)
    result: List[str] = []
    for name in names:
        for pixel_format in ("rgba", "nv12"):
            result.append(
                f"[0:v]format={pixel_format},hwupload_cuda,{name}=64:64,"
                "hwdownload,format=rgba[out]"
            )
    return result


def _cuda_overlay_candidates(filters: str) -> List[str]:
    primary = "scale_cuda" if "scale_cuda" in filters else "scale_npp"
    names = [primary]
    if "scale_npp" in filters and "scale_cuda" in filters:
        names.append("scale_npp" if primary == "scale_cuda" else "scale_cuda")
    result: List[str] = []
    for name in names:
        for overlay_format in ("nv12", "rgba"):
            result.append(
                "[0:v]format=nv12,hwupload_cuda[bg];"
                f"[1:v]format={overlay_format},hwupload_cuda,{name}=32:32[ov];"
                "[bg][ov]overlay_cuda=x=16:y=16[out]"
            )
    return result


async def _run_filter_candidates(
    ffmpeg_path: str, candidates: List[str], *, overlay: bool
) -> bool:
    for graph in candidates:
        cmd = [ffmpeg_path, "-hide_banner", "-y", "-f", "lavfi", "-i"]
        if overlay:
            cmd.extend([
                "color=c=black:s=64x64:d=0.1", "-f", "lavfi", "-i",
                "color=c=white:s=32x32:d=0.1",
            ])
        else:
            cmd.append("color=c=black:s=48x48:d=0.1")
        cmd.extend(["-filter_complex", graph, "-map", "[out]", "-f", "null", "-"])
        try:
            await _run_ffmpeg_async(cmd, error_log_level=logging.WARNING)
            return True
        except Exception as exc:
            logger.debug("GPU filter smoke candidate failed: %s\nFC=%s", exc, graph)
    return False


async def smoke_test_cuda_scale_only(ffmpeg_path: str = "ffmpeg") -> bool:
    global _cuda_scale_only_smoke_result
    if _cuda_scale_only_smoke_result is not None:
        return _cuda_scale_only_smoke_result
    async with _cuda_scale_only_smoke_lock:
        if _cuda_scale_only_smoke_result is not None:
            return _cuda_scale_only_smoke_result
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        if not (
            "hwupload_cuda" in filters
            and ("scale_cuda" in filters or "scale_npp" in filters)
        ):
            _cuda_scale_only_smoke_result = False
            return False
        primary = await get_preferred_cuda_scale_filter(ffmpeg_path)
        _cuda_scale_only_smoke_result = await _run_filter_candidates(
            ffmpeg_path, _cuda_scale_candidates(filters, primary), overlay=False
        )
        return _cuda_scale_only_smoke_result


async def _dump_process_output(command: List[str], label: str) -> None:
    try:
        proc = await _run_ffmpeg_async(command, error_log_level=logging.DEBUG)
        if proc.stdout:
            logger.info("[%s]\n%s", label, proc.stdout.strip())
    except Exception as exc:
        logger.info("[%s] failed: %s", label, exc)


async def _dump_external_output(command: List[str], label: str) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode == 0:
            logger.info("[%s]\n%s", label, (out or b"").decode(errors="ignore").strip())
        else:
            logger.info(
                "[%s] exit=%s stderr=%s", label, proc.returncode,
                (err or b"").decode(errors="ignore").strip(),
            )
    except FileNotFoundError:
        logger.info("[%s] command not found", label)
    except Exception as exc:
        logger.info("[%s] failed: %s", label, exc)


async def _dump_cuda_diag_once(ffmpeg_path: str = "ffmpeg") -> None:
    global _cuda_diag_dumped
    if _cuda_diag_dumped:
        return
    _cuda_diag_dumped = True
    logger.info("[CUDA Diag] Collecting environment diagnostics after smoke failure...")
    await _dump_process_output([ffmpeg_path, "-hide_banner", "-buildconf"], "ffmpeg -buildconf")
    await _dump_process_output([ffmpeg_path, "-hide_banner", "-filters"], "ffmpeg -filters")
    await _dump_external_output(["nvidia-smi", "-L"], "nvidia-smi -L")
    await _dump_external_output(["nvcc", "--version"], "nvcc --version")


async def smoke_test_cuda_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    global _cuda_smoke_result
    if _cuda_smoke_result is not None:
        return _cuda_smoke_result
    async with _cuda_smoke_lock:
        if _cuda_smoke_result is not None:
            return _cuda_smoke_result
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        if not (
            "overlay_cuda" in filters
            and "hwupload_cuda" in filters
            and ("scale_cuda" in filters or "scale_npp" in filters)
        ):
            _cuda_smoke_result = False
            return False
        _cuda_smoke_result = await _run_filter_candidates(
            ffmpeg_path, _cuda_overlay_candidates(filters), overlay=True
        )
        if _cuda_smoke_result:
            return True
        logger.warning(
            "CUDA filter smoke test failed for all candidates; switching global HW filter mode to CPU."
        )
        await _dump_cuda_diag_once(ffmpeg_path)
        try:
            set_hw_filter_mode("cpu")
        except Exception:
            pass
        return False


def _opencl_overlay_graph() -> str:
    scale = build_scale_opencl_filter(32, 32)
    return (
        "[0:v]format=rgba,hwupload[bg];"
        f"[1:v]format=rgba,hwupload,{scale}[ov];"
        "[bg][ov]overlay_opencl=x=16:y=16,hwdownload,format=rgba[out]"
    )


async def smoke_test_opencl_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    global _opencl_smoke_result
    if _opencl_smoke_result is not None:
        return _opencl_smoke_result
    async with _opencl_smoke_lock:
        if _opencl_smoke_result is not None:
            return _opencl_smoke_result
        graph = _opencl_overlay_graph()
        cmd = [
            ffmpeg_path, "-hide_banner", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=64x64:d=0.1", "-f", "lavfi", "-i",
            "color=c=white:s=32x32:d=0.1", "-filter_complex", graph,
            "-map", "[out]", "-f", "null", "-",
        ]
        try:
            await _run_ffmpeg_async(cmd, error_log_level=logging.WARNING)
            _opencl_smoke_result = True
        except Exception as exc:
            logger.debug("OpenCL smoke test failed: %s", exc)
            _opencl_smoke_result = False
        return _opencl_smoke_result


async def smoke_test_opencl_scale_only(ffmpeg_path: str = "ffmpeg") -> bool:
    global _opencl_scale_only_smoke_result
    if _opencl_scale_only_smoke_result is not None:
        return _opencl_scale_only_smoke_result
    async with _opencl_scale_only_smoke_lock:
        if _opencl_scale_only_smoke_result is not None:
            return _opencl_scale_only_smoke_result
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        if not filters or "scale_opencl" not in filters or "hwupload" not in filters:
            _opencl_scale_only_smoke_result = False
            return False
        scale = build_scale_opencl_filter(64, 64)
        candidates = [
            f"[0:v]format=rgba,hwupload,{scale},hwdownload,format=rgba[out]",
            f"[0:v]format=nv12,hwupload,{scale},hwdownload,format=rgba[out]",
        ]
        _opencl_scale_only_smoke_result = await _run_filter_candidates(
            ffmpeg_path, candidates, overlay=False
        )
        return _opencl_scale_only_smoke_result


async def get_filter_diagnostics(
    ffmpeg_path: str = "ffmpeg", *, run_smokes: bool = True,
    include_opencl_smokes: bool = True,
) -> Dict[str, Any]:
    filters = await _list_ffmpeg_filters(ffmpeg_path)
    present = {
        "overlay_cuda": "overlay_cuda" in filters,
        "scale_cuda": "scale_cuda" in filters,
        "scale_npp": "scale_npp" in filters,
        "hwupload_cuda": "hwupload_cuda" in filters,
        "overlay_opencl": "overlay_opencl" in filters,
        "scale_opencl": "scale_opencl" in filters,
        "hwupload": "hwupload" in filters,
    }
    smokes: Dict[str, Optional[bool]] = {
        "cuda_filters": None, "cuda_scale_only": None,
        "opencl_filters": None, "opencl_scale_only": None,
    }
    if run_smokes:
        smokes["cuda_filters"] = await smoke_test_cuda_filters(ffmpeg_path)
        smokes["cuda_scale_only"] = await smoke_test_cuda_scale_only(ffmpeg_path)
        if include_opencl_smokes:
            smokes["opencl_filters"] = await smoke_test_opencl_filters(ffmpeg_path)
            smokes["opencl_scale_only"] = await smoke_test_opencl_scale_only(ffmpeg_path)
    return {"present": present, "smokes": smokes}
