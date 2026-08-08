import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from zundamotion.cache import CacheManager
from zundamotion.components.video import VideoRenderer
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_capabilities import (
    get_hw_encoder_kind_for_video_params,
    get_ffmpeg_version,
)
from zundamotion.utils.ffmpeg_hw import get_hw_filter_mode, set_hw_filter_mode
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams, resolve_media_params
from zundamotion.utils.logger import logger, time_log

from .character_render_state import (
    SCENE_STATE_RESOLUTION_VERSION,
    character_state_fingerprint,
    resolve_character_render_state,
    static_character_entry,
)
from .execution import VideoPhaseExecutionMixin


class VideoPhase(VideoPhaseExecutionMixin):
    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
        hw_kind: Optional[str],
        video_params: VideoParams,
        audio_params: AudioParams,
        clip_workers: Optional[int] = None,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.jobs = jobs
        self.hw_kind = hw_kind
        self.video_params = video_params
        self.audio_params = audio_params

        self.video_extensions = self.config.get("system", {}).get(
            "video_extensions",
            [".mp4", ".mov", ".webm", ".avi", ".mkv"],
        )
        if isinstance(clip_workers, int) and clip_workers >= 1:
            self.clip_workers = clip_workers
        else:
            self.clip_workers = self._determine_clip_workers(jobs, self.hw_kind)
        vcfg = self.config.get("video", {}) if isinstance(self.config, dict) else {}
        try:
            self.profile_limit = int(vcfg.get("profile_first_clips", 4))
        except Exception:
            self.profile_limit = 4
        self.auto_tune_enabled = bool(vcfg.get("auto_tune", True))
        self._profile_samples: List[Dict[str, Any]] = []
        self._retuned = False
        self.parallel_scene_rendering = False
        self.scene_workers = self._determine_scene_workers(
            vcfg, self.hw_kind, self.clip_workers
        )
        self._clip_samples_all: List[Dict[str, Any]] = []

    @staticmethod
    def _determine_clip_workers(jobs: str, hw_kind: Optional[str]) -> int:
        """決定的な並列度を返す。"""
        try:
            filter_mode = get_hw_filter_mode()
            cpu_filters_effective = filter_mode == "cpu"

            if jobs is None:
                base = max(1, (os.cpu_count() or 2) // 2)
                if cpu_filters_effective:
                    return min(2, max(1, base))
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            normalized_jobs = jobs.strip().lower()
            if normalized_jobs in ("0", "auto"):
                base = max(2, (os.cpu_count() or 2) // 2)
                if cpu_filters_effective:
                    return min(2, max(1, base))
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            value = int(normalized_jobs)
            if value <= 0:
                base = max(2, (os.cpu_count() or 2) // 2)
                if cpu_filters_effective:
                    return min(2, max(1, base))
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            decided = max(1, min(value, os.cpu_count() or value))
            if hw_kind == "nvenc" and not cpu_filters_effective:
                return min(2, decided)
            return decided
        except Exception:
            return 1 if hw_kind == "nvenc" else 2

    @staticmethod
    def _determine_scene_workers(
        video_cfg: Dict[str, Any],
        hw_kind: Optional[str],
        clip_workers: int,
    ) -> int:
        raw = os.getenv(
            "ZUNDAMOTION_SCENE_WORKERS",
            video_cfg.get("scene_workers", "1"),
        )
        try:
            if isinstance(raw, str):
                normalized = raw.strip().lower()
                if normalized in {"", "0", "auto"}:
                    cpu_count = os.cpu_count() or 2
                    if hw_kind == "nvenc":
                        return 1
                    spare = max(1, cpu_count // max(1, clip_workers))
                    return max(1, min(2, spare))
                return max(1, int(normalized))
            return max(1, int(raw))
        except Exception:
            return 1

    @staticmethod
    def _resolve_effective_hw_kind(
        hw_encoder: str,
        hw_kind: Optional[str],
        filter_mode: str,
    ) -> Optional[str]:
        """Return encoder kind independently from the selected filter backend."""
        return hw_kind

    @classmethod
    async def create(
        cls,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
        hw_encoder: str = "auto",
        *,
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
    ):
        hw_kind = await get_hw_encoder_kind_for_video_params(hw_encoder=hw_encoder)
        hint_path = cache_manager.cache_dir / "autotune_hint.json"
        try:
            import json as _json

            if hint_path.exists():
                with open(hint_path, "r", encoding="utf-8") as hint_file:
                    hint = _json.load(hint_file)
                decided = str(hint.get("decided_mode", "auto")).lower()
                hint_ffmpeg = str(hint.get("ffmpeg", ""))
                hint_hw = str(hint.get("hw_kind", ""))
                current_ffmpeg = await get_ffmpeg_version()
                current_hw = hw_kind
                outdated = False
                try:
                    if hint_ffmpeg and current_ffmpeg and hint_ffmpeg != current_ffmpeg:
                        outdated = True
                    if hint_hw and current_hw and hint_hw != current_hw:
                        outdated = True
                except Exception:
                    outdated = False
                if outdated:
                    logger.info(
                        "[AutoTune] Ignoring outdated hint (ffmpeg:%s->%s, hw:%s->%s)",
                        hint_ffmpeg or "-",
                        current_ffmpeg or "-",
                        hint_hw or "-",
                        current_hw or "-",
                    )
                elif decided in {"cpu", "cuda", "auto"} and decided == "cpu":
                    try:
                        set_hw_filter_mode("cpu")
                        logger.info(
                            "[AutoTune] Loaded hint: forcing HW filter mode to 'cpu'."
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        effective_hw_kind = cls._resolve_effective_hw_kind(
            hw_encoder, hw_kind, get_hw_filter_mode()
        )
        if effective_hw_kind != hw_kind:
            logger.info(
                "[AutoTune] Adjusting hardware encoder kind: %s -> %s",
                hw_kind,
                effective_hw_kind,
            )
            hw_kind = effective_hw_kind

        if video_params is None or audio_params is None:
            resolved_video_params, resolved_audio_params = resolve_media_params(config)
            video_params = video_params or resolved_video_params
            audio_params = audio_params or resolved_audio_params

        pre_clip_workers = cls._determine_clip_workers(jobs, hw_kind)
        video_renderer = await VideoRenderer.create(
            config,
            temp_dir,
            cache_manager,
            jobs,
            hw_kind=hw_kind,
            video_params=video_params,
            audio_params=audio_params,
            hw_encoder=hw_encoder,
            clip_workers=pre_clip_workers,
        )
        instance = cls(
            config,
            temp_dir,
            cache_manager,
            jobs,
            hw_kind,
            video_params,
            audio_params,
            clip_workers=pre_clip_workers,
        )
        instance.video_renderer = video_renderer
        return instance

    def _generate_scene_hash(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        """Build the scene cache fingerprint payload."""
        defaults = self.config.get("defaults", {}) or {}
        character_config = self.config.get("characters", {}) or {}
        character_states = []
        for line in scene.get("lines", []) or []:
            character_states.append(
                [
                    character_state_fingerprint(
                        resolve_character_render_state(character, character_config)
                    )
                    for character in (line.get("characters", []) or [])
                    if isinstance(character, dict)
                ]
            )
        return {
            "scene_state_resolution_version": SCENE_STATE_RESOLUTION_VERSION,
            "id": scene.get("id"),
            "lines": scene.get("lines", []),
            "items": scene.get("items", []),
            "bg": scene.get("bg"),
            "characters_persist": bool(
                scene.get("characters_persist", defaults.get("characters_persist", False))
            ),
            "background_persist": bool(
                scene.get("background_persist", defaults.get("background_persist", False))
            ),
            "default_characters": defaults.get("characters", {}),
            "character_render_defaults": {
                "default_scale": character_config.get("default_scale", 1.0),
                "default_anchor": character_config.get("default_anchor", "bottom_center"),
            },
            "character_render_states": character_states,
            "character_defaults": scene.get("character_defaults"),
            "video_filter": scene.get("video_filter"),
            "badge": scene.get("badge"),
            "badges": scene.get("badges"),
            "fg_overlays": scene.get("fg_overlays"),
            "voice_config": self.config.get("voice", {}),
            "video_config": self.config.get("video", {}),
            "subtitle_config": self.config.get("subtitle", {}),
            "bgm_config": self.config.get("bgm", {}),
            "background_default": self.config.get("background", {}).get("default"),
            "transition_config": scene.get("transition"),
            "hw_kind": self.hw_kind,
            "video_params": self.video_params.__dict__,
            "audio_params": self.audio_params.__dict__,
        }

    def _norm_char_entries(self, line: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Extract static character overlay entries from a line configuration."""
        entries: Dict[str, Dict[str, Any]] = {}
        for character in line.get("characters", []) or []:
            if not isinstance(character, dict):
                continue
            entry = static_character_entry(
                character, self.config.get("characters", {}) or {}
            )
            if entry is not None:
                key, overlay = entry
                entries[key] = overlay
        return entries

    @staticmethod
    def _scene_is_overlay_heavy(scene: Dict[str, Any]) -> bool:
        if scene.get("fg_overlays"):
            return True
        for line in scene.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            if line.get("fg_overlays") or line.get("image_layers"):
                return True
            if any(
                isinstance(character, dict) and character.get("visible", False)
                for character in (line.get("characters", []) or [])
            ):
                return True
            insert_cfg = line.get("insert") or {}
            insert_path = str(insert_cfg.get("path", "")).lower()
            if insert_path.endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
                return True
            if line.get("background_effects") or line.get("screen_effects"):
                return True
        return False

    def _apply_initial_worker_backoff(self, scenes: List[Dict[str, Any]]) -> None:
        if self.clip_workers <= 2:
            return
        jobs_mode = str(self.jobs or "").strip().lower()
        if jobs_mode not in {"", "0", "auto"}:
            return
        try:
            if self.hw_kind is None:
                reason = "cpu_encoder"
            elif get_hw_filter_mode() == "cpu":
                reason = "global_cpu_filter_mode"
            else:
                heavy_scenes = sum(
                    1 for scene in scenes if self._scene_is_overlay_heavy(scene)
                )
                if heavy_scenes <= 0:
                    return
                reason = f"overlay_heavy_scenes={heavy_scenes}/{len(scenes) or 1}"
            previous_workers = self.clip_workers
            self.clip_workers = 2
            try:
                self.video_renderer.clip_workers = self.clip_workers
            except Exception:
                pass
            logger.info(
                "VideoPhase: reducing clip_workers %s -> %s (%s)",
                previous_workers,
                self.clip_workers,
                reason,
            )
        except Exception:
            return

    @time_log(logger)
    async def run(
        self,
        scenes: List[Dict[str, Any]],
        line_data_map: Dict[str, Dict[str, Any]],
        timeline: Timeline,
    ) -> List[Path]:
        """Phase 2: render video clips for each scene."""
        return await self._run_video_phase(scenes, line_data_map, timeline)
