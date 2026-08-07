"""Standard per-line scene rendering and assembly path.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

import json
import subprocess
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....exceptions import PipelineError
from ....utils.logger import logger
from ....utils import perf_stats


class SceneStandardRendererMixin:
    """Render line clips, assemble scene layers, and persist scene caches."""

    async def _render_scene_internal(
        self,
        scene: Dict[str, Any],
        scene_cp: bool,
        bg_default: Optional[str],
        scene_hash_data: Dict[str, Any],
    ) -> List[Path]:
        scene_id = scene["id"]
        line_data_map = self.line_data_map
        pbar_scenes = self.pbar_scenes
        scene_results: List[Path] = []
        generate_no_sub_video = bool(
            self.config.get("system", {}).get("generate_no_sub_video", False)
        )
        cache_scene_base_video = bool(
            self.config.get("system", {}).get("cache_scene_base_video", True)
        )
        scene_base_hash_data = self._scene_base_cache_data(scene_hash_data)
        scene_sub_hash_data = self._scene_subtitle_cache_data(
            scene_hash_data,
            scene_base_hash_data,
        )

        bg_image = scene.get("bg", bg_default)
        if not bg_image:
            raise PipelineError(f"Scene '{scene_id}' does not define a background.")
        is_bg_video = Path(bg_image).suffix.lower() in self.video_extensions
        has_line_bg_override = any(
            isinstance((line.get("background") or {}), dict)
            and bool((line.get("background") or {}).get("path"))
            for line in scene.get("lines", [])
        )

        timing_plan = self._build_scene_timing_plan(
            scene=scene,
            scene_hash_data=scene_hash_data,
            scene_base_hash_data=scene_base_hash_data,
        )
        lines = timing_plan.lines
        scene_duration = timing_plan.scene_duration
        start_time_by_idx = timing_plan.start_time_by_idx
        badge_line_markers = timing_plan.badge_line_markers
        subtitle_entries = timing_plan.subtitle_entries
        component_keys = timing_plan.component_keys
        subtitle_timing_key = timing_plan.subtitle_timing_key

        if cache_scene_base_video:
            cached_base_scene_path = self.cache_manager.get_cached_path(
                key_data=scene_base_hash_data,
                file_name=f"scene_{scene_id}_base",
                extension="mp4",
            )
            if cached_base_scene_path:
                perf_stats.record_line_clips_skipped_by_scene_cache(
                    sum(
                        1
                        for index, _line in lines
                        if (self.line_data_map.get(f"{scene_id}_{index}") or {}).get("type")
                        != "image_layer"
                    )
                )
                base_key = self._cache_key_short(scene_base_hash_data)
                self._record_scene_cache_event(
                    scene_id=scene_id,
                    layer="base",
                    status="HIT",
                    key=base_key,
                    detail=component_keys,
                )
                logger.info(
                    "[SceneCache] scene=%s layer=base HIT key=%s subtitle_timing_key=%s file=%s; reusing before subtitle burn",
                    scene_id,
                    base_key,
                    subtitle_timing_key,
                    cached_base_scene_path.name,
                )
                scene_output_path = cached_base_scene_path
                if subtitle_entries:
                    self._record_scene_cache_event(
                        scene_id=scene_id,
                        layer="sub",
                        status="MISS",
                        key=self._cache_key_short(scene_sub_hash_data),
                        reason="subtitle_layer_changed_base_hit",
                        detail=component_keys,
                    )
                    scene_output_path = await self.video_renderer.apply_subtitle_overlays(
                        cached_base_scene_path,
                        subtitle_entries,
                        scene_id=scene_id,
                    )
                    logger.info(
                        "[SceneCache] scene=%s layer=sub MISS reason=subtitle_layer_changed_base_hit subtitle_timing_key=%s -> burned subtitles from cached base (%d subtitles)",
                        scene_id,
                        subtitle_timing_key,
                        len(subtitle_entries),
                    )
                    self.cache_manager.cache_file(
                        source_path=scene_output_path,
                        key_data=scene_sub_hash_data,
                        file_name=f"scene_{scene_id}_sub",
                        extension="mp4",
                    )
                    logger.info(
                        "[SceneCache] scene=%s layer=sub STORE key=%s subtitle_timing_key=%s subtitles=%d",
                        scene_id,
                        self._cache_key_short(scene_sub_hash_data),
                        subtitle_timing_key,
                        len(subtitle_entries),
                    )
                    if generate_no_sub_video:
                        self.cache_manager.cache_file(
                            source_path=scene_output_path,
                            key_data=scene_hash_data,
                            file_name=f"scene_{scene_id}_sub",
                            extension="mp4",
                        )
                scene_results.append(scene_output_path)
                pbar_scenes.update(1)
                return scene_results
            base_key = self._cache_key_short(scene_base_hash_data)
            self._record_scene_cache_event(
                scene_id=scene_id,
                layer="base",
                status="MISS",
                key=base_key,
                reason="base_video_not_cached",
                detail=component_keys,
            )
            logger.info(
                "[SceneCache] scene=%s layer=base MISS key=%s subtitle_timing_key=%s reason=%s",
                scene_id,
                base_key,
                subtitle_timing_key,
                "base_video_not_cached",
            )
        else:
            self._record_scene_cache_event(
                scene_id=scene_id,
                layer="base",
                status="DISABLED",
                reason="cache_scene_base_video_false",
                detail=component_keys,
            )
            logger.info(
                "[SceneCache] scene=%s layer=base disabled reason=cache_scene_base_video_false",
                scene_id,
            )

        can_use_fast_path, fast_path_reason = self._can_use_simple_scene_fast_path(
            scene_duration=scene_duration,
            bg_image=bg_image,
            generate_no_sub_video=generate_no_sub_video,
            start_time_by_idx=start_time_by_idx,
        )
        if can_use_fast_path:
            fast_scene_path = await self._render_simple_scene_fast(
                scene_id=scene_id,
                bg_default=bg_image,
                scene_duration=scene_duration,
                start_time_by_idx=start_time_by_idx,
                scene_hash_data=scene_hash_data,
            )
            if fast_scene_path is not None:
                pbar_scenes.update(1)
                return [fast_scene_path]
        else:
            logger.info("Scene %s: skipping simple fast path (%s)", scene_id, fast_path_reason)

        # Optional: Pre-cache subtitle PNGs to reduce jitter during rendering
        try:
            vcfg = self.config.get("video", {}) or {}
            subtitle_gen = self.video_renderer.subtitle_gen
            subtitle_mode_resolver = getattr(
                subtitle_gen, "resolve_render_mode_for_line_configs", None
            )
            if callable(subtitle_mode_resolver):
                scene_subtitle_mode = subtitle_mode_resolver(
                    [
                        (line_data_map.get(f"{scene_id}_{idx}") or {}).get("line_config", {})
                        for idx, _line in enumerate(scene.get("lines", []), start=1)
                    ]
                )
            else:
                scene_subtitle_mode = subtitle_gen.subtitle_render_mode()
            if scene_subtitle_mode == "ass":
                raise RuntimeError("subtitle_precache_not_needed_for_ass")
            # Heuristic: enable precache when either explicitly enabled
            # or talk lines exceed configured threshold.
            precache_default = bool(vcfg.get("precache_subtitles", False))
            try:
                precache_min_lines = int(vcfg.get("precache_min_lines", 6))
            except Exception:
                precache_min_lines = 6
            will_precache = precache_default or (len(scene.get("lines", [])) >= precache_min_lines)
            if will_precache:
                renderer = self.video_renderer.subtitle_gen.png_renderer
                unique_subtitles: Dict[str, tuple[str, Dict[str, Any]]] = {}
                for idx, line in enumerate(scene.get("lines", []), start=1):
                    line_id = f"{scene_id}_{idx}"
                    data = line_data_map.get(line_id)
                    if not data:
                        continue
                    text = (data.get("text") or "").strip()
                    if not text:
                        continue
                    lc = data.get("line_config") or {}
                    style_resolver = getattr(subtitle_gen, "resolve_subtitle_style", None)
                    if callable(style_resolver):
                        style = style_resolver(lc)
                    else:
                        style = (self.config.get("subtitle", {}) or {}).copy()
                        if "subtitle" in lc and isinstance(lc["subtitle"], dict):
                            style.update(lc["subtitle"])  # line overrides
                    dedupe_key = json.dumps(
                        {"text": text, "style": style},
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    )
                    unique_subtitles.setdefault(dedupe_key, (text, style))
                if unique_subtitles:
                    import asyncio as _asyncio
                    precache_tasks = [
                        renderer.render(text, style)
                        for text, style in unique_subtitles.values()
                    ]
                    await _asyncio.gather(*precache_tasks, return_exceptions=True)
                    logger.info(
                        "Precached %d unique subtitle PNG(s) for scene '%s'",
                        len(unique_subtitles),
                        scene_id,
                    )
        except Exception as e:
            logger.debug("Subtitle precache skipped (scene=%s): %s", scene_id, e)

        try:
            face_precache_started = _time.time()
            await self._precache_face_overlays(
                scene_id=scene_id,
                scene=scene,
                line_data_map=line_data_map,
            )
            perf_stats.add_ms("face_precache_ms", (_time.time() - face_precache_started) * 1000.0)
        except Exception as e:
            logger.debug("Face overlay precache skipped (scene=%s): %s", scene_id, e)

        base_plan = self._build_scene_base_plan(
            scene=scene,
            scene_copy=scene_cp,
            is_background_video=is_bg_video,
            has_line_background_override=has_line_bg_override,
        )
        if base_plan.detection_error is not None:
            logger.debug(
                "Static overlay detection failed on scene %s: %s",
                scene_id,
                base_plan.detection_error,
            )
        base_result = await self._prepare_scene_base(
            scene_id=scene_id,
            background=bg_image,
            is_background_video=is_bg_video,
            scene_duration=scene_duration,
            plan=base_plan,
        )
        static_overlays = base_plan.static_overlays
        static_char_keys = base_plan.static_character_keys
        static_insert_in_base = base_plan.static_insert_in_base
        scene_level_insert_video = base_result.scene_level_insert_video
        scene_base_path = base_result.scene_base_path
        normalized_bg_path = base_result.normalized_background_path

        run_bases = await self._prepare_run_bases(
            scene_id=scene_id,
            background=str(bg_image),
            is_background_video=is_bg_video,
            scene_base_path=scene_base_path,
            scene_copy=scene_cp,
            has_line_background_override=has_line_bg_override,
        )

        # 先に各行の開始時刻を決定
        image_layers_by_line = self._collect_image_layers_by_line(
            [line for _, line in lines]
        )

        # 行処理本体。並列度・順序・cancelはSceneLineExecutorが管理する。
        async def process_one(
            idx: int, line: Dict[str, Any]
        ) -> Optional[Path]:
            import time as _time
            line_total_started = _time.perf_counter()
            context = self._build_scene_line_context(
                scene_id=scene_id,
                line_index=idx,
                line=line,
                scene_background=str(bg_image),
                scene_base_path=scene_base_path,
                normalized_background_path=normalized_bg_path,
                start_time_by_index=start_time_by_idx,
                run_bases=run_bases,
                image_layers_by_line=image_layers_by_line,
            )
            line_id = context.line_id
            line_is_bg_video = context.background_is_video

            if context.line_type == "image_layer":
                return None

            if context.line_type == "wait":
                return await self._render_wait_line(context)

            # Talk step
            text = context.text
            audio_path = context.audio_path
            logger.debug(
                f"Rendering clip for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
            )

            talk_plan = self._build_scene_talk_plan(
                context=context,
                static_character_keys=static_char_keys,
                static_insert_in_base=static_insert_in_base,
                scene_level_insert_video=scene_level_insert_video,
            )
            render_outcome = await self._render_talk_line(
                context=context,
                plan=talk_plan,
                static_character_keys=static_char_keys,
                static_insert_in_base=static_insert_in_base,
            )
            clip_path = render_outcome.path
            self._record_talk_line_metrics(
                scene_id=scene_id,
                context=context,
                plan=talk_plan,
                outcome=render_outcome,
                line_total_started=line_total_started,
            )
            return clip_path

        results = await self._execute_scene_lines(
            lines,
            process_one,
            max_workers=self.phase.clip_workers,
            scene_id=scene_id,
        )

        await self._maybe_retune_line_workers()

        # 順序維持で集約
        scene_line_clips: List[Path] = [p for p in results if p is not None]

        if scene_line_clips:
            scene_output_path = self.temp_dir / f"scene_output_{scene_id}.mp4"
            concat_started = _time.time()
            await self.video_renderer.concat_clips(
                scene_line_clips, str(scene_output_path)
            )
            perf_stats.add_ms("scene_concat_ms", (_time.time() - concat_started) * 1000.0)
            logger.info(f"Concatenated scene clips -> {scene_output_path.name}")

            fg_overlays = await self._resolve_visual_overlays(
                scene,
                scope_id=scene_id,
                line_markers=badge_line_markers,
            )
            scene_output_no_sub_path = scene_output_path
            if fg_overlays:
                scene_output_no_sub_path = await self.video_renderer.apply_foreground_overlays(
                    scene_output_path, fg_overlays
                )
                logger.info(
                    f"Applied foreground overlays -> {scene_output_no_sub_path.name}"
                )
            if cache_scene_base_video:
                self.cache_manager.cache_file(
                    source_path=scene_output_no_sub_path,
                    key_data=scene_base_hash_data,
                    file_name=f"scene_{scene_id}_base",
                    extension="mp4",
                )
                logger.info(
                    "[SceneCache] scene=%s layer=base STORE key=%s subtitle_timing_key=%s file_name=scene_%s_base.mp4",
                    scene_id,
                    self._cache_key_short(scene_base_hash_data),
                    subtitle_timing_key,
                    scene_id,
                )
            if subtitle_entries:
                scene_output_path = await self.video_renderer.apply_subtitle_overlays(
                    scene_output_no_sub_path, subtitle_entries, scene_id=scene_id
                )
                logger.info(f"Applied subtitles -> {scene_output_path.name}")
                self.cache_manager.cache_file(
                    source_path=scene_output_path,
                    key_data=scene_sub_hash_data,
                    file_name=f"scene_{scene_id}_sub",
                    extension="mp4",
                )
                logger.info(
                    "[SceneCache] scene=%s layer=sub STORE key=%s subtitle_timing_key=%s subtitles=%d",
                    scene_id,
                    self._cache_key_short(scene_sub_hash_data),
                    subtitle_timing_key,
                    len(subtitle_entries),
                )
                if generate_no_sub_video:
                    self.cache_manager.cache_file(
                        source_path=scene_output_no_sub_path,
                        key_data=scene_hash_data,
                        file_name=f"scene_{scene_id}",
                        extension="mp4",
                    )
                    self.cache_manager.cache_file(
                        source_path=scene_output_path,
                        key_data=scene_hash_data,
                        file_name=f"scene_{scene_id}_sub",
                        extension="mp4",
                    )
            else:
                scene_output_path = scene_output_no_sub_path
                self.cache_manager.cache_file(
                    source_path=scene_output_path,
                    key_data=scene_hash_data,
                    file_name=f"scene_{scene_id}",
                    extension="mp4",
                )
            scene_results.append(scene_output_path)

        if (
            scene_base_path
            and scene_base_path.exists()
            and self.cache_manager.cache_dir.resolve() not in scene_base_path.resolve().parents
        ):
            try:
                scene_base_path.unlink()
                logger.debug(
                    f"Cleaned up temporary scene base video -> {scene_base_path.name}"
                )
            except Exception:
                pass
        pbar_scenes.update(1)
        return scene_results
