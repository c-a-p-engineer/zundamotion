"""Line performance recording and post-profile auto-tune decisions."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ....utils import perf_stats
from ....utils.ffmpeg_capabilities import get_ffmpeg_version
from ....utils.ffmpeg_hw import set_hw_filter_mode
from ....utils.logger import logger
from .scene_line_context import SceneLineContext
from .scene_talk_plan import SceneTalkPlan
from .scene_talk_renderer import TalkRenderOutcome


@dataclass(frozen=True)
class LineTimingSummary:
    """Stable descriptive statistics for collected line elapsed samples."""

    average: float
    p50: float
    p90: float
    p95: float
    maximum: float


def summarize_line_elapsed(values: Iterable[Any]) -> LineTimingSummary:
    """Return deterministic nearest-index statistics for positive seconds."""
    elapsed: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            elapsed.append(number)
    elapsed.sort()
    if not elapsed:
        return LineTimingSummary(0.0, 0.0, 0.0, 0.0, 0.0)

    def percentile(ratio: float) -> float:
        index = int(ratio * (len(elapsed) - 1))
        return elapsed[index]

    return LineTimingSummary(
        average=sum(elapsed) / float(len(elapsed)),
        p50=percentile(0.50),
        p90=percentile(0.90),
        p95=percentile(0.95),
        maximum=elapsed[-1],
    )


class SceneLineMetricsMixin:
    """Record line metrics and retune later scenes after a bounded sample."""

    def _record_talk_line_metrics(
        self,
        *,
        scene_id: str,
        context: SceneLineContext,
        plan: SceneTalkPlan,
        outcome: TalkRenderOutcome,
        line_total_started: float,
    ) -> None:
        total_ms = max(
            0.0,
            (outcome.finished_at - line_total_started) * 1000.0,
        )
        prepare_ms = max(
            0.0,
            (outcome.cache_started_at - line_total_started) * 1000.0,
        )
        cpu_overlay = (
            plan.has_subtitle
            or plan.has_visible_characters
            or plan.insert_is_image
        )
        if (
            self.phase.auto_tune_enabled
            and not getattr(self.phase, "parallel_scene_rendering", False)
            and len(self.phase._profile_samples) < self.phase.profile_limit
        ):
            self.phase._profile_samples.append(
                {
                    "cpu_overlay": cpu_overlay,
                    "elapsed": total_ms / 1000.0,
                }
            )

        try:
            task = asyncio.current_task()
            worker_id = task.get_name() if task is not None else "async-main"
            perf_stats.record_line_clip(
                {
                    "scene_id": scene_id,
                    "line_index": context.line_index,
                    "clip_id": context.line_id,
                    "duration_ms": total_ms,
                    "cache_status": outcome.cache_status,
                    "worker_id": worker_id,
                    "render_path": str(outcome.path),
                    "has_subtitle": plan.has_subtitle,
                    "has_face_overlay": bool(plan.face_animations),
                    "has_move": plan.has_move,
                    "has_effect": plan.has_effect,
                    "cache_lookup_ms": outcome.cache_lookup_ms,
                    "render_ms": outcome.render_ms,
                    "prepare_ms": prepare_ms,
                    "cache_store_ms": outcome.cache_store_ms,
                }
            )
            self.phase._clip_samples_all.append(
                {
                    "scene": scene_id,
                    "line": context.line_index,
                    "elapsed": total_ms / 1000.0,
                    "subtitle": plan.has_subtitle,
                    "chars": plan.has_visible_characters,
                    "insert_img": plan.insert_is_image,
                    "is_bg_video": context.background_is_video,
                    "cache": outcome.cache_status,
                }
            )
        except Exception as error:
            logger.warning(
                "Failed to record line clip performance scene=%s line=%s: %s",
                scene_id,
                context.line_index,
                error,
            )

    async def _maybe_retune_line_workers(self) -> None:
        if not (
            self.phase.auto_tune_enabled
            and not getattr(self.phase, "parallel_scene_rendering", False)
            and not self.phase._retuned
            and len(self.phase._profile_samples) >= self.phase.profile_limit
        ):
            return

        try:
            samples = list(self.phase._profile_samples)
            cpu_ratio = (
                sum(1 for sample in samples if sample.get("cpu_overlay"))
                / float(len(samples) or 1)
            )
            summary = summarize_line_elapsed(
                sample.get("elapsed", 0.0) for sample in samples
            )
            previous_workers = self.phase.clip_workers
            decision_mode = "auto"

            if cpu_ratio >= 0.5:
                os.environ.setdefault("FFMPEG_FILTER_THREADS_CAP", "2")
                os.environ.setdefault("FFMPEG_FILTER_COMPLEX_THREADS_CAP", "2")
                set_hw_filter_mode("cpu")
                decision_mode = "cpu"
                logger.info(
                    "[AutoTune] Set HW filter mode to 'cpu' due to CPU overlay dominance."
                )

                cpu_count = os.cpu_count() or 8
                target_workers = 2
                if cpu_count >= 16 and cpu_ratio >= 0.8:
                    target_workers = 4
                elif cpu_count >= 12 and cpu_ratio >= 0.6:
                    target_workers = 3
                self.phase.clip_workers = max(
                    1,
                    min(target_workers, cpu_count),
                )
                try:
                    self.video_renderer.clip_workers = self.phase.clip_workers
                except Exception:
                    pass
                logger.info(
                    "[AutoTune] cpu_ratio=%.2f avg=%.2fs p50=%.2fs p90=%.2fs p95=%.2fs max=%.2fs -> caps(ft,fct)=2, clip_workers %s -> %s",
                    cpu_ratio,
                    summary.average,
                    summary.p50,
                    summary.p90,
                    summary.p95,
                    summary.maximum,
                    previous_workers,
                    self.phase.clip_workers,
                )
            else:
                logger.info(
                    "[AutoTune] cpu_ratio=%.2f avg=%.2fs p50=%.2fs p90=%.2fs p95=%.2fs max=%.2fs -> keeping current concurrency",
                    cpu_ratio,
                    summary.average,
                    summary.p50,
                    summary.p90,
                    summary.p95,
                    summary.maximum,
                )

            os.environ["FFMPEG_PROFILE_MODE"] = "0"
            self.phase._retuned = True
            await self._write_line_autotune_hint(
                cpu_ratio=cpu_ratio,
                decision_mode=decision_mode,
                summary=summary,
            )
        except Exception as error:
            logger.warning("[AutoTune] Failed to apply line tuning: %s", error)

    async def _write_line_autotune_hint(
        self,
        *,
        cpu_ratio: float,
        decision_mode: str,
        summary: LineTimingSummary,
    ) -> Path | None:
        try:
            hint = {
                "cpu_ratio": cpu_ratio,
                "decided_mode": decision_mode,
                "clip_workers": self.phase.clip_workers,
                "avg_elapsed": summary.average,
                "p50_elapsed": summary.p50,
                "p90_elapsed": summary.p90,
                "p95_elapsed": summary.p95,
                "max_elapsed": summary.maximum,
                "ffmpeg": await get_ffmpeg_version(),
                "hw_kind": self.hw_kind,
            }
            hint_path = self.cache_manager.cache_dir / "autotune_hint.json"
            hint_path.parent.mkdir(parents=True, exist_ok=True)
            hint_path.write_text(
                json.dumps(hint, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("[AutoTune] Saved hint to %s", hint_path)
            return hint_path
        except Exception as error:
            logger.warning("[AutoTune] Failed to save hint: %s", error)
            return None
