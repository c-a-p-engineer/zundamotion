"""Resolve AudioPhase concurrency without owning task execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AudioWorkerPolicy:
    requested: str
    resolved: int
    source: str
    automatic: bool
    fallback_reason: str | None = None


def resolve_audio_worker_policy(
    voice_config: Mapping[str, Any] | None,
    environ: Mapping[str, str],
    *,
    cpu_count: int | None,
) -> AudioWorkerPolicy:
    config = voice_config or {}
    env_value = environ.get("ZUNDAMOTION_AUDIO_WORKERS")
    if env_value is not None:
        raw: Any = env_value
        source = "environment"
    elif "parallel_workers" in config:
        raw = config.get("parallel_workers")
        source = "voice_config"
    else:
        raw = "auto"
        source = "default"

    requested = str(raw if raw is not None else "auto").strip().lower()
    if requested in {"", "auto", "0"}:
        resolved = max(1, min(2, int(cpu_count or 2)))
        return AudioWorkerPolicy(
            requested=requested or "auto",
            resolved=resolved,
            source=source,
            automatic=True,
        )

    try:
        resolved = max(1, int(requested))
    except (TypeError, ValueError):
        return AudioWorkerPolicy(
            requested=requested,
            resolved=2,
            source=source,
            automatic=True,
            fallback_reason="invalid_value",
        )
    return AudioWorkerPolicy(
        requested=requested,
        resolved=resolved,
        source=source,
        automatic=False,
    )
