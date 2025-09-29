import hashlib
import json
import time  # Import time module
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm
import os
import sys

from zundamotion.cache import CacheManager
from zundamotion.components.video import VideoRenderer
from zundamotion.exceptions import PipelineError
from zundamotion.timeline import Timeline
from zundamotion.utils.ffmpeg_capabilities import (
    get_hw_encoder_kind_for_video_params,  # 追加
    get_ffmpeg_version,
)
from zundamotion.utils.ffmpeg_ops import normalize_media
from zundamotion.utils.ffmpeg_hw import set_hw_filter_mode  # Auto-tuneでのバックオフに使用
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams
from zundamotion.utils.logger import logger, time_log
from .scene_renderer import SceneRenderer

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

    @classmethod
    async def create(
        cls,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str,
    ):
        hw_kind = await get_hw_encoder_kind_for_video_params()
        video_params = VideoParams(
            width=config.get("video", {}).get("width", 1920),
            height=config.get("video", {}).get("height", 1080),
            fps=config.get("video", {}).get("fps", 30),
            pix_fmt=config.get("video", {}).get("pix_fmt", "yuv420p"),
            profile=config.get("video", {}).get("profile", "high"),
            level=config.get("video", {}).get("level", "4.2"),
            preset=config.get("video", {}).get(
                "preset", "p5" if hw_kind == "nvenc" else "veryfast"
            ),
            cq=config.get("video", {}).get("cq", 23),
            crf=config.get("video", {}).get("crf", 23),
        )
        audio_params = AudioParams(
            sample_rate=config.get("video", {}).get("audio_sample_rate", 48000),
            channels=config.get("video", {}).get("audio_channels", 2),
            codec=config.get("video", {}).get("audio_codec", "libmp3lame"),
            bitrate_kbps=config.get("video", {}).get("audio_bitrate_kbps", 192),
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
        return {
            "id": scene.get("id"),
            "lines": scene.get("lines", []),
            "bg": scene.get("bg"),
            "bgm": scene.get("bgm"),
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

    @staticmethod
    def _norm_char_entries(line: Dict[str, Any]) -> Dict[tuple, Dict[str, Any]]:
        """Extracts static character overlay entries from a line configuration.

        Characters with dynamic enter/leave animations are excluded to avoid
        duplicating them in the scene base. The returned dictionary maps
        normalized character keys to overlay configuration.
        """
        entries: Dict[tuple, Dict[str, Any]] = {}
        for ch in line.get("characters", []) or []:
            if not ch.get("visible", False):
                continue
            if ch.get("enter") or ch.get("leave"):
                continue
            name = ch.get("name")
            expr = ch.get("expression", "default")
            try:
                scale = round(float(ch.get("scale", 1.0)), 2)
            except Exception:
                scale = 1.0
            anchor = str(ch.get("anchor", "bottom_center")).lower()
            pos_raw = ch.get("position", {"x": "0", "y": "0"}) or {}

            def _q(v: Any) -> str:
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
            candidates = [
                base_dir / expr / "base.png",  # new: <name>/<expr>/base.png
                base_dir / f"{expr}.png",  # legacy: <name>/{expr}.png
                base_dir / "default" / "base.png",  # new default: <name>/default/base.png
                base_dir / "default.png",  # legacy default: <name>/default.png
            ]
            chosen = None
            for c in candidates:
                try:
                    if c.exists():
                        chosen = c
                        break
                except Exception:
                    pass
            if chosen is None:
                continue
            entries[key] = {
                "path": str(chosen),
                "scale": scale,
                "anchor": anchor,
                "position": {"x": pos.get("x", "0"), "y": pos.get("y", "0")},
            }
        return entries

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
            f"VideoPhase started. clip_workers={self.clip_workers}, hw_kind={self.hw_kind}"
        )

        all_clips: List[Path] = []
        bg_default = self.config.get("background", {}).get("default")
        total_scenes = len(scenes)

        with tqdm(
            total=total_scenes,
            desc="Scene Rendering",
            unit="scene",
            leave=False,
            disable=(os.getenv("TQDM_DISABLE") == "1" or not sys.stderr.isatty()),
        ) as pbar_scenes:
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

        return all_clips
