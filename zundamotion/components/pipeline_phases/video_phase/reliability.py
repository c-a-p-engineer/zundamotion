"""Reliability policy for VideoPhase clip-process concurrency."""

from __future__ import annotations

from typing import Any, Dict, List

from zundamotion.utils.ffmpeg_hw import get_hw_filter_mode
from zundamotion.utils.logger import logger

from .main import VideoPhase as _BaseVideoPhase


class ReliableVideoPhase(_BaseVideoPhase):
    """VideoPhase with conservative process concurrency for CPU overlays.

    BtbN FFmpeg has intermittently stalled near EOF when multiple software-CPU
    clip processes render overlay-heavy filter graphs concurrently. The same
    fixture is stable when clip processes are serialized. Limit only the risky
    automatic CPU/overlay combination; explicit jobs, simple CPU scenes, and
    hardware encoders keep their existing process parallelism.
    """

    def _apply_initial_worker_backoff(self, scenes: List[Dict[str, Any]]) -> None:
        jobs_mode = str(self.jobs or "").strip().lower()
        if jobs_mode not in {"", "0", "auto"}:
            return

        heavy_scenes = sum(
            1 for scene in scenes if self._scene_is_overlay_heavy(scene)
        )
        cpu_overlay_risk = (
            self.hw_kind is None
            and get_hw_filter_mode() == "cpu"
            and heavy_scenes > 0
        )
        if cpu_overlay_risk and self.clip_workers > 1:
            previous = self.clip_workers
            self.clip_workers = 1
            try:
                self.video_renderer.clip_workers = 1
            except Exception:
                pass
            logger.info(
                "[Reliability] serializing CPU overlay-heavy clips: "
                "clip_workers=%s->1 heavy_scenes=%s/%s reason=ffmpeg_overlay_stall",
                previous,
                heavy_scenes,
                len(scenes) or 1,
            )
            return

        # Preserve the existing broader >2 backoff policy for non-risk cases.
        super()._apply_initial_worker_backoff(scenes)
