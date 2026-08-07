"""Ordered scene clip assembly, foreground composition, and subtitle burn."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ....utils import perf_stats
from ....utils.logger import logger


@dataclass(frozen=True)
class SceneAssemblyResult:
    """Generated scene media before and after subtitle burn."""

    line_clips: tuple[Path, ...]
    no_sub_path: Path
    final_path: Path

    @property
    def has_subtitles(self) -> bool:
        return self.final_path != self.no_sub_path


class SceneAssemblyMixin:
    """Assemble ordered line results without owning cache or cleanup policy."""

    async def _assemble_scene_media(
        self,
        *,
        scene_id: str,
        line_results: Iterable[Optional[Path]],
        scene: Dict[str, Any],
        badge_line_markers: Mapping[str, float],
        subtitle_entries: list[Dict[str, Any]],
    ) -> Optional[SceneAssemblyResult]:
        line_clips = tuple(
            Path(path)
            for path in line_results
            if path is not None
        )
        if not line_clips:
            logger.info(
                "[SceneAssembly] scene=%s status=empty line_clips=0",
                scene_id,
            )
            return None

        concatenated_path = self.temp_dir / f"scene_output_{scene_id}.mp4"
        concat_started = time.perf_counter()
        await self.video_renderer.concat_clips(
            list(line_clips),
            str(concatenated_path),
        )
        perf_stats.add_ms(
            "scene_concat_ms",
            (time.perf_counter() - concat_started) * 1000.0,
        )
        logger.info("Concatenated scene clips -> %s", concatenated_path.name)

        foreground_overlays = await self._resolve_visual_overlays(
            scene,
            scope_id=scene_id,
            line_markers=dict(badge_line_markers),
        )
        no_sub_path = concatenated_path
        if foreground_overlays:
            no_sub_path = Path(
                await self.video_renderer.apply_foreground_overlays(
                    concatenated_path,
                    foreground_overlays,
                )
            )
            logger.info("Applied foreground overlays -> %s", no_sub_path.name)

        final_path = no_sub_path
        if subtitle_entries:
            final_path = Path(
                await self.video_renderer.apply_subtitle_overlays(
                    no_sub_path,
                    subtitle_entries,
                    scene_id=scene_id,
                )
            )
            logger.info("Applied subtitles -> %s", final_path.name)

        logger.info(
            "[SceneAssembly] scene=%s status=success line_clips=%d foreground=%s subtitles=%d output=%s",
            scene_id,
            len(line_clips),
            str(bool(foreground_overlays)).lower(),
            len(subtitle_entries),
            final_path.name,
        )
        return SceneAssemblyResult(
            line_clips=line_clips,
            no_sub_path=no_sub_path,
            final_path=final_path,
        )
