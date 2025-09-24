"""FFmpegのスレッド設定ロジックを切り出したモジュール。"""

from __future__ import annotations

import multiprocessing
import os
from typing import List, Optional

from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.logger import logger


def build_ffmpeg_thread_flags(
    jobs: Optional[str],
    clip_workers: int,
    hw_kind: Optional[str],
) -> List[str]:
    """`VideoRenderer`から独立したスレッド設定を構築して返す。"""

    nproc = multiprocessing.cpu_count() or 1

    def _auto_threads_for_mode() -> str:
        global_mode = get_hw_filter_mode()
        if global_mode == "cpu":
            per_proc = max(1, nproc // max(1, clip_workers))
            return str(per_proc)
        return "0"

    if jobs is None or str(jobs).strip().lower() in {"auto", ""}:
        threads = _auto_threads_for_mode()
        logger.info(
            "[Jobs] Auto mode: nproc=%s, clip_workers=%s -> threads=%s",
            nproc,
            clip_workers,
            threads,
        )
    else:
        job_token = str(jobs).strip().lower()
        try:
            if job_token == "0":
                threads = _auto_threads_for_mode()
                logger.info(
                    "[Jobs] Auto(0) adjusted: nproc=%s, clip_workers=%s -> threads=%s",
                    nproc,
                    clip_workers,
                    threads,
                )
            else:
                explicit_jobs = int(job_token)
                if explicit_jobs <= 0:
                    threads = _auto_threads_for_mode()
                    logger.info(
                        "[Jobs] Non-positive --jobs -> auto adjusted to %s",
                        threads,
                    )
                else:
                    threads = str(explicit_jobs)
                    logger.info("[Jobs] Using specified threads=%s", threads)
        except ValueError:
            threads = _auto_threads_for_mode()
            logger.warning(
                "[Jobs] Invalid --jobs '%s'. Auto adjusted to %s.",
                jobs,
                threads,
            )

    ft_override = os.environ.get("FFMPEG_FILTER_THREADS")
    fct_override = os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS")

    global_filter_mode = get_hw_filter_mode()

    if ft_override and ft_override.isdigit():
        ft = ft_override
    else:
        if global_filter_mode == "cpu":
            per_filter_threads = max(1, nproc // max(1, clip_workers))
            cap_token = os.environ.get("FFMPEG_FILTER_THREADS_CAP")
            try:
                cap_value = int(cap_token) if cap_token and cap_token.isdigit() else 4
            except Exception:
                cap_value = 4
            ft = str(max(1, min(per_filter_threads, cap_value)))
        else:
            ft = "1" if hw_kind == "nvenc" else str(nproc)

    if fct_override and fct_override.isdigit():
        fct = fct_override
    else:
        if global_filter_mode == "cpu":
            per_filter_threads = max(1, nproc // max(1, clip_workers))
            cap_token = os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS_CAP")
            try:
                cap_value = int(cap_token) if cap_token and cap_token.isdigit() else 4
            except Exception:
                cap_value = 4
            fct = str(max(1, min(per_filter_threads, cap_value)))
        else:
            fct = "1" if hw_kind == "nvenc" else str(nproc)

    logger.info(
        "[FFmpeg Threads] mode=%s, nproc=%s, clip_workers=%s, threads=%s, "
        "filter_threads=%s, filter_complex_threads=%s, overrides(ft=%s,fct=%s)",
        get_hw_filter_mode(),
        nproc,
        clip_workers,
        threads,
        ft,
        fct,
        os.environ.get("FFMPEG_FILTER_THREADS"),
        os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS"),
    )

    return [
        "-threads",
        threads,
        "-filter_threads",
        ft,
        "-filter_complex_threads",
        fct,
    ]

