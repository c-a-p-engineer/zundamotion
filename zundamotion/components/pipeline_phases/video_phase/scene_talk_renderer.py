"""Talk-line cache payload, clip rendering, and foreground application."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ....exceptions import PipelineError
from .scene_line_context import SceneLineContext
from .scene_talk_plan import SceneTalkPlan


@dataclass(frozen=True)
class TalkRenderOutcome:
    """Rendered path plus timing boundaries used by line metrics."""

    path: Path
    cache_started_at: float
    cache_finished_at: float
    finished_at: float
    creator_started_at: Optional[float]
    creator_finished_at: Optional[float]
    render_ms: float

    @property
    def cache_status(self) -> str:
        return "miss" if self.creator_started_at is not None else "hit"

    @property
    def cache_lookup_ms(self) -> float:
        if self.creator_started_at is not None:
            return max(
                0.0,
                (self.creator_started_at - self.cache_started_at) * 1000.0,
            )
        return max(
            0.0,
            (self.cache_finished_at - self.cache_started_at) * 1000.0,
        )

    @property
    def cache_store_ms(self) -> float:
        if self.creator_finished_at is None:
            return 0.0
        return max(
            0.0,
            (self.cache_finished_at - self.creator_finished_at) * 1000.0,
        )


class SceneTalkRendererMixin:
    """Render one resolved talk line without owning scheduling or metrics."""

    def _build_talk_cache_data(
        self,
        *,
        context: SceneLineContext,
        plan: SceneTalkPlan,
        static_character_keys: Iterable[Any],
        static_insert_in_base: bool,
    ) -> Dict[str, Any]:
        """Build the legacy-compatible talk clip cache payload."""
        audio_cache_key_data = {
            "text": context.text,
            "line_config": context.line_config,
            "voice_config": self.config.get("voice", {}),
        }
        animation_meta = plan.animation_meta
        return {
            "type": "talk",
            "clip_render_version": "20260330_face_overlay_args_v2",
            "audio_cache_key": self.cache_manager._generate_hash(
                audio_cache_key_data
            ),
            "duration": context.duration,
            "audio_delay": context.pre_duration,
            "post_duration": context.post_duration,
            "bg_image_path": context.background_source,
            "is_bg_video": context.background_is_video,
            "start_time": context.scene_start_time,
            "video_config": self.config.get("video", {}),
            "bgm_config": self.config.get("bgm", {}),
            "insert_config": plan.effective_insert,
            "image_layer_overlays": list(context.image_layer_overlays),
            "extra_audio_overlays": list(context.extra_audio_overlays),
            "static_chars_in_base": bool(static_character_keys),
            "static_insert_in_base": static_insert_in_base,
            "hw_kind": self.hw_kind,
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
            "lip_eye_version": "v2",
            "face_anim_enabled": bool(plan.face_animations),
            "mouth_fps": animation_meta.get("mouth_fps"),
            "thr_half": animation_meta.get("thr_half"),
            "thr_open": animation_meta.get("thr_open"),
            "blink_min_interval": animation_meta.get("blink_min_interval"),
            "blink_max_interval": animation_meta.get("blink_max_interval"),
            "blink_close_frames": animation_meta.get("blink_close_frames"),
            "screen_effects": context.line_config.get("screen_effects"),
            "background_effects": context.line_config.get(
                "background_effects"
            ),
            "background_layout": context.background_layout,
            "video_filter": context.background_config.get("video_filter"),
        }

    async def _render_talk_line(
        self,
        *,
        context: SceneLineContext,
        plan: SceneTalkPlan,
        static_character_keys: Iterable[Any],
        static_insert_in_base: bool,
    ) -> TalkRenderOutcome:
        cache_data = self._build_talk_cache_data(
            context=context,
            plan=plan,
            static_character_keys=static_character_keys,
            static_insert_in_base=static_insert_in_base,
        )
        creator_started: Optional[float] = None
        creator_finished: Optional[float] = None
        render_ms = 0.0

        async def creator(output_path: Path) -> Path:
            nonlocal creator_started, creator_finished, render_ms
            creator_started = time.perf_counter()
            clip_path = await self.video_renderer.render_clip(
                audio_path=context.audio_path,
                duration=context.duration,
                background_config=context.background_config,
                characters_config=list(plan.effective_characters),
                output_filename=output_path.stem,
                subtitle_text=None,
                subtitle_line_config=context.line_config,
                insert_config=plan.effective_insert,
                image_layer_overlays=list(context.image_layer_overlays),
                extra_audio_overlays=list(context.extra_audio_overlays),
                background_effects=context.line_config.get(
                    "background_effects"
                ),
                screen_effects=context.line_config.get("screen_effects"),
                face_anim=list(plan.face_animations),
                audio_delay=context.pre_duration,
                _force_cpu=bool(context.image_layer_overlays),
            )
            if clip_path is None:
                raise PipelineError(
                    f"Clip rendering failed for line: {context.line_id}"
                )
            creator_finished = time.perf_counter()
            render_ms = (creator_finished - creator_started) * 1000.0
            return Path(clip_path)

        cache_started = time.perf_counter()
        clip_path = await self.cache_manager.get_or_create(
            key_data=cache_data,
            file_name=context.line_id,
            extension="mp4",
            creator_func=creator,
        )
        cache_finished = time.perf_counter()

        foreground_overlays = await self._resolve_visual_overlays(
            context.visual_container,
            scope_id=context.line_id,
        )
        if foreground_overlays:
            clip_path = await self.video_renderer.apply_foreground_overlays(
                Path(clip_path),
                foreground_overlays,
            )
        finished = time.perf_counter()
        return TalkRenderOutcome(
            path=Path(clip_path),
            cache_started_at=cache_started,
            cache_finished_at=cache_finished,
            finished_at=finished,
            creator_started_at=creator_started,
            creator_finished_at=creator_finished,
            render_ms=render_ms,
        )
