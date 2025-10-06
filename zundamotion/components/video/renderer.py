# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...cache import CacheManager
from ...utils.ffmpeg_params import AudioParams, VideoParams
from ...utils.ffmpeg_hw import get_hw_filter_mode, set_hw_filter_mode
from ...utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async  # 互換用エクスポート
from ...utils.ffmpeg_ops import concat_videos_copy
from ...utils.ffmpeg_capabilities import (
    has_cuda_filters,
    smoke_test_cuda_filters,
    smoke_test_cuda_scale_only,
    smoke_test_opencl_scale_only,
    get_preferred_cuda_scale_filter,
    has_gpu_scale_filters,
    get_filter_diagnostics,
)
from ..subtitles import SubtitleGenerator
from .clip_renderer import render_clip as render_clip_task
from .scene_renderer import (
    render_scene_base as render_scene_base_task,
    render_scene_base_composited as render_scene_base_composited_task,
    render_wait_clip as render_wait_clip_task,
    render_looped_background_video as render_looped_background_video_task,
)
from .face_overlay_cache import FaceOverlayCache
from .overlays import OverlayMixin
from .threading import build_ffmpeg_thread_flags
from ...utils.logger import logger


class VideoRenderer(OverlayMixin):
    """FFmpegを用いて動画を合成するレンダラー。"""

    def __init__(
        self,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str = "0",
        hw_kind: Optional[str] = None,
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
        has_cuda_filters: bool = False,
        clip_workers: Optional[int] = None,
    ):
        self.config = config
        self.temp_dir = temp_dir
        self.cache_manager = cache_manager
        self.video_config = config.get("video", {})
        self.bgm_config = config.get("bgm", {})
        self.jobs = jobs
        self.ffmpeg_path = "ffmpeg"  # PATH 前提

        self.hw_kind = hw_kind
        self.video_params = video_params or VideoParams()
        self.audio_params = audio_params or AudioParams()
        self.has_cuda_filters = has_cuda_filters
        self.has_gpu_scale: bool = False
        # Whether GPU scale-only path is confirmed safe via smoke test
        self.cuda_scale_only_ok: bool = False
        # If scale-only is allowed, which backend to use: 'cuda' | 'opencl'
        self.scale_only_backend: Optional[str] = None
        # GPU overlay backend: 'cuda' | 'opencl' | None (cpu)
        self.gpu_overlay_backend: Optional[str] = None
        # 並列クリップ数（VideoPhase 側の決定を受け取る）
        self.clip_workers = max(1, int(clip_workers)) if clip_workers else 1
        # Experimental flag: allow GPU overlays even with RGBA inputs
        self.gpu_overlay_experimental = bool(
            config.get("video", {}).get("gpu_overlay_experimental", False)
        )
        # Preferred GPU scaler ("scale_cuda" or fallback "scale_npp")
        self.scale_filter = "scale_cuda"
        # Allow OpenCL overlays even when global HW filter mode is 'cpu'
        self.allow_opencl_overlay_in_cpu_mode = bool(
            config.get("video", {}).get("allow_opencl_overlay_in_cpu_mode", False)
        )
        # Subtitle generator (used to build overlay snippet and PNG input)
        self.subtitle_gen = SubtitleGenerator(self.config, self.cache_manager)
        # Face overlay preprocessor/cache
        self.face_cache = FaceOverlayCache(self.cache_manager)
        # Path usage counters for diagnostics
        self.path_counters: Dict[str, int] = {
            "cuda_overlay": 0,
            "opencl_overlay": 0,
            "gpu_scale_only": 0,
            "cpu": 0,
        }
        # CPU scaler flags and fps filter policy (quality-aware)
        try:
            vcfg = config.get("video", {}) or {}
            self.scale_flags: str = str(vcfg.get("scale_flags", "lanczos"))
            self.apply_fps_filter: bool = bool(vcfg.get("apply_fps_filter", True))
        except Exception:
            self.scale_flags = "lanczos"
            self.apply_fps_filter = True

        if self.has_cuda_filters:
            logger.info("CUDA filters available: True (scale_cuda/overlay_cuda)")
        else:
            logger.info("CUDA filters available: False (using CPU or alt GPU filters)")
        logger.info(
            "VideoRenderer initialized: hw_kind=%s, clip_workers=%s, hw_filter_mode=%s",
            self.hw_kind,
            self.clip_workers,
            get_hw_filter_mode(),
        )

    @classmethod
    async def create(
        cls,
        config: Dict[str, Any],
        temp_dir: Path,
        cache_manager: CacheManager,
        jobs: str = "0",
        hw_kind: Optional[str] = None,
        video_params: Optional[VideoParams] = None,
        audio_params: Optional[AudioParams] = None,
        clip_workers: Optional[int] = None,
    ):
        ffmpeg_path = config.get("ffmpeg_path", "ffmpeg")
        vcfg = config.get("video", {}) if isinstance(config, dict) else {}
        # フィルタ存在チェックに加えて実行スモークテストで確度を上げる
        has_cuda_filters_listed = await has_cuda_filters(ffmpeg_path)
        has_cuda_filters_val = (
            has_cuda_filters_listed and (await smoke_test_cuda_filters(ffmpeg_path))
        )
        # Scale-only capability (allows hybrid GPU scale in CPU overlay mode)
        has_gpu_scale_val = await has_gpu_scale_filters(ffmpeg_path)
        # GPU scale-only smoke (for conditional allow under CPU mode)
        try:
            scale_only_ok = await smoke_test_cuda_scale_only(ffmpeg_path)
        except Exception:
            scale_only_ok = False
        # Try OpenCL as alternative backend when CUDA is not available/disabled
        from ..utils.ffmpeg_capabilities import (
            has_opencl_filters,
            smoke_test_opencl_filters,
        )
        opencl_ok = False
        allow_opencl_cpu = bool(config.get("video", {}).get("allow_opencl_overlay_in_cpu_mode", False))
        if not has_cuda_filters_val and (get_hw_filter_mode() != "cpu" or allow_opencl_cpu):
            try:
                if await has_opencl_filters(ffmpeg_path):
                    opencl_ok = await smoke_test_opencl_filters(ffmpeg_path)
            except Exception:
                opencl_ok = False
        # GPUスケールフィルタの優先名を決定
        scale_filter = await get_preferred_cuda_scale_filter(ffmpeg_path)
        # Respect global HW filter mode (process-wide backoff)
        # Keep detection result even if global mode is 'cpu' so that
        # hybrid 'GPU scale only' path can still leverage CUDA when allowed
        # (overlay paths will still be disabled by mode checks elsewhere).
        # if get_hw_filter_mode() == "cpu":
        #     has_cuda_filters_val = False
        inst = cls(
            config,
            temp_dir,
            cache_manager,
            jobs,
            hw_kind,
            video_params,
            audio_params,
            has_cuda_filters_val,
            clip_workers=clip_workers,
        )
        try:
            inst.scale_filter = scale_filter or "scale_cuda"
        except Exception:
            inst.scale_filter = "scale_cuda"
        # propagate allow-opencl-in-cpu flag
        try:
            inst.allow_opencl_overlay_in_cpu_mode = allow_opencl_cpu
        except Exception:
            pass
        try:
            inst.has_gpu_scale = bool(has_gpu_scale_val)
        except Exception:
            pass
        try:
            inst.cuda_scale_only_ok = bool(scale_only_ok)
        except Exception:
            pass
        # Decide overlay backend
        if (get_hw_filter_mode() != "cpu") or allow_opencl_cpu:
            if has_cuda_filters_val and hw_kind == "nvenc":
                inst.gpu_overlay_backend = "cuda"
            elif opencl_ok:
                inst.gpu_overlay_backend = "opencl"
        # Decide scale-only backend (allowed also in CPU mode when smoke passed)
        opencl_scale_only_ok = False
        try:
            opencl_scale_only_ok = await smoke_test_opencl_scale_only(ffmpeg_path)
        except Exception:
            opencl_scale_only_ok = False
        if inst.cuda_scale_only_ok:
            inst.scale_only_backend = "cuda"
        elif opencl_scale_only_ok:
            inst.scale_only_backend = "opencl"
        # Aggressive enablement: when CUDA scale filters are present but the
        # conservative smoke test failed, allow scale-only path opportunistically
        # to reduce CPU work. This is guarded by config and still falls back
        # safely via render_clip() retry logic if FFmpeg errors occur.
        try:
            aggressive = bool(vcfg.get("gpu_scale_aggressive", False))
        except Exception:
            aggressive = False
        if (
            aggressive
            and not inst.cuda_scale_only_ok
            and has_gpu_scale_val
            and inst.scale_only_backend is None
        ):
            inst.cuda_scale_only_ok = True
            inst.scale_only_backend = "cuda"
            try:
                logger.info(
                    "[Filters] Enabling aggressive GPU scale-only path (smoke test failed, filters present)."
                )
            except Exception:
                pass
        logger.info(
            "[Filters] GPU overlay backend=%s (cuda=%s, opencl_ok=%s, scale_only=%s, scale_only_smoke_ok=%s)",
            inst.gpu_overlay_backend or "none",
            has_cuda_filters_val,
            opencl_ok,
            has_gpu_scale_val,
            scale_only_ok,
        )
        # Emit a one-shot diagnostics table for filters/smokes
        try:
            diag = await get_filter_diagnostics(ffmpeg_path)
            pres = diag.get("present", {})
            smo = diag.get("smokes", {})
            logger.info(
                "[FilterDiag] present(cu:ov=%s,sc=%s,npp=%s,up=%s; ocl:ov=%s,sc=%s,up=%s) smokes(cu=%s, cu_scale_only=%s, ocl=%s, ocl_scale_only=%s)",
                int(bool(pres.get("overlay_cuda"))),
                int(bool(pres.get("scale_cuda"))),
                int(bool(pres.get("scale_npp"))),
                int(bool(pres.get("hwupload_cuda"))),
                int(bool(pres.get("overlay_opencl"))),
                int(bool(pres.get("scale_opencl"))),
                int(bool(pres.get("hwupload"))),
                int(bool(smo.get("cuda_filters"))),
                int(bool(smo.get("cuda_scale_only"))),
                int(bool(smo.get("opencl_filters"))),
                int(bool(smo.get("opencl_scale_only"))),
            )
        except Exception:
            pass
        return inst

    def ffmpeg_thread_flags(self) -> List[str]:
        """FFmpeg向けのスレッド指定を共通ユーティリティで生成する。"""
        return build_ffmpeg_thread_flags(self.jobs, self.clip_workers, self.hw_kind)

    async def render_clip(
        self,
        audio_path: Path,
        duration: float,
        background_config: Dict[str, Any],
        characters_config: List[Dict[str, Any]],
        output_filename: str,
        subtitle_text: Optional[str] = None,
        subtitle_line_config: Optional[Dict[str, Any]] = None,
        insert_config: Optional[Dict[str, Any]] = None,
        screen_effects: Optional[List[Any]] = None,
        subtitle_png_path: Optional[Path] = None,
        face_anim: Optional[Dict[str, Any]] = None,
        _force_cpu: bool = False,
        audio_delay: float = 0.0,
    ) -> Optional[Path]:
        return await render_clip_task(
            renderer=self,
            audio_path=audio_path,
            duration=duration,
            background_config=background_config,
            characters_config=characters_config,
            output_filename=output_filename,
            subtitle_text=subtitle_text,
            subtitle_line_config=subtitle_line_config,
            insert_config=insert_config,
            screen_effects=screen_effects,
            subtitle_png_path=subtitle_png_path,
            face_anim=face_anim,
            _force_cpu=_force_cpu,
            audio_delay=audio_delay,
        )

    # --------------------------
    # 内部ユーティリティ
    # --------------------------
    def _thread_flags(self) -> List[str]:
        """後方互換のためのエイリアス。"""
        return self.ffmpeg_thread_flags()

    # --------------------------
    # クリップ生成（字幕PNG/立ち絵対応）
    # --------------------------

    # --------------------------
    # シーンベース（背景のみ、静的）
    # --------------------------
    async def render_scene_base(
        self,
        background_config: Dict[str, Any],
        duration: float,
        output_filename: str,
    ) -> Path:
        return await render_scene_base_task(
            self,
            background_config=background_config,
            duration=duration,
            output_filename=output_filename,
        )

    async def render_scene_base_composited(
        self,
        background_config: Dict[str, Any],
        duration: float,
        output_filename: str,
        overlays: List[Dict[str, Any]],
    ) -> Path:
        return await render_scene_base_composited_task(
            self,
            background_config=background_config,
            duration=duration,
            output_filename=output_filename,
            overlays=overlays,
        )

    # --------------------------
    # 無音待機クリップ
    # --------------------------
    async def render_wait_clip(
        self,
        duration: float,
        background_config: Dict[str, Any],
        output_filename: str,
        line_config: Dict[str, Any],
    ) -> Optional[Path]:
        return await render_wait_clip_task(
            self,
            duration=duration,
            background_config=background_config,
            output_filename=output_filename,
            line_config=line_config,
        )

    # --------------------------
    # BG動画の指定長ループ
    # --------------------------
    async def render_looped_background_video(
        self, bg_video_path_str: str, duration: float, output_filename: str
    ) -> Path:
        return await render_looped_background_video_task(
            self,
            bg_video_path_str=bg_video_path_str,
            duration=duration,
            output_filename=output_filename,
        )

    # --------------------------
    # -c copy で連結
    # --------------------------
    async def concat_clips(self, clip_paths: List[Path], output_path: str) -> None:
        """
        複数のクリップを -c copy で連結。
        すべての入力に音声/映像が存在し、同一パラメータである前提（本パイプラインの生成物は満たす）。
        """
        if not clip_paths:
            print("[Concat] No clips to concatenate.")
            return

        print(
            f"[Concat] Concatenating {len(clip_paths)} clips -> {output_path} using -c copy."
        )
        try:
            await concat_videos_copy(
                [str(p.resolve()) for p in clip_paths], output_path
            )
        except Exception as e:
            print(f"[Error] -c copy concat failed for {output_path}: {e}")
            raise
