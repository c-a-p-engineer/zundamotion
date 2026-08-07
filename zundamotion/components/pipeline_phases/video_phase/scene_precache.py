"""Subtitle and face-overlay precache stage for standard scene rendering."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

from ....utils import perf_stats
from ....utils.logger import logger
from .scene_standard_context import StandardSceneContext


class ScenePrecacheMixin:
    """Precache optional subtitle and face assets without changing failure policy."""

    async def _precache_standard_scene_assets(
        self,
        context: StandardSceneContext,
    ) -> None:
        scene = context.scene
        scene_id = context.scene_id
        line_data_map = self.line_data_map

        try:
            video_config = self.config.get("video", {}) or {}
            subtitle_gen = self.video_renderer.subtitle_gen
            mode_resolver = getattr(
                subtitle_gen,
                "resolve_render_mode_for_line_configs",
                None,
            )
            if callable(mode_resolver):
                subtitle_mode = mode_resolver(
                    [
                        (line_data_map.get(f"{scene_id}_{index}") or {}).get(
                            "line_config",
                            {},
                        )
                        for index, _line in enumerate(
                            scene.get("lines", []),
                            start=1,
                        )
                    ]
                )
            else:
                subtitle_mode = subtitle_gen.subtitle_render_mode()
            if subtitle_mode == "ass":
                raise RuntimeError("subtitle_precache_not_needed_for_ass")

            precache_default = bool(
                video_config.get("precache_subtitles", False)
            )
            try:
                precache_min_lines = int(
                    video_config.get("precache_min_lines", 6)
                )
            except Exception:
                precache_min_lines = 6
            will_precache = precache_default or (
                len(scene.get("lines", [])) >= precache_min_lines
            )
            if will_precache:
                renderer = subtitle_gen.png_renderer
                unique_subtitles: Dict[str, tuple[str, Dict[str, Any]]] = {}
                for index, _line in enumerate(scene.get("lines", []), start=1):
                    data = line_data_map.get(f"{scene_id}_{index}")
                    if not data:
                        continue
                    text = (data.get("text") or "").strip()
                    if not text:
                        continue
                    line_config = data.get("line_config") or {}
                    style_resolver = getattr(
                        subtitle_gen,
                        "resolve_subtitle_style",
                        None,
                    )
                    if callable(style_resolver):
                        style = style_resolver(line_config)
                    else:
                        style = (self.config.get("subtitle", {}) or {}).copy()
                        if "subtitle" in line_config and isinstance(
                            line_config["subtitle"],
                            dict,
                        ):
                            style.update(line_config["subtitle"])
                    dedupe_key = json.dumps(
                        {"text": text, "style": style},
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    )
                    unique_subtitles.setdefault(
                        dedupe_key,
                        (text, style),
                    )
                if unique_subtitles:
                    await asyncio.gather(
                        *(
                            renderer.render(text, style)
                            for text, style in unique_subtitles.values()
                        ),
                        return_exceptions=True,
                    )
                    logger.info(
                        "Precached %d unique subtitle PNG(s) for scene '%s'",
                        len(unique_subtitles),
                        scene_id,
                    )
        except Exception as error:
            logger.debug(
                "Subtitle precache skipped (scene=%s): %s",
                scene_id,
                error,
            )

        try:
            started = time.time()
            await self._precache_face_overlays(
                scene_id=scene_id,
                scene=scene,
                line_data_map=line_data_map,
            )
            perf_stats.add_ms(
                "face_precache_ms",
                (time.time() - started) * 1000.0,
            )
        except Exception as error:
            logger.debug(
                "Face overlay precache skipped (scene=%s): %s",
                scene_id,
                error,
            )
