"""Standard per-line scene rendering and assembly path.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....exceptions import PipelineError
from ....utils.logger import logger
from ....utils import perf_stats
from ....utils.subtitle_text import is_effective_subtitle_text


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

        # 並列レンダリング用のタスクを構築
        import asyncio

        # If auto-tune has retuned clip_workers, new sem will reflect it
        sem = asyncio.Semaphore(self.phase.clip_workers)
        results: List[Optional[Path]] = [None] * len(lines)

        async def process_one(idx: int, line: Dict[str, Any]):
            async with sem:
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
                line_data = context.line_data
                duration = context.duration
                pre_dur = context.pre_duration
                line_config = context.line_config
                extra_audio_overlays = list(context.extra_audio_overlays)
                bg_layout = context.background_layout
                line_bg_image = context.background_source
                line_is_bg_video = context.background_is_video
                run_base = context.run_base
                background_config = context.background_config
                line_image_layers = list(context.image_layer_overlays)

                if context.line_type == "image_layer":
                    results[idx - 1] = None
                    return

                if context.line_type == "wait":
                    logger.debug(
                        f"Rendering wait clip for {duration}s (Scene '{scene_id}', Line {idx})"
                    )
                    wait_cache_data = {
                        "type": "wait",
                        "duration": duration,
                        "bg_image_path": line_bg_image,
                        "is_bg_video": line_is_bg_video,
                        "start_time": start_time_by_idx[idx],
                        "video_config": self.config.get("video", {}),
                        "line_config": line_config,
                        "image_layer_overlays": line_image_layers,
                        "extra_audio_overlays": extra_audio_overlays,
                        "hw_kind": self.hw_kind,
                        "video_params": self.video_params.__dict__,
                        "audio_params": self.audio_params.__dict__,
                        "screen_effects": line_config.get("screen_effects"),
                        "background_effects": line_config.get("background_effects"),
                        "background_layout": bg_layout,
                        "video_filter": background_config.get("video_filter"),
                    }

                    async def wait_creator_func(output_path: Path) -> Path:
                        clip_path = await self.video_renderer.render_wait_clip(
                            duration,
                            background_config,
                            output_path.stem,
                            line_config,
                            characters_config=line_config.get("characters", []) or [],
                            image_layer_overlays=line_image_layers,
                            extra_audio_overlays=extra_audio_overlays,
                        )
                        if clip_path is None:
                            raise PipelineError(
                                f"Wait clip rendering failed for line: {line_id}"
                            )
                        return clip_path

                    clip_path = await self.cache_manager.get_or_create(
                        key_data=wait_cache_data,
                        file_name=line_id,
                        extension="mp4",
                        creator_func=wait_creator_func,
                    )
                    fg_overlays = await self._resolve_visual_overlays(
                        line,
                        scope_id=line_id,
                    )
                    if fg_overlays:
                        clip_path = await self.video_renderer.apply_foreground_overlays(
                            clip_path, fg_overlays
                        )
                    results[idx - 1] = clip_path
                    return

                # Talk step
                text = context.text
                audio_path = context.audio_path
                logger.debug(
                    f"Rendering clip for line '{text[:30]}...' (Scene '{scene_id}', Line {idx})"
                )

                audio_cache_key_data = {
                    "text": text,
                    "line_config": line_config,
                    "voice_config": self.config.get("voice", {}),
                }
                # 静的レイヤをベースに取り込んでいる場合、行側から該当項目のみ除去
                original_characters = line.get("characters", []) or []
                if static_char_keys or (run_base and run_base.character_keys):
                    eff_chars: List[Dict[str, Any]] = []
                    for ch in original_characters:
                        if not ch.get("visible", False):
                            eff_chars.append(ch)
                            continue
                        entry_keys = set(
                            self._norm_char_entries({"characters": [ch]}).keys()
                        )
                        if entry_keys & static_char_keys or (
                            run_base
                            and entry_keys & run_base.character_keys
                        ):
                            continue
                        eff_chars.append(ch)
                    effective_characters = eff_chars
                else:
                    effective_characters = original_characters

                # ベースに取り込まれていない共通挿入“動画”があれば、事前正規化済みのパスを各行へ伝搬
                if static_insert_in_base or (run_base and run_base.has_insert_image):
                    effective_insert = None
                else:
                    raw_insert = line_config.get("insert")
                    if (
                        scene_level_insert_video is not None
                        and raw_insert
                        and Path(raw_insert.get("path", "")).exists()
                    ):
                        effective_insert = {
                            **raw_insert,
                            "path": str(scene_level_insert_video),
                            "normalized": True,
                            "pre_scaled": True,
                        }
                    else:
                        effective_insert = raw_insert

                # Face animation config versioning for cache stability
                face_anim_raw = line_data.get("face_anim")
                if isinstance(face_anim_raw, list):
                    face_anim_list = face_anim_raw
                elif face_anim_raw:
                    face_anim_list = [face_anim_raw]
                else:
                    face_anim_list = []
                first_anim_meta = face_anim_list[0] if face_anim_list else {}
                anim_meta = (first_anim_meta or {}).get("meta") or {}
                video_cache_data = {
                    "type": "talk",
                    "clip_render_version": "20260330_face_overlay_args_v2",
                    "audio_cache_key": self.cache_manager._generate_hash(
                        audio_cache_key_data
                    ),
                    "duration": duration,
                    "audio_delay": pre_dur,
                    "post_duration": float(line_data.get("post_duration", 0.0)),
                    "bg_image_path": line_bg_image,
                    "is_bg_video": line_is_bg_video,
                    "start_time": start_time_by_idx[idx],
                    "video_config": self.config.get("video", {}),
                    "bgm_config": self.config.get("bgm", {}),
                    "insert_config": effective_insert,
                    "image_layer_overlays": line_image_layers,
                    "extra_audio_overlays": extra_audio_overlays,
                    "static_chars_in_base": bool(static_char_keys),
                    "static_insert_in_base": static_insert_in_base,
                    "hw_kind": self.hw_kind,
                    "video_params": self.video_params.__dict__,
                    "audio_params": self.audio_params.__dict__,
                    # Minimal cache key for face animation
                    "lip_eye_version": "v2",
                    "face_anim_enabled": bool(face_anim_list),
                    "mouth_fps": anim_meta.get("mouth_fps"),
                    "thr_half": anim_meta.get("thr_half"),
                    "thr_open": anim_meta.get("thr_open"),
                    "blink_min_interval": anim_meta.get("blink_min_interval"),
                    "blink_max_interval": anim_meta.get("blink_max_interval"),
                    "blink_close_frames": anim_meta.get("blink_close_frames"),
                    "screen_effects": line_config.get("screen_effects"),
                    "background_effects": line_config.get("background_effects"),
                    "background_layout": bg_layout,
                    "video_filter": background_config.get("video_filter"),
                }

                has_subtitle = is_effective_subtitle_text(line_data.get("text"))
                any_chars = any(
                    (character or {}).get("visible", False)
                    for character in (line.get("characters", []) or [])
                )
                insert_config = line_config.get("insert") or {}
                insert_path = str(insert_config.get("path", ""))
                insert_is_image = insert_path.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".bmp", ".webp")
                )
                has_move = bool(line_config.get("move")) or any(
                    bool((character or {}).get("move"))
                    for character in (line.get("characters", []) or [])
                )
                has_effect = bool(
                    line_config.get("background_effects")
                    or line_config.get("screen_effects")
                )
                creator_started: Optional[float] = None
                creator_finished: Optional[float] = None
                render_ms = 0.0

                async def clip_creator_func(output_path: Path) -> Path:
                    nonlocal creator_started, creator_finished, render_ms
                    creator_started = _time.perf_counter()
                    render_started = creator_started
                    clip_path = await self.video_renderer.render_clip(
                        audio_path=audio_path,
                        duration=duration,
                        background_config=background_config,
                        characters_config=effective_characters,
                        output_filename=output_path.stem,
                        # Scene-level subtitle burn-in remains the source of truth.
                        # Only pass line_config so face overlay fallback can recover
                        # character placement when the base scene already contains it.
                        subtitle_text=None,
                        subtitle_line_config=line_config,
                        insert_config=effective_insert,
                        image_layer_overlays=line_image_layers,
                        extra_audio_overlays=extra_audio_overlays,
                        background_effects=line_config.get("background_effects"),
                        screen_effects=line_config.get("screen_effects"),
                        face_anim=face_anim_list,
                        audio_delay=pre_dur,
                        _force_cpu=bool(line_image_layers),
                    )
                    if clip_path is None:
                        raise PipelineError(
                            f"Clip rendering failed for line: {line_id}"
                        )
                    creator_finished = _time.perf_counter()
                    render_ms = (creator_finished - render_started) * 1000.0
                    return clip_path

                cache_started = _time.perf_counter()
                clip_path = await self.cache_manager.get_or_create(
                    key_data=video_cache_data,
                    file_name=line_id,
                    extension="mp4",
                    creator_func=clip_creator_func,
                )
                cache_finished = _time.perf_counter()
                fg_overlays = await self._resolve_visual_overlays(
                    line,
                    scope_id=line_id,
                )
                if fg_overlays:
                    clip_path = await self.video_renderer.apply_foreground_overlays(
                        clip_path, fg_overlays
                    )
                total_finished = _time.perf_counter()
                total_ms = (total_finished - line_total_started) * 1000.0
                cache_status = "miss" if creator_started is not None else "hit"
                cache_lookup_ms = (
                    (creator_started - cache_started) * 1000.0
                    if creator_started is not None
                    else (cache_finished - cache_started) * 1000.0
                )
                cache_store_ms = (
                    max(0.0, (cache_finished - creator_finished) * 1000.0)
                    if creator_finished is not None
                    else 0.0
                )
                prepare_ms = max(0.0, (cache_started - line_total_started) * 1000.0)
                # Collect lightweight samples for auto-tune
                if (
                    self.phase.auto_tune_enabled
                    and not getattr(self.phase, "parallel_scene_rendering", False)
                    and len(self.phase._profile_samples) < self.phase.profile_limit
                ):
                    self.phase._profile_samples.append(
                        {
                            "cpu_overlay": has_subtitle or any_chars or insert_is_image,
                            "elapsed": total_ms / 1000.0,
                        }
                    )
                try:
                    task = asyncio.current_task()
                    worker_id = task.get_name() if task is not None else "async-main"
                    perf_stats.record_line_clip(
                        {
                            "scene_id": scene_id,
                            "line_index": idx,
                            "clip_id": line_id,
                            "duration_ms": total_ms,
                            "cache_status": cache_status,
                            "worker_id": worker_id,
                            "render_path": str(clip_path),
                            "has_subtitle": has_subtitle,
                            "has_face_overlay": bool(face_anim_list),
                            "has_move": has_move,
                            "has_effect": has_effect,
                            "cache_lookup_ms": cache_lookup_ms,
                            "render_ms": render_ms,
                            "prepare_ms": prepare_ms,
                            "cache_store_ms": cache_store_ms,
                        }
                    )
                    self.phase._clip_samples_all.append(
                        {
                            "scene": scene_id,
                            "line": idx,
                            "elapsed": total_ms / 1000.0,
                            "subtitle": has_subtitle,
                            "chars": any_chars,
                            "insert_img": insert_is_image,
                            "is_bg_video": line_is_bg_video,
                            "cache": cache_status,
                        }
                    )
                except Exception as measurement_error:
                    logger.warning(
                        "Failed to record line clip performance scene=%s line=%s: %s",
                        scene_id,
                        idx,
                        measurement_error,
                    )
                results[idx - 1] = clip_path

        tasks = [process_one(idx, line) for idx, line in lines]
        # 並列実行
        await asyncio.gather(*tasks)

        # After first scene (or once enough samples), auto-tune for subsequent scenes
        if (
            self.phase.auto_tune_enabled
            and not getattr(self.phase, "parallel_scene_rendering", False)
            and not self.phase._retuned
            and len(self.phase._profile_samples) >= self.phase.profile_limit
        ):
            try:
                cpu_ratio = (
                    sum(1 for s in self.phase._profile_samples if s.get("cpu_overlay"))
                    / float(len(self.phase._profile_samples) or 1)
                )
                import os as _os
                # Basic throughput stats on the profiled clips
                try:
                    elapsed_vals = [
                        float(s.get("elapsed", 0.0))
                        for s in self.phase._profile_samples
                    ]
                    elapsed_vals = [v for v in elapsed_vals if v > 0]
                    elapsed_vals.sort()
                    avg_elapsed = sum(elapsed_vals) / float(len(elapsed_vals) or 1)
                    p90_elapsed = elapsed_vals[int(0.9 * (len(elapsed_vals) - 1))] if elapsed_vals else 0.0
                except Exception:
                    avg_elapsed = 0.0
                    p90_elapsed = 0.0
                # Be conservative on CPU overlays
                if cpu_ratio >= 0.5:
                    # Tighten filter caps and lower concurrency
                    _os.environ.setdefault("FFMPEG_FILTER_THREADS_CAP", "2")
                    _os.environ.setdefault(
                        "FFMPEG_FILTER_COMPLEX_THREADS_CAP", "2"
                    )
                    # CPU overlay 優勢時はGPUフィルタを全体でオフにしてスレッド最適化を適用
                    try:
                        set_hw_filter_mode("cpu")
                        logger.info(
                            "[AutoTune] Set HW filter mode to 'cpu' due to CPU overlay dominance."
                        )
                    except Exception:
                        pass
                    # Explore a slightly higher worker count on larger CPUs
                    prev_workers = self.phase.clip_workers
                    cpu_cnt = _os.cpu_count() or 8
                    target_workers = 2
                    if cpu_cnt >= 16 and cpu_ratio >= 0.8:
                        target_workers = 4
                    elif cpu_cnt >= 12 and cpu_ratio >= 0.6:
                        target_workers = 3
                    # Keep within CPU count
                    target_workers = max(1, min(target_workers, cpu_cnt))
                    # Apply the decided target
                    self.phase.clip_workers = target_workers
                    # Propagate new concurrency to the renderer for consistent thread logging
                    try:
                        self.video_renderer.clip_workers = self.phase.clip_workers
                    except Exception:
                        pass
                    logger.info(
                        "[AutoTune] cpu_ratio=%.2f avg=%.2fs p90=%.2fs -> caps(ft,fct)=2, clip_workers %s -> %s",
                        cpu_ratio,
                        avg_elapsed,
                        p90_elapsed,
                        prev_workers,
                        self.phase.clip_workers,
                    )
                else:
                    logger.info(
                        "[AutoTune] cpu_ratio=%.2f avg=%.2fs p90=%.2fs -> keeping current concurrency",
                        cpu_ratio,
                        avg_elapsed,
                        p90_elapsed,
                    )
                # Disable profiling overhead after retune
                _os.environ["FFMPEG_PROFILE_MODE"] = "0"
                self.phase._retuned = True
                # Persist hint for next runs
                try:
                    import json as _json
                    from zundamotion.utils.ffmpeg_capabilities import get_ffmpeg_version
                    hint = {
                        "cpu_ratio": cpu_ratio,
                        "decided_mode": "cpu" if cpu_ratio >= 0.5 else "auto",
                        "clip_workers": self.phase.clip_workers,
                        "avg_elapsed": avg_elapsed,
                        "p90_elapsed": p90_elapsed,
                        "ffmpeg": await get_ffmpeg_version(),
                        "hw_kind": self.hw_kind,
                    }
                    hint_path = self.cache_manager.cache_dir / "autotune_hint.json"
                    with open(hint_path, "w", encoding="utf-8") as f:
                        _json.dump(hint, f, ensure_ascii=False)
                    logger.info("[AutoTune] Saved hint to %s", hint_path)
                except Exception:
                    pass
            except Exception:
                pass

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
