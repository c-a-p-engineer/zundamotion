"""FFmpeg/ffprobe invocation classification and A/V warning diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import perf_stats
from .logger import logger


def _classify_ffprobe_call(args: List[str]) -> str:
    joined = " ".join(str(token) for token in args)
    if "format=duration" in joined:
        return "ffprobe_duration_calls"
    if "show_streams" in joined or "stream=" in joined:
        return "ffprobe_stream_calls"
    return "ffprobe_other_calls"


def _guess_ffmpeg_output_path(args: List[str]) -> Optional[Path]:
    if not args or os.path.basename(str(args[0])).startswith("ffprobe"):
        return None
    for token in reversed(args[1:]):
        value = str(token)
        if not value or value.startswith("-"):
            continue
        if value in {"pipe:1", "pipe:2", "-", "NUL", "/dev/null"}:
            return None
        return Path(value)
    return None


def _guess_ffmpeg_input_paths(args: List[str]) -> list[str]:
    inputs: list[str] = []
    for index, token in enumerate(args[:-1]):
        if str(token) != "-i":
            continue
        value = str(args[index + 1])
        if value not in {"pipe:0", "pipe:1", "pipe:2", "-", "NUL", "/dev/null"}:
            inputs.append(value)
    return inputs


def _normalize_warning_type(line: str) -> Optional[str]:
    lower = line.lower()
    if "queue input is backward in time" in lower:
        return "queue_input_backward"
    if "non-monotonic dts" in lower:
        return "non_monotonic_dts"
    if "past duration" in lower:
        return "past_duration"
    if "invalid dropping" in lower:
        return "invalid_dropping"
    if " dts" in lower or lower.startswith("dts"):
        return "dts_warning"
    if " pts" in lower or lower.startswith("pts"):
        return "pts_warning"
    return None


def _extract_av_warning_items(stderr_text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_line in stderr_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        warning_type = _normalize_warning_type(line)
        if warning_type:
            items.append({"type": warning_type, "message": line})
    return items


def prepare_ffmpeg_context(args: List[str], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = dict(context or {})
    resolved.setdefault("input_paths", _guess_ffmpeg_input_paths(args))
    resolved.setdefault("output_path", str(_guess_ffmpeg_output_path(args) or ""))
    return resolved


def record_invocation(args: List[str], base: str) -> None:
    if base.startswith("ffprobe"):
        perf_stats.incr("ffprobe_calls")
        perf_stats.incr(_classify_ffprobe_call(args))
    elif base.startswith("ffmpeg"):
        perf_stats.incr("ffmpeg_calls")


def record_ffprobe_duration(
    args: List[str], context: Dict[str, Any], elapsed_seconds: float
) -> None:
    base = os.path.basename(str(args[0])) if args else ""
    if not base.startswith("ffprobe"):
        return
    counter = _classify_ffprobe_call(args)
    kind = counter.removeprefix("ffprobe_").removesuffix("_calls")
    path = str(context.get("path") or "")
    if not path:
        inputs = context.get("input_paths") or []
        if inputs:
            path = str(inputs[-1])
    perf = perf_stats.current_perf_stats()
    if perf is not None:
        perf.record_ffprobe_call(
            kind=kind,
            caller=str(context.get("caller") or "unknown"),
            path=path,
            elapsed_ms=elapsed_seconds * 1000.0,
            cache_hit=False,
        )


def record_av_warnings(stderr_text: str, context: Dict[str, Any], base: str) -> None:
    if not stderr_text:
        return
    perf = perf_stats.current_perf_stats()
    for item in _extract_av_warning_items(stderr_text):
        warning = {
            "run_id": getattr(perf, "run_id", None),
            "phase": str(context.get("phase") or "unknown"),
            "operation": str(context.get("operation") or base),
            "scene_id": context.get("scene_id"),
            "line_id": context.get("line_id"),
            "chunk_index": context.get("chunk_index"),
            "transition_index": context.get("transition_index"),
            "type": item["type"],
            "input_paths": list(context.get("input_paths") or []),
            "output_path": context.get("output_path"),
            "message": item["message"],
        }
        if perf is not None:
            perf.record_av_warning(warning)
        logger.warning(
            "[AVWarning] run_id=%s phase=%s operation=%s scene_id=%s line_id=%s chunk_index=%s transition_index=%s type=%s input=%s output=%s message=%r",
            warning.get("run_id") or "-",
            warning.get("phase") or "-",
            warning.get("operation") or "-",
            warning.get("scene_id") or "-",
            warning.get("line_id") or "-",
            warning.get("chunk_index") if warning.get("chunk_index") is not None else "-",
            warning.get("transition_index") if warning.get("transition_index") is not None else "-",
            warning.get("type") or "-",
            ",".join(str(path) for path in warning.get("input_paths") or []) or "-",
            warning.get("output_path") or "-",
            warning.get("message") or "",
        )
