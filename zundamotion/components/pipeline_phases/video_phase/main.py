import asyncio
import hashlib
import json
import os
import time  # Import time module
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm
import sys

from zundamotion.cache import CacheManager
from zundamotion.components.video import VideoRenderer
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_capabilities import (
    get_hw_encoder_kind_for_video_params,  # 追加
    get_ffmpeg_version,
)
from zundamotion.utils.ffmpeg_hw import get_hw_filter_mode
from zundamotion.utils.ffmpeg_ops import normalize_media
from zundamotion.utils.ffmpeg_hw import set_hw_filter_mode  # Auto-tuneでのバックオフに使用
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams, resolve_media_params
from zundamotion.utils.logger import logger, time_log
from .scene_renderer import SceneRenderer
from .character_render_state import (
    SCENE_STATE_RESOLUTION_VERSION,
    character_state_fingerprint,
    resolve_character_render_state,
    static_character_entry,
)

class VideoPhase:
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
        # クリップ並列実行ワーカー数を決定（createで決めた値があればそれを優先）
        if isinstance(clip_workers, int) and clip_workers >= 1:
            self.clip_workers = clip_workers
        else:
            # 実効フィルタ経路がCPUの場合は、NVENC でもCPU向けヒューリスティクスを適用する
            self.clip_workers = self._determine_clip_workers(jobs, self.hw_kind)
        # Auto-tune (profile first N clips then adjust caps/clip_workers)
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
        # Detailed per-line clip timing samples for diagnostics
        self._clip_samples_all: List[Dict[str, Any]] = []

    @staticmethod
    def _determine_clip_workers(jobs: str, hw_kind: Optional[str]) -> int:
        """決定的な並列度を返す。"""
        try:
            import os
            from zundamotion.utils.ffmpeg_hw import get_hw_filter_mode

            # 実効フィルタがCPUかどうか（プロセス全体のバックオフ判定）
            filter_mode = get_hw_filter_mode()
            cpu_filters_effective = filter_mode == "cpu"

            if jobs is None:
                base = max(1, (os.cpu_count() or 2) // 2)
                # CPUフィルタ経路では初期から過剰並列を抑制
                if cpu_filters_effective:
                    return min(2, max(1, base))
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            j = jobs.strip().lower()
            if j in ("0", "auto"):
                base = max(2, (os.cpu_count() or 2) // 2)
                if cpu_filters_effective:
                    return min(2, max(1, base))
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            val = int(j)
            if val <= 0:
                base = max(2, (os.cpu_count() or 2) // 2)
                if cpu_filters_effective:
                    return min(2, max(1, base))
                if hw_kind == "nvenc" and not cpu_filters_effective:
                    return min(2, max(1, base))
                return base
            # 上限はCPU数
            decided = max(1, min(val, os.cpu_count() or val))
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
        """Return encoder kind independently from the selected filter backend.

        CPU filter mode means "do not use GPU filters".  It must not disable
        NVENC itself because CPU overlays + NVENC encoding is the stable fast
        path for PNG subtitles and character mouth overlays.
        """
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
        hw_kind = await get_hw_encoder_kind_for_video_params(
            hw_encoder=hw_encoder
        )
        # AutoTune hint: early backoff（clip_workers 決定前に適用）
        hint_path = cache_manager.cache_dir / "autotune_hint.json"
        try:
            import json as _json
            if hint_path.exists():
                with open(hint_path, "r", encoding="utf-8") as _f:
                    _hint = _json.load(_f)
                decided = str(_hint.get("decided_mode", "auto")).lower()
                hint_ffmpeg = str(_hint.get("ffmpeg", ""))
                hint_hw = str(_hint.get("hw_kind", ""))
                # 現環境シグネチャ
                cur_ffmpeg = await get_ffmpeg_version()
                cur_hw = hw_kind
                # 乖離チェック: ffmpeg版 or ハードウェア種別が変わっていればヒント無効
                outdated = False
                try:
                    if hint_ffmpeg and cur_ffmpeg and hint_ffmpeg != cur_ffmpeg:
                        outdated = True
                    if hint_hw and cur_hw and hint_hw != cur_hw:
                        outdated = True
                except Exception:
                    outdated = False
                if outdated:
                    logger.info(
                        "[AutoTune] Ignoring outdated hint (ffmpeg:%s->%s, hw:%s->%s)",
                        hint_ffmpeg or "-",
                        cur_ffmpeg or "-",
                        hint_hw or "-",
                        cur_hw or "-",
                    )
                else:
                    if decided in {"cpu", "cuda", "auto"} and decided == "cpu":
                        try:
                            set_hw_filter_mode("cpu")
                            logger.info("[AutoTune] Loaded hint: forcing HW filter mode to 'cpu'.")
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

        # jobs/hw_kind から clip_workers を算出して VideoRenderer に伝搬
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
        """Generates a dictionary for scene hash based on its content and relevant config."""
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
            "transition_config": scene.get(
                "transition"
            ),  # Add transition config to hash
            "hw_kind": self.hw_kind,  # 追加
            "video_params": self.video_params.__dict__,  # 追加
            "audio_params": self.audio_params.__dict__,  # 追加
        }

    def _norm_char_entries(self, line: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Extracts static character overlay entries from a line configuration.

        Characters with dynamic enter/leave animations are excluded to avoid
        duplicating them in the scene base. The returned dictionary maps
        normalized character keys to overlay configuration.
        """
        entries: Dict[str, Dict[str, Any]] = {}
        for ch in line.get("characters", []) or []:
            if not isinstance(ch, dict):
                continue
            entry = static_character_entry(ch, self.config.get("characters", {}) or {})
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
                isinstance(ch, dict) and ch.get("visible", False)
                for ch in (line.get("characters", []) or [])
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
            prev_workers = self.clip_workers
            self.clip_workers = 2
            try:
                self.video_renderer.clip_workers = self.clip_workers
            except Exception:
                pass
            logger.info(
                "VideoPhase: reducing clip_workers %s -> %s (%s)",
                prev_workers,
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
        """Phase 2: Render video clips for each scene."""
        start_time = time.time()  # Start timing
        logger.info(
            "VideoPhase started. clip_workers=%s, scene_workers=%s, hw_kind=%s",
            self.clip_workers,
            self.scene_workers,
            self.hw_kind,
        )
        self._apply_initial_worker_backoff(scenes)

        all_clips: List[Path] = []
        bg_default = self.config.get("background", {}).get("default")
        total_scenes = len(scenes)
        self.parallel_scene_rendering = self.scene_workers > 1
        if self.parallel_scene_rendering and self.auto_tune_enabled:
            logger.info(
                "VideoPhase: disabling auto_tune during parallel scene rendering."
            )

        with tqdm(
            total=total_scenes,
            desc="Scene Rendering",
            unit="scene",
            leave=False,
            disable=(os.getenv("TQDM_DISABLE") == "1" or not sys.stderr.isatty()),
        ) as pbar_scenes:
            if self.parallel_scene_rendering:
                sem = asyncio.Semaphore(self.scene_workers)
                scene_results: List[List[Path]] = [[] for _ in scenes]

                async def _render_one(scene_idx: int, scene: Dict[str, Any]) -> None:
                    async with sem:
                        scene_id = scene["id"]
                        scene_hash_data = self._generate_scene_hash(scene)

                        scene_renderer = SceneRenderer(
                            phase=self,
                            scene=scene,
                            scene_hash_data=scene_hash_data,
                            scene_idx=scene_idx,
                            total_scenes=total_scenes,
                            line_data_map=line_data_map,
                            timeline=timeline,
                            pbar_scenes=pbar_scenes,
                        )
                        scene_results[scene_idx] = await scene_renderer.render_scene()

                await asyncio.gather(
                    *(_render_one(scene_idx, scene) for scene_idx, scene in enumerate(scenes))
                )
                for scene_clips in scene_results:
                    all_clips.extend(scene_clips)
            else:
                for scene_idx, scene in enumerate(scenes):
                    scene_id = scene["id"]
                    scene_hash_data = self._generate_scene_hash(scene)

                    scene_renderer = SceneRenderer(
                        phase=self,
                        scene=scene,
                        scene_hash_data=scene_hash_data,
                        scene_idx=scene_idx,
                        total_scenes=total_scenes,
                        line_data_map=line_data_map,
                        timeline=timeline,
                        pbar_scenes=pbar_scenes,
                    )
                    scene_clips = await scene_renderer.render_scene()
                    all_clips.extend(scene_clips)

        # Ensure a clean newline after closing the progress bar
        try:
            tqdm.write("", file=sys.stderr)
        except Exception:
            pass

        end_time = time.time()  # End timing
        duration = end_time - start_time
        logger.info(f"VideoPhase completed in {duration:.2f} seconds.")
        # Diagnostics: Top-N slowest line clips across all scenes
        try:
            if self._clip_samples_all:
                topn = sorted(
                    self._clip_samples_all,
                    key=lambda s: float(s.get("elapsed", 0.0)),
                    reverse=True,
                )[:5]
                logger.info("[Diagnostics] Slowest line clips (top 5):")
                for s in topn:
                    logger.info(
                        "  Scene=%s Line=%s Elapsed=%.2fs subtitle=%s chars=%s insert_img=%s bg_video=%s",
                        s.get("scene"),
                        s.get("line"),
                        float(s.get("elapsed", 0.0)),
                        bool(s.get("subtitle")),
                        bool(s.get("chars")),
                        bool(s.get("insert_img")),
                        bool(s.get("is_bg_video")),
                    )
        except Exception:
            pass

        # Summarize filter path usage counters from renderer if present
        try:
            stats = getattr(self.video_renderer, "path_counters", None)
            if isinstance(stats, dict):
                logger.info(
                    "[Diagnostics] Filter path usage: cuda_overlay=%s, opencl_overlay=%s, gpu_scale_only=%s, cpu=%s",
                    stats.get("cuda_overlay", 0),
                    stats.get("opencl_overlay", 0),
                    stats.get("gpu_scale_only", 0),
                    stats.get("cpu", 0),
                )
        except Exception:
            pass
        try:
            subtitle_stats = getattr(self.video_renderer, "subtitle_overlay_stats", None)
            if isinstance(subtitle_stats, dict):
                logger.info(
                    "[Diagnostics] Subtitle overlay: mode=%s, subtitles=%s, chunks=%s, png_chunk_size=%s, base=%.2fs, layer_attempted=%s, layer_used=%s",
                    subtitle_stats.get("mode", "none"),
                    subtitle_stats.get("subtitles", 0),
                    subtitle_stats.get("chunks", 0),
                    subtitle_stats.get("png_chunk_size"),
                    float(subtitle_stats.get("base_duration") or 0.0),
                    bool(subtitle_stats.get("layer_video_attempted")),
                    bool(subtitle_stats.get("layer_video_used")),
                )
        except Exception:
            pass

        try:
            timeline.resync_with_scene_durations(scenes, line_data_map)
        except Exception as exc:
            logger.warning(
                "VideoPhase: failed to resync timeline with rendered durations: %s",
                exc,
            )

        return all_clips
