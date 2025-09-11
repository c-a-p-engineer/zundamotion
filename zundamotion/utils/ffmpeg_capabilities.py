# -*- coding: utf-8 -*-
"""FFmpeg の機能検出やハードウェア判定を行うヘルパー群。"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .ffmpeg_hw import get_hw_filter_mode, set_hw_filter_mode
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger

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


async def get_ffmpeg_version(ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """FFmpeg のバージョン文字列（例: '7.0.2'）を返す。失敗時 None。"""
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-version"])
        m = re.search(r"ffmpeg version (\S+)", result.stdout)
        return m.group(1) if m else None
    except Exception as e:
        logger.error(f"Error getting FFmpeg version: {e}")
        return None




async def _list_encoders(ffmpeg_path: str = "ffmpeg") -> str:
    """`ffmpeg -encoders` の標準出力（小文字化）を返す。失敗時は空文字。"""
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-encoders"])
        return result.stdout.lower()
    except Exception as e:
        logger.error(f"Error listing FFmpeg encoders: {e}")
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


# 軽量な CUDA フィルタのスモークテスト（overlay_cuda/scale_cuda 実行確認）
_cuda_smoke_result: Optional[bool] = None
_cuda_smoke_lock = asyncio.Lock()
_cuda_diag_dumped: bool = False  # スモーク失敗時の診断ダンプは1回のみ


_filters_cache: Dict[str, str] = {}


async def _list_ffmpeg_filters(ffmpeg_path: str = "ffmpeg") -> str:
    """Return the raw output of `ffmpeg -hide_banner -filters` (cached)."""
    cached = _filters_cache.get(ffmpeg_path)
    if cached is not None:
        return cached
    try:
        result = await _run_ffmpeg_async([ffmpeg_path, "-hide_banner", "-filters"])
        out = result.stdout or ""
        _filters_cache[ffmpeg_path] = out
        return out
    except Exception:
        return ""


_preferred_scale_filter_cache: Dict[str, str] = {}


async def get_preferred_cuda_scale_filter(ffmpeg_path: str = "ffmpeg") -> str:
    """
    Choose GPU scale filter: prefer `scale_cuda` if available; otherwise use
    `scale_npp` when present. Falls back to `scale_cuda` by name if nothing is
    detectable (the call site will still fail gracefully if missing).
    Result is cached per ffmpeg path.
    """
    cached = _preferred_scale_filter_cache.get(ffmpeg_path)
    if cached:
        return cached
    filters = await _list_ffmpeg_filters(ffmpeg_path)
    chosen = "scale_cuda" if "scale_cuda" in filters else (
        "scale_npp" if "scale_npp" in filters else "scale_cuda"
    )
    _preferred_scale_filter_cache[ffmpeg_path] = chosen
    return chosen


async def has_gpu_scale_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    Return True if GPU-side scaling filters are available, even when
    overlay_cuda is not. Used to enable the hybrid path: GPU scale + CPU overlay.

    Conditions:
      - hwupload_cuda exists, and
      - either scale_cuda or scale_npp exists.
    """
    try:
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        has_upload = "hwupload_cuda" in filters
        has_scale = ("scale_cuda" in filters) or ("scale_npp" in filters)
        return has_upload and has_scale
    except Exception:
        return False


# ---------------------------------------------------------
# CUDA scale-only smoke test (for CPU-mode limited enable)
# ---------------------------------------------------------
_cuda_scale_only_smoke_result: Optional[bool] = None
_cuda_scale_only_smoke_lock = asyncio.Lock()


async def smoke_test_cuda_scale_only(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    Run a conservative smoke test that ONLY exercises the GPU scaling path
    (hwupload_cuda -> scale_* -> hwdownload) without overlay_cuda. This is
    used to selectively allow "GPU scale + CPU overlay" hybrid even when the
    global HW filter mode is backed off to CPU due to overlay failures.

    The result is cached per-process.
    """
    global _cuda_scale_only_smoke_result
    if _cuda_scale_only_smoke_result is not None:
        return _cuda_scale_only_smoke_result

    async with _cuda_scale_only_smoke_lock:
        if _cuda_scale_only_smoke_result is not None:
            return _cuda_scale_only_smoke_result

        try:
            filters = await _list_ffmpeg_filters(ffmpeg_path)
            if not filters:
                _cuda_scale_only_smoke_result = False
                return _cuda_scale_only_smoke_result
            has_upload = "hwupload_cuda" in filters
            has_scale_cuda = "scale_cuda" in filters
            has_scale_npp = "scale_npp" in filters
            if not (has_upload and (has_scale_cuda or has_scale_npp)):
                _cuda_scale_only_smoke_result = False
                return _cuda_scale_only_smoke_result

            scale_primary = await get_preferred_cuda_scale_filter(ffmpeg_path)
            scale_alternatives = []
            if has_scale_cuda and scale_primary != "scale_cuda":
                scale_alternatives.append("scale_cuda")
            if has_scale_npp and scale_primary != "scale_npp":
                scale_alternatives.append("scale_npp")

            # Build candidate filtergraphs to reduce false negatives across envs
            candidates = []
            # RGBA upload -> GPU scale -> download
            candidates.append(
                f"[0:v]format=rgba,hwupload_cuda,{scale_primary}=64:64,hwdownload,format=rgba[out]"
            )
            # NV12 upload path
            candidates.append(
                f"[0:v]format=nv12,hwupload_cuda,{scale_primary}=64:64,hwdownload,format=rgba[out]"
            )
            # Try explicit alternatives if present
            for alt in scale_alternatives:
                candidates.append(
                    f"[0:v]format=rgba,hwupload_cuda,{alt}=64:64,hwdownload,format=rgba[out]"
                )
                candidates.append(
                    f"[0:v]format=nv12,hwupload_cuda,{alt}=64:64,hwdownload,format=rgba[out]"
                )

            last_err: Optional[BaseException] = None
            for fc in candidates:
                cmd = [
                    ffmpeg_path,
                    "-hide_banner",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=48x48:d=0.1",
                    "-filter_complex",
                    fc,
                    "-map",
                    "[out]",
                    "-f",
                    "null",
                    "-",
                ]
                try:
                    await _run_ffmpeg_async(cmd)
                    _cuda_scale_only_smoke_result = True
                    return _cuda_scale_only_smoke_result
                except Exception as e:  # pragma: no cover - environment dependent
                    last_err = e
                    logger.debug("CUDA scale-only candidate failed: %s\nFC=%s", e, fc)

            logger.debug("All CUDA scale-only smoke candidates failed: %s", last_err)
            _cuda_scale_only_smoke_result = False
            return _cuda_scale_only_smoke_result
        except Exception as e:  # pragma: no cover - generic guard
            logger.debug("CUDA scale-only smoke failed: %s", e)
            _cuda_scale_only_smoke_result = False
            return _cuda_scale_only_smoke_result


async def _dump_cuda_diag_once(ffmpeg_path: str = "ffmpeg") -> None:
    """On first CUDA smoke failure, dump environment/build info at INFO level."""
    global _cuda_diag_dumped
    if _cuda_diag_dumped:
        return
    _cuda_diag_dumped = True
    logger.info("[CUDA Diag] Collecting environment diagnostics after smoke failure...")
    # ffmpeg -buildconf
    try:
        proc = await _run_ffmpeg_async([ffmpeg_path, "-hide_banner", "-buildconf"])
        if proc.stdout:
            logger.info("[ffmpeg -buildconf]\n%s", proc.stdout.strip())
    except Exception as e:
        logger.info("[ffmpeg -buildconf] failed: %s", e)
    # ffmpeg -filters
    try:
        proc = await _run_ffmpeg_async([ffmpeg_path, "-hide_banner", "-filters"])
        if proc.stdout:
            logger.info("[ffmpeg -filters]\n%s", proc.stdout.strip())
    except Exception as e:
        logger.info("[ffmpeg -filters] failed: %s", e)
    # nvidia-smi -L
    try:
        p = await asyncio.create_subprocess_exec(
            "nvidia-smi", "-L", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await p.communicate()
        if p.returncode == 0:
            logger.info("[nvidia-smi -L]\n%s", (out or b"").decode(errors="ignore").strip())
        else:
            logger.info(
                "[nvidia-smi -L] exit=%s stderr=%s",
                p.returncode,
                (err or b"").decode(errors="ignore").strip(),
            )
    except FileNotFoundError:
        logger.info("[nvidia-smi -L] command not found")
    except Exception as e:
        logger.info("[nvidia-smi -L] failed: %s", e)
    # nvcc --version (if present)
    try:
        p = await asyncio.create_subprocess_exec(
            "nvcc", "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await p.communicate()
        if p.returncode == 0:
            logger.info("[nvcc --version]\n%s", (out or b"").decode(errors="ignore").strip())
        else:
            logger.info(
                "[nvcc --version] exit=%s stderr=%s",
                p.returncode,
                (err or b"").decode(errors="ignore").strip(),
            )
    except FileNotFoundError:
        logger.info("[nvcc --version] command not found")
    except Exception as e:
        logger.info("[nvcc --version] failed: %s", e)


async def smoke_test_cuda_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    overlay_cuda/scale_cuda が実行できるかを短いフィルタグラフで検証。
    成功/失敗をプロセス内でキャッシュする。
    """
    global _cuda_smoke_result
    if _cuda_smoke_result is not None:
        return _cuda_smoke_result


# ------------------------------
# OpenCL overlay support (fallback)
# ------------------------------
_opencl_smoke_result: Optional[bool] = None
_opencl_smoke_lock = asyncio.Lock()


async def has_opencl_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    """Check presence of overlay_opencl and scale_opencl filters."""
    try:
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        return ("overlay_opencl" in filters) and ("scale_opencl" in filters or "hwupload" in filters)
    except Exception:
        return False


async def smoke_test_opencl_filters(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    Try a tiny OpenCL overlay graph using colors and hwupload with derive_device=opencl.
    Cache the result per-process to avoid repeated probing.
    """
    global _opencl_smoke_result
    if _opencl_smoke_result is not None:
        return _opencl_smoke_result
    async with _opencl_smoke_lock:
        if _opencl_smoke_result is not None:
            return _opencl_smoke_result
        # Build a conservative filtergraph: hwupload both inputs to OpenCL, scale overlay, overlay_opencl, then hwdownload.
        fc = (
            "[0:v]format=rgba,hwupload[bg];"
            "[1:v]format=rgba,hwupload,scale_opencl=32:32[ov];"
            "[bg][ov]overlay_opencl=x=16:y=16,hwdownload,format=rgba[out]"
        )
        cmd = [
            ffmpeg_path,
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=0.1",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=32x32:d=0.1",
            "-filter_complex",
            fc,
            "-map",
            "[out]",
            "-f",
            "null",
            "-",
        ]
        try:
            await _run_ffmpeg_async(cmd)
            _opencl_smoke_result = True
            return _opencl_smoke_result
        except subprocess.CalledProcessError as e:  # pragma: no cover - environment dependent
            logger.debug(
                "OpenCL smoke test failed (exit=%s). STDERR=%s",
                getattr(e, "returncode", None),
                (e.stderr or "").strip(),
            )
            _opencl_smoke_result = False
            return _opencl_smoke_result
        except Exception as e:  # pragma: no cover - generic guard
            logger.debug("OpenCL smoke test failed: %s", e)
            _opencl_smoke_result = False
            return _opencl_smoke_result

    # The following block was accidentally placed under OpenCL scope; keep CUDA smoke below
    async with _cuda_smoke_lock:
        if _cuda_smoke_result is not None:
            return _cuda_smoke_result
        # 64x64黒 + 32x32白を GPU に上げて overlay_cuda。
        # 複数の候補フィルタグラフを試し、どれかが通れば True。
        filters = await _list_ffmpeg_filters(ffmpeg_path)
        use_scale_npp = ("scale_npp" in filters) and ("scale_cuda" not in filters)
        scale_name_primary = "scale_cuda" if "scale_cuda" in filters else (
            "scale_npp" if "scale_npp" in filters else "scale_cuda"
        )
        # 候補グラフ（順に試す）
        candidates = []
        # 1) NV12+NV12 with primary scale
        candidates.append(
            f"[0:v]format=nv12,hwupload_cuda[bg];[1:v]format=nv12,hwupload_cuda,{scale_name_primary}=32:32[ov];[bg][ov]overlay_cuda=x=16:y=16[out]"
        )
        # 2) RGBA overlay variant with primary scale (common in pipeline)
        candidates.append(
            f"[0:v]format=nv12,hwupload_cuda[bg];[1:v]format=rgba,hwupload_cuda,{scale_name_primary}=32:32[ov];[bg][ov]overlay_cuda=x=16:y=16[out]"
        )
        # 3) If both scale filters exist, try the alternative explicitly
        if "scale_npp" in filters and "scale_cuda" in filters:
            candidates.append(
                "[0:v]format=nv12,hwupload_cuda[bg];[1:v]format=nv12,hwupload_cuda,scale_npp=32:32[ov];[bg][ov]overlay_cuda=x=16:y=16[out]"
            )
            candidates.append(
                "[0:v]format=nv12,hwupload_cuda[bg];[1:v]format=rgba,hwupload_cuda,scale_npp=32:32[ov];[bg][ov]overlay_cuda=x=16:y=16[out]"
            )

        last_err: Optional[BaseException] = None
        for fc in candidates:
            cmd = [
                ffmpeg_path,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:d=0.1",
                "-f",
                "lavfi",
                "-i",
                "color=c=white:s=32x32:d=0.1",
                "-filter_complex",
                fc,
                "-map",
                "[out]",
                "-f",
                "null",
                "-",
            ]
            try:
                await _run_ffmpeg_async(cmd)
                _cuda_smoke_result = True
                return _cuda_smoke_result
            except subprocess.CalledProcessError as e:
                last_err = e
                logger.debug(
                    "CUDA smoke candidate failed (exit=%s). FilterGraph=%s\nSTDERR=%s",
                    getattr(e, "returncode", None),
                    fc,
                    (e.stderr or "").strip(),
                )
            except Exception as e:  # pragma: no cover - generic guard
                last_err = e
                logger.debug("CUDA smoke candidate failed: %s", e)

        # All candidates failed
        logger.warning(
            "CUDA filter smoke test failed for all candidates; switching global HW filter mode to CPU."
        )
        await _dump_cuda_diag_once(ffmpeg_path)
        try:
            set_hw_filter_mode("cpu")
        except Exception:
            pass
        _cuda_smoke_result = False
        return _cuda_smoke_result


# ---------------------------------------------------------
# OpenCL scale-only smoke test (for CPU-mode limited enable)
# ---------------------------------------------------------
_opencl_scale_only_smoke_result: Optional[bool] = None
_opencl_scale_only_smoke_lock = asyncio.Lock()


async def smoke_test_opencl_scale_only(ffmpeg_path: str = "ffmpeg") -> bool:
    """
    Conservative smoke test for OpenCL scale-only path (no overlay_opencl):
    hwupload (derive_device=opencl) -> scale_opencl -> hwdownload.

    Used to allow "GPU scale + CPU overlay" hybrid even when overlay backends are
    unavailable. Result is cached per-process.
    """
    global _opencl_scale_only_smoke_result
    if _opencl_scale_only_smoke_result is not None:
        return _opencl_scale_only_smoke_result
    async with _opencl_scale_only_smoke_lock:
        if _opencl_scale_only_smoke_result is not None:
            return _opencl_scale_only_smoke_result
        try:
            filters = await _list_ffmpeg_filters(ffmpeg_path)
            if not filters or "scale_opencl" not in filters or "hwupload" not in filters:
                _opencl_scale_only_smoke_result = False
                return _opencl_scale_only_smoke_result
            # Try a minimal graph: upload -> scale_opencl -> download
            fcandidates = [
                # RGBA
                "[0:v]format=rgba,hwupload,scale_opencl=64:64,hwdownload,format=rgba[out]",
                # NV12
                "[0:v]format=nv12,hwupload,scale_opencl=64:64,hwdownload,format=rgba[out]",
            ]
            for fc in fcandidates:
                cmd = [
                    ffmpeg_path,
                    "-hide_banner",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=48x48:d=0.1",
                    "-filter_complex",
                    fc,
                    "-map",
                    "[out]",
                    "-f",
                    "null",
                    "-",
                ]
                try:
                    await _run_ffmpeg_async(cmd)
                    _opencl_scale_only_smoke_result = True
                    return _opencl_scale_only_smoke_result
                except Exception as e:
                    logger.debug("OpenCL scale-only candidate failed: %s\nFC=%s", e, fc)
            _opencl_scale_only_smoke_result = False
            return _opencl_scale_only_smoke_result
        except Exception as e:
            logger.debug("OpenCL scale-only smoke failed: %s", e)
            _opencl_scale_only_smoke_result = False
            return _opencl_scale_only_smoke_result


# ---------------------------------------------------------
# GPU Filter diagnostics (presence + smokes)
# ---------------------------------------------------------
async def get_filter_diagnostics(ffmpeg_path: str = "ffmpeg") -> Dict[str, Any]:
    """
    Return a dictionary summarizing GPU filter presence and smoke test results.
    Keys:
      present: overlay_cuda, scale_cuda, scale_npp, hwupload_cuda,
               overlay_opencl, scale_opencl, hwupload
      smoke:   cuda_filters, cuda_scale_only, opencl_filters, opencl_scale_only
    """
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
    # Run smokes (they cache results internally)
    smokes = {
        "cuda_filters": await smoke_test_cuda_filters(ffmpeg_path),
        "cuda_scale_only": await smoke_test_cuda_scale_only(ffmpeg_path),
        "opencl_filters": await smoke_test_opencl_filters(ffmpeg_path),
        "opencl_scale_only": await smoke_test_opencl_scale_only(ffmpeg_path),
    }
    return {"present": present, "smokes": smokes}


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
    # Base threads behavior
    threads = os.getenv("FFMPEG_THREADS", "0")  # let FFmpeg decide by default

    # Filter threads logic with caps
    # Defaults: when CPU filter mode is effective → cap small (<=4), else be conservative (1)
    try:
        cap_ft_env = os.getenv("FFMPEG_FILTER_THREADS_CAP")
        cap_fct_env = os.getenv("FFMPEG_FILTER_COMPLEX_THREADS_CAP")
        cap_ft = int(cap_ft_env) if cap_ft_env and cap_ft_env.isdigit() else None
        cap_fct = int(cap_fct_env) if cap_fct_env and cap_fct_env.isdigit() else None
    except Exception:
        cap_ft = cap_fct = None

    effective_cpu_filters = get_hw_filter_mode() == "cpu"
    default_cap = 4 if effective_cpu_filters else 1

    ft_val = int(nproc)
    fct_val = int(nproc)

    # Apply default conservative caps
    if effective_cpu_filters:
        ft_val = max(1, min(ft_val, default_cap))
        fct_val = max(1, min(fct_val, default_cap))
    else:
        ft_val = 1
        fct_val = 1

    # Apply explicit caps if provided
    if cap_ft is not None:
        ft_val = max(1, min(ft_val, cap_ft))
    if cap_fct is not None:
        fct_val = max(1, min(fct_val, cap_fct))

    return [
        "-threads",
        threads,
        "-filter_threads",
        str(ft_val),
        "-filter_complex_threads",
        str(fct_val),
    ]

