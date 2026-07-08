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
from ....utils.ffmpeg_ops import normalize_media
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

        # キャラクターの登場/退場アニメーション秒数を行ごとに反映
        for idx, line in enumerate(scene.get("lines", []), start=1):
            line_id = f"{scene_id}_{idx}"
            data = line_data_map.get(line_id)
            if not data:
                continue
            chars = line.get("characters", []) or []

            def _max_dur(key: str) -> float:
                """Return max duration for enter/leave across characters."""
                dur = 0.0
                flag = key.replace("_duration", "")
                for ch in chars:
                    if ch.get(flag):
                        try:
                            d = float(ch.get(key, 0.0))
                        except Exception:
                            d = 0.0
                        dur = max(dur, d)
                return dur

            enter_pad = _max_dur("enter_duration")
            leave_pad = _max_dur("leave_duration")
            data["pre_duration"] = enter_pad
            data["post_duration"] = leave_pad
            data["duration"] = float(data.get("duration", 0.0)) + enter_pad + leave_pad

        scene_duration = sum(
            line_data_map[f"{scene_id}_{idx + 1}"]["duration"]
            for idx, line in enumerate(scene.get("lines", []))
        )

        lines = list(enumerate(scene.get("lines", []), start=1))
        start_time_by_idx: Dict[int, float] = {}
        t_acc = 0.0
        for idx, _line in lines:
            line_id2 = f"{scene_id}_{idx}"
            d = line_data_map[line_id2]["duration"]
            start_time_by_idx[idx] = t_acc
            t_acc += d
        badge_line_markers = self._build_badge_line_markers(
            start_time_by_idx=start_time_by_idx,
        )
        subtitle_entries = self._build_subtitle_entries(scene_id, start_time_by_idx)
        component_keys = self._scene_cache_component_keys(
            scene_hash_data,
            scene_base_hash_data,
        )
        subtitle_timing_key = self._subtitle_timing_key(subtitle_entries)
        component_keys["subtitle_timing_key"] = subtitle_timing_key

        if cache_scene_base_video:
            cached_base_scene_path = self.cache_manager.get_cached_path(
                key_data=scene_base_hash_data,
                file_name=f"scene_{scene_id}_base",
                extension="mp4",
            )
            if cached_base_scene_path:
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

        # シーンベース映像（背景のみ）を事前生成（動画/静止画どちらでも）
        scene_base_path: Optional[Path] = None
        # 静的レイヤ（全行で不変な立ち絵・挿入画像）を検出（項目単位の共通部分を抽出）
        static_overlays: List[Dict[str, Any]] = []
        static_char_keys: set = set()
        static_insert_in_base = False
        scene_level_insert_video: Optional[Path] = None
        try:
            talk_lines = [
                l
                for l in scene.get("lines", [])
                if not ("wait" in l or l.get("type") == "wait")
            ]
            if talk_lines:
                # 各行の可視キャラを正規化してキー化（name, expr, scale, anchor, pos）
                per_line_char_maps = [self._norm_char_entries(tl) for tl in talk_lines]
                if per_line_char_maps:
                    common_keys = set(per_line_char_maps[0].keys())
                    for m in per_line_char_maps[1:]:
                        common_keys &= set(m.keys())
                    for key in sorted(common_keys):
                        ov = per_line_char_maps[0][key]
                        p = Path(ov["path"])  # expr 固定のはず
                        if not p.exists():
                            # default フォールバック（新/旧いずれか）
                            name, _expr, _s, _a, _x, _y = key
                            alt1 = Path(f"assets/characters/{name}/default/base.png")
                            alt2 = Path(f"assets/characters/{name}/default.png")
                            if alt1.exists():
                                ov = {**ov, "path": str(alt1)}
                            elif alt2.exists():
                                ov = {**ov, "path": str(alt2)}
                            else:
                                continue
                        static_overlays.append(ov)
                        static_char_keys.add(key)

                # 画像の挿入が全行共通か（画像のみ、動画は対象外）
                first_insert = talk_lines[0].get("insert")
                if first_insert:
                    same_insert_all = all(
                        (tl.get("insert") == first_insert) for tl in talk_lines
                    )
                    if same_insert_all:
                        insert_path = Path(first_insert.get("path", ""))
                        # 画像はベースへ取り込み、動画はシーン単位で事前正規化のみ行う
                        if insert_path.suffix.lower() in [
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".bmp",
                            ".webp",
                        ] and insert_path.exists():
                            static_overlays.append(
                                {
                                    "path": str(insert_path),
                                    "scale": first_insert.get("scale", 1.0),
                                    "anchor": first_insert.get(
                                        "anchor", "middle_center"
                                    ),
                                    "position": first_insert.get(
                                        "position", {"x": "0", "y": "0"}
                                    ),
                                }
                            )
                            static_insert_in_base = True
                        elif insert_path.suffix.lower() in [
                            ".mp4",
                            ".mov",
                            ".webm",
                            ".avi",
                            ".mkv",
                        ] and insert_path.exists():
                            try:
                                # シーン内で共通の挿入動画を一度だけ正規化
                                normalized_insert = await normalize_media(
                                    input_path=insert_path,
                                    video_params=self.video_params,
                                    audio_params=self.audio_params,
                                    cache_manager=self.cache_manager,
                                )
                                scene_level_insert_video = normalized_insert
                                logger.info(
                                    f"Scene {scene_id}: pre-normalized common insert video -> {normalized_insert.name}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Scene {scene_id}: failed to pre-normalize common insert video {insert_path.name}: {e}"
                                )
        except Exception as e:
            logger.debug(
                f"Static overlay detection failed on scene {scene_id}: {e}"
            )
        if scene_cp:
            static_overlays = []
            static_char_keys = set()
            static_insert_in_base = False
            scene_level_insert_video = None
        # ベース映像生成の可否を判断
        normalized_bg_path: Optional[Path] = None
        total_lines_in_scene = len(scene.get("lines", []))
        min_lines_for_base = int(
            self.config.get("video", {}).get("scene_base_min_lines", 6)
        )
        should_generate_base = False
        if has_line_bg_override:
            should_generate_base = False
        elif static_overlays:
            should_generate_base = True
        elif is_bg_video and total_lines_in_scene >= min_lines_for_base:
            # 静的オーバーレイは無いが、行数が多い場合はベース生成の方が有利
            should_generate_base = True
        elif (not is_bg_video) and total_lines_in_scene >= 2:
            # 背景が静止画でも行数が複数ある場合は、背景のスケール/ループを一度だけ行う方が有利
            should_generate_base = True

        base_bg_layout = self._resolve_background_layout({})

        if should_generate_base:
            try:
                bg_config_for_base = {
                    "type": "video" if is_bg_video else "image",
                    "path": str(bg_image),
                    "fit": base_bg_layout["fit"],
                    "fill_color": base_bg_layout["fill_color"],
                    "anchor": base_bg_layout["anchor"],
                    "position": dict(base_bg_layout["position"]),
                }
                scene_base_filename = f"scene_base_{scene_id}"
                if static_overlays:
                    scene_base_path = await self.video_renderer.render_scene_base_composited(
                        bg_config_for_base,
                        scene_duration,
                        scene_base_filename,
                        static_overlays,
                    )
                    # ベースに取り込んだ静的オーバーレイの種類は per-line で個別に除外処理
                else:
                    shared_base_key_data = {
                        "type": "shared_scene_base",
                        "version": "20260502_v1",
                        "background_config": bg_config_for_base,
                        "duration": round(float(scene_duration), 3),
                        "video_params": self.video_params.__dict__,
                        "audio_params": self.audio_params.__dict__,
                        "hw_kind": self.hw_kind,
                    }

                    async def shared_base_creator(output_path: Path) -> Path:
                        return await self.video_renderer.render_scene_base(
                            bg_config_for_base,
                            scene_duration,
                            output_path.stem,
                        )

                    scene_base_path = await self.cache_manager.get_or_create(
                        key_data=shared_base_key_data,
                        file_name="scene_base_shared",
                        extension="mp4",
                        creator_func=shared_base_creator,
                    )
                if scene_base_path:
                    logger.info(
                        f"Scene {scene_id}: generated base with {len(static_overlays)} static overlay(s) -> {scene_base_path.name}"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to generate scene base for scene {scene_id}: {e}"
                )
                # フォールバック: 動画背景なら従来のループ生成を試みる
                if is_bg_video:
                    try:
                        normalized_bg_path = await normalize_media(
                            input_path=Path(bg_image),
                            video_params=self.video_params,
                            audio_params=self.audio_params,
                            cache_manager=self.cache_manager,
                            fit_mode=base_bg_layout["fit"],
                            fill_color=base_bg_layout["fill_color"],
                            anchor=base_bg_layout["anchor"],
                            position=base_bg_layout["position"],
                            scale_flags=self.video_renderer.scale_flags,
                        )
                        scene_base_path = await self.video_renderer.render_looped_background_video(
                            str(normalized_bg_path),
                            scene_duration,
                            f"scene_bg_{scene_id}",
                            fit_mode=base_bg_layout["fit"],
                            fill_color=base_bg_layout["fill_color"],
                            anchor=base_bg_layout["anchor"],
                            position=base_bg_layout["position"],
                        )
                        if scene_base_path:
                            logger.debug(
                                f"Fallback generated looped background -> {scene_base_path.name}"
                            )
                    except Exception as e2:
                        logger.warning(
                            f"Fallback looped BG generation also failed for scene {scene_id}: {e2}"
                        )
        else:
            # ベース生成をスキップ。動画背景はシーン単位で一度だけ正規化して各行へ伝搬
            if is_bg_video:
                try:
                    normalized_bg_path = await normalize_media(
                        input_path=Path(bg_image),
                        video_params=self.video_params,
                        audio_params=self.audio_params,
                        cache_manager=self.cache_manager,
                        fit_mode=base_bg_layout["fit"],
                        fill_color=base_bg_layout["fill_color"],
                        anchor=base_bg_layout["anchor"],
                        position=base_bg_layout["position"],
                        scale_flags=self.video_renderer.scale_flags,
                    )
                    logger.info(
                        "Scene %s: skipping base generation (static_overlays=%d, lines=%d < threshold=%d). Using pre-normalized background.",
                        scene_id,
                        len(static_overlays),
                        total_lines_in_scene,
                        min_lines_for_base,
                    )
                except Exception as e:
                    logger.warning(
                        "Scene %s: background pre-normalization failed (%s). Proceeding as-is without base.",
                        scene_id,
                        e,
                    )

        # 連続行で静的レイヤが不変な“ラン”のベース（行ブロック前処理）を検討
        run_bases: List[Dict[str, Any]] = []
        if scene_base_path is None and not scene_cp and not has_line_bg_override:
            try:
                talk_lines2 = [
                    l
                    for l in scene.get("lines", [])
                    if not ("wait" in l or l.get("type") == "wait")
                ]
                if talk_lines2:
                    def _norm_char_entries(line: Dict[str, Any]) -> Dict[tuple, Dict[str, Any]]:
                        entries: Dict[tuple, Dict[str, Any]] = {}
                        for ch in line.get("characters", []) or []:
                            if not ch.get("visible", False):
                                continue
                            name = ch.get("name")
                            expr = ch.get("expression", "default")
                            try:
                                scale = round(float(ch.get("scale", 1.0)), 2)
                            except Exception:
                                scale = 1.0
                            anchor = str(ch.get("anchor", "bottom_center")).lower()
                            pos_raw = ch.get("position", {"x": "0", "y": "0"}) or {}
                            def _q(v):
                                try:
                                    return f"{float(v):.2f}"
                                except Exception:
                                    return str(v)
                            pos = {"x": _q(pos_raw.get("x", "0")), "y": _q(pos_raw.get("y", "0"))}
                            key = (
                                name,
                                expr,
                                float(scale),
                                str(anchor),
                                str(pos.get("x", "0")),
                                str(pos.get("y", "0")),
                            )
                            base_dir = Path(f"assets/characters/{name}")
                            for c in [
                                base_dir / expr / "base.png",
                                base_dir / f"{expr}.png",
                                base_dir / "default" / "base.png",
                                base_dir / "default.png",
                            ]:
                                try:
                                    if c.exists():
                                        entries[key] = {
                                            "path": str(c),
                                            "scale": scale,
                                            "anchor": anchor,
                                            "position": {"x": pos.get("x", "0"), "y": pos.get("y", "0")},
                                        }
                                        break
                                except Exception:
                                    pass
                        return entries

                    def _insert_image_overlay(line: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                        ins = line.get("insert") or {}
                        p = ins.get("path")
                        if not p:
                            return None
                        sp = Path(p)
                        if sp.exists() and sp.suffix.lower() not in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
                            return {
                                "path": str(sp.resolve()),
                                "scale": float(ins.get("scale", 1.0) or 1.0),
                                "anchor": str(ins.get("anchor", "middle_center")),
                                "position": (ins.get("position") or {"x": "0", "y": "0"}),
                            }
                        return None

                    maps = [_norm_char_entries(l) for l in talk_lines2]
                    run_start: Optional[int] = None
                    run_sig = None
                    for i, m in enumerate(maps):
                        sig_keys = tuple(sorted(m.keys()))
                        ov_ins = _insert_image_overlay(talk_lines2[i])
                        sig = (sig_keys, ov_ins and (ov_ins.get("path"), ov_ins.get("scale"), ov_ins.get("anchor"), (ov_ins.get("position") or {}).get("x"), (ov_ins.get("position") or {}).get("y")))
                        if run_start is None:
                            run_start = i
                            run_sig = sig
                            continue
                        if sig != run_sig:
                            if run_start is not None and (i - run_start) >= 2 and sig_keys:
                                run_end = i - 1
                                overlays: List[Dict[str, Any]] = [maps[run_start][k] for k in tuple(sorted(maps[run_start].keys()))]
                                if ov_ins:
                                    overlays.append(ov_ins)
                                # ランの長さ
                                dur = 0.0
                                for li in range(run_start, run_end + 1):
                                    lid = f"{scene_id}_{li + 1}"
                                    dur += float(line_data_map[lid]["duration"])  # type: ignore
                                try:
                                    base_path = await self.video_renderer.render_scene_base_composited(
                                        {"type": "video" if is_bg_video else "image", "path": str(bg_image)},
                                        dur,
                                        f"scene_base_{scene_id}_run_{run_start+1}_{run_end+1}",
                                        overlays,
                                    )
                                    run_bases.append({
                                        "start": run_start + 1,
                                        "end": run_end + 1,
                                        "path": base_path,
                                        "char_keys": set(tuple(sorted(maps[run_start].keys()))),
                                        "has_insert_image": bool(ov_ins),
                                        "offsets": None,
                                    })
                                except Exception as e:
                                    logger.debug("Run-base generation failed: %s", e)
                            run_start = i
                            run_sig = sig
                    # 末尾ラン
                    i = len(maps)
                    if run_start is not None and (i - run_start) >= 2 and tuple(sorted(maps[run_start].keys())):
                        run_end = i - 1
                        ov_ins0 = _insert_image_overlay(talk_lines2[run_start])
                        overlays = [maps[run_start][k] for k in tuple(sorted(maps[run_start].keys()))]
                        if ov_ins0:
                            overlays.append(ov_ins0)
                        dur = 0.0
                        for li in range(run_start, run_end + 1):
                            lid = f"{scene_id}_{li + 1}"
                            dur += float(line_data_map[lid]["duration"])  # type: ignore
                        try:
                            base_path = await self.video_renderer.render_scene_base_composited(
                                {"type": "video" if is_bg_video else "image", "path": str(bg_image)},
                                dur,
                                f"scene_base_{scene_id}_run_{run_start+1}_{run_end+1}",
                                overlays,
                            )
                            run_bases.append({
                                "start": run_start + 1,
                                "end": run_end + 1,
                                "path": base_path,
                                "char_keys": set(tuple(sorted(maps[run_start].keys()))),
                                "has_insert_image": bool(ov_ins0),
                                "offsets": None,
                            })
                        except Exception as e:
                            logger.debug("Run-base generation failed (tail): %s", e)
            except Exception as e:
                logger.debug("Run-base detection skipped: scene=%s err=%s", scene_id, e)

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
                line_id = f"{scene_id}_{idx}"
                line_data = line_data_map[line_id]
                duration = line_data["duration"]
                pre_dur = float(line_data.get("pre_duration", 0.0))
                line_config = line_data["line_config"]
                bg_layout = self._resolve_background_layout(line_config)
                line_bg_image = self._resolve_background_source(line_config, bg_image)
                if not line_bg_image:
                    raise PipelineError(
                        f"Background is not defined for scene '{scene_id}', line {idx}."
                    )
                line_is_bg_video = (
                    Path(line_bg_image).suffix.lower() in self.video_extensions
                )
                uses_scene_background = line_bg_image == bg_image

                # シーンベース or 連続ランのベースがあればそれを使用
                run_base = None
                for rb in run_bases or []:
                    if rb["start"] <= idx <= rb["end"]:
                        run_base = rb
                        break
                if (
                    uses_scene_background
                    and scene_base_path is not None
                    and scene_base_path.exists()
                ):
                    background_config = {
                        "type": "video",
                        "path": str(scene_base_path),
                        "start_time": start_time_by_idx[idx],
                        "normalized": True,  # 正規化済み（ベース作成時）
                        "pre_scaled": True,  # width/height/fps 済み
                        "fit": bg_layout["fit"],
                        "fill_color": bg_layout["fill_color"],
                        "anchor": bg_layout["anchor"],
                        "position": dict(bg_layout["position"]),
                    }
                elif (
                    uses_scene_background
                    and run_base is not None
                    and Path(run_base["path"]).exists()
                ):
                    # ラン内でのオフセットを算出（キャッシュ）
                    if run_base.get("offsets") is None:
                        offs = {}
                        acc = 0.0
                        for li in range(run_base["start"], run_base["end"] + 1):
                            offs[li] = acc
                            lid2 = f"{scene_id}_{li}"
                            acc += float(line_data_map[lid2]["duration"])  # type: ignore
                        run_base["offsets"] = offs
                    background_config = {
                        "type": "video",
                        "path": str(run_base["path"]),
                        "start_time": float(run_base["offsets"][idx]),
                        "normalized": True,
                        "pre_scaled": True,
                        "fit": bg_layout["fit"],
                        "fill_color": bg_layout["fill_color"],
                        "anchor": bg_layout["anchor"],
                        "position": dict(bg_layout["position"]),
                    }
                else:
                    # フォールバック（従来動作）: ベースなしで個別処理
                    if line_is_bg_video:
                        # シーン単位で正規化済みなら二重スケールを回避
                        if uses_scene_background and normalized_bg_path is not None and Path(
                            normalized_bg_path
                        ).exists():
                            background_config = {
                                "type": "video",
                                "path": str(normalized_bg_path),
                                "start_time": start_time_by_idx[idx],
                                "normalized": True,
                                "pre_scaled": True,
                                "fit": bg_layout["fit"],
                                "fill_color": bg_layout["fill_color"],
                                "anchor": bg_layout["anchor"],
                                "position": dict(bg_layout["position"]),
                            }
                        else:
                            background_config = {
                                "type": "video",
                                "path": str(line_bg_image),
                                "start_time": start_time_by_idx[idx],
                                "fit": bg_layout["fit"],
                                "fill_color": bg_layout["fill_color"],
                                "anchor": bg_layout["anchor"],
                                "position": dict(bg_layout["position"]),
                            }
                    else:
                        background_config = {
                            "type": "image",
                            "path": str(line_bg_image),
                            "start_time": start_time_by_idx[idx],
                            "fit": bg_layout["fit"],
                            "fill_color": bg_layout["fill_color"],
                            "anchor": bg_layout["anchor"],
                            "position": dict(bg_layout["position"]),
                        }

                video_filter = line_config.get("video_filter") or self.scene.get(
                    "video_filter"
                )
                if video_filter:
                    background_config["video_filter"] = video_filter

                if line_data["type"] == "image_layer":
                    results[idx - 1] = None
                    return

                if line_data["type"] == "wait":
                    logger.debug(
                        f"Rendering wait clip for {duration}s (Scene '{scene_id}', Line {idx})"
                    )
                    line_image_layers = image_layers_by_line.get(idx, [])
                    wait_cache_data = {
                        "type": "wait",
                        "duration": duration,
                        "bg_image_path": line_bg_image,
                        "is_bg_video": line_is_bg_video,
                        "start_time": start_time_by_idx[idx],
                        "video_config": self.config.get("video", {}),
                        "line_config": line_config,
                        "image_layer_overlays": line_image_layers,
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
                text = line_data["text"]
                audio_path = line_data["audio_path"]
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
                if static_char_keys or (run_base and run_base.get("char_keys")):
                    eff_chars: List[Dict[str, Any]] = []
                    for ch in original_characters:
                        if not ch.get("visible", False):
                            eff_chars.append(ch)
                            continue
                        key = (
                            ch.get("name"),
                            ch.get("expression", "default"),
                            float(ch.get("scale", 1.0)),
                            str(ch.get("anchor", "bottom_center")),
                            str((ch.get("position", {}) or {}).get("x", "0")),
                            str((ch.get("position", {}) or {}).get("y", "0")),
                        )
                        if key in static_char_keys or (run_base and key in run_base.get("char_keys", set())):
                            continue
                        eff_chars.append(ch)
                    effective_characters = eff_chars
                else:
                    effective_characters = original_characters

                # ベースに取り込まれていない共通挿入“動画”があれば、事前正規化済みのパスを各行へ伝搬
                if static_insert_in_base or (run_base and run_base.get("has_insert_image")):
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
                line_image_layers = image_layers_by_line.get(idx, [])
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

                async def clip_creator_func(output_path: Path) -> Path:
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
                    return clip_path

                _t0 = _time.time()
                clip_path = await self.cache_manager.get_or_create(
                    key_data=video_cache_data,
                    file_name=line_id,
                    extension="mp4",
                    creator_func=clip_creator_func,
                )
                fg_overlays = await self._resolve_visual_overlays(
                    line,
                    scope_id=line_id,
                )
                if fg_overlays:
                    clip_path = await self.video_renderer.apply_foreground_overlays(
                        clip_path, fg_overlays
                    )
                # Collect lightweight samples for auto-tune
                try:
                    if (
                        self.phase.auto_tune_enabled
                        and not getattr(self.phase, "parallel_scene_rendering", False)
                        and len(self.phase._profile_samples) < self.phase.profile_limit
                    ):
                        # Heuristic: subtitle or visible characters or image insert implies CPU overlay
                        has_subtitle = is_effective_subtitle_text(line_data.get("text"))
                        any_chars = any(
                            (c or {}).get("visible", False)
                            for c in (line.get("characters", []) or [])
                        )
                        ins = line_config.get("insert") or {}
                        ins_path = str(ins.get("path", ""))
                        ins_is_image = ins_path.lower().endswith(
                            (".png", ".jpg", ".jpeg", ".bmp", ".webp")
                        )
                        cpu_overlay = has_subtitle or any_chars or ins_is_image
                        elapsed = _time.time() - _t0
                        self.phase._profile_samples.append(
                            {
                                "cpu_overlay": cpu_overlay,
                                "elapsed": elapsed,
                            }
                        )
                    # Also record full diagnostic sample (independent of profiling caps)
                    try:
                        perf_stats.incr("line_clips")
                        perf_stats.add_ms("video_line_clip_ms", elapsed * 1000.0)
                        self.phase._clip_samples_all.append(
                            {
                                "scene": scene_id,
                                "line": idx,
                                "elapsed": elapsed,
                                "subtitle": has_subtitle,
                                "chars": any_chars,
                                "insert_img": ins_is_image,
                                "is_bg_video": is_bg_video,
                            }
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
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
