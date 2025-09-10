# -*- coding: utf-8 -*-
import multiprocessing
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..cache import CacheManager
from ..exceptions import PipelineError  # 追加
from ..utils.ffmpeg_utils import _run_ffmpeg_async  # 追加
from ..utils.ffmpeg_utils import (
        AudioParams,
        VideoParams,
        calculate_overlay_position,
        concat_videos_copy,
        get_media_info,
        get_media_duration,
        has_audio_stream,
        has_cuda_filters,
        smoke_test_cuda_filters,
        smoke_test_cuda_scale_only,
        smoke_test_opencl_scale_only,
        normalize_media,
        get_hw_filter_mode,
        set_hw_filter_mode,
        get_preferred_cuda_scale_filter,
        has_gpu_scale_filters,
        _dump_cuda_diag_once,
        get_profile_flags,
        get_filter_diagnostics,
    )
from .subtitle import SubtitleGenerator
from .face_overlay_cache import FaceOverlayCache
from ..utils.logger import logger


class VideoRenderer:
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
        from ..utils.ffmpeg_utils import has_opencl_filters, smoke_test_opencl_filters
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

    # --------------------------
    # 内部ユーティリティ
    # --------------------------
    def _thread_flags(self) -> List[str]:
        """
        ffmpeg7 向けスレッド指定:
        -threads 0（自動）＋ filter_threads / filter_complex_threads
        既定は物理コア数。ただし安定性のためのオーバーライドをサポート。
        """
        nproc = multiprocessing.cpu_count() or 1

        # Global worker threads for encoders/decoders
        def _auto_threads_for_mode() -> str:
            # CPU フィルタ優勢時は、クリップ並列(self.clip_workers)との過剰競合を避けるため
            # プロセスあたりのスレッド数を抑制（nproc // clip_workers）。
            # NVENC/GPU 経路では FFmpeg の自動スレッド化に委ねる（0）。
            global_mode = get_hw_filter_mode()
            if global_mode == "cpu":
                per_proc = max(1, nproc // max(1, self.clip_workers))
                return str(per_proc)
            # 非CPU（NVENCなど）では 0（自動）
            return "0"

        if self.jobs is None or str(self.jobs).strip().lower() in {"auto", ""}:
            threads = _auto_threads_for_mode()
            logger.info(
                "[Jobs] Auto mode: nproc=%s, clip_workers=%s -> threads=%s",
                nproc,
                self.clip_workers,
                threads,
            )
        else:
            j = str(self.jobs).strip().lower()
            try:
                if j == "0":
                    threads = _auto_threads_for_mode()
                    logger.info(
                        "[Jobs] Auto(0) adjusted: nproc=%s, clip_workers=%s -> threads=%s",
                        nproc,
                        self.clip_workers,
                        threads,
                    )
                else:
                    num_jobs = int(j)
                    if num_jobs <= 0:
                        threads = _auto_threads_for_mode()
                        logger.info(
                            "[Jobs] Non-positive --jobs -> auto adjusted to %s",
                            threads,
                        )
                    else:
                        threads = str(num_jobs)
                        logger.info("[Jobs] Using specified threads=%s", threads)
            except ValueError:
                threads = _auto_threads_for_mode()
                logger.warning(
                    "[Jobs] Invalid --jobs '%s'. Auto adjusted to %s.",
                    self.jobs,
                    threads,
                )

        # Filter thread overrides via env (used for fallback stability)
        ft_override = os.environ.get("FFMPEG_FILTER_THREADS")
        fct_override = os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS")

        # 実効フィルタ経路（プロセス全体のバックオフ判定）
        global_filter_mode = get_hw_filter_mode()

        if ft_override and ft_override.isdigit():
            ft = ft_override
        else:
            # CPU フィルタ経路ではCPU向けヒューリスティクス（= nproc）
            # CUDA フィルタ想定で NVENC の場合は保守的に 1
            if global_filter_mode == "cpu":
                # clip_workers 並列時に filter_threads を割り当て過ぎない
                per_filter_threads = max(1, nproc // max(1, self.clip_workers))
                # デフォルト上限（CPUフィルタ時は小さめ）
                cap = os.environ.get("FFMPEG_FILTER_THREADS_CAP")
                try:
                    cap_i = int(cap) if cap and cap.isdigit() else 4
                except Exception:
                    cap_i = 4
                ft = str(max(1, min(per_filter_threads, cap_i)))
            else:
                ft = "1" if self.hw_kind == "nvenc" else str(nproc)

        if fct_override and fct_override.isdigit():
            fct = fct_override
        else:
            if global_filter_mode == "cpu":
                per_filter_threads = max(1, nproc // max(1, self.clip_workers))
                cap = os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS_CAP")
                try:
                    cap_i = int(cap) if cap and cap.isdigit() else 4
                except Exception:
                    cap_i = 4
                fct = str(max(1, min(per_filter_threads, cap_i)))
            else:
                fct = "1" if self.hw_kind == "nvenc" else str(nproc)

        flags = [
            "-threads",
            threads,
            "-filter_threads",
            ft,
            "-filter_complex_threads",
            fct,
        ]
        logger.info(
            "[FFmpeg Threads] mode=%s, nproc=%s, clip_workers=%s, threads=%s, filter_threads=%s, filter_complex_threads=%s, overrides(ft=%s,fct=%s)",
            get_hw_filter_mode(),
            nproc,
            self.clip_workers,
            threads,
            ft,
            fct,
            os.environ.get("FFMPEG_FILTER_THREADS"),
            os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS"),
        )
        return flags

    # --------------------------
    # クリップ生成（字幕PNG/立ち絵対応）
    # --------------------------
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
        subtitle_png_path: Optional[Path] = None,
        face_anim: Optional[Dict[str, Any]] = None,
        _force_cpu: bool = False,
    ) -> Optional[Path]:
        """
        drawtext 全廃版:
        - 字幕は SubtitleGenerator の GPU/CPU スニペットを使用し、PNG 事前生成入力（-loop 1 -i png）→ overlay
        - 位置/スタイルは line_config の subtitle 設定 + デフォルトを反映
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        import time as _time
        _t0 = _time.time()
        logger.info("[Video] Rendering clip -> %s", output_path.name)

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            *get_profile_flags(),
        ]
        cmd.extend(self._thread_flags())

        # --- Inputs -------------------------------------------------------------
        input_layers: List[Dict[str, Any]] = []

        # 0) Background
        bg_path_str = background_config.get("path")
        if not bg_path_str:
            raise ValueError("Background path is missing.")
        bg_path = Path(bg_path_str)

        if background_config.get("type") == "video":
            try:
                # ループ済みシーンBGなど、既に正規化済みの入力はスキップ
                normalized_hint = bool(background_config.get("normalized", False))
                is_temp_scene_bg = (
                    bg_path.parent.resolve() == self.temp_dir.resolve()
                    and bg_path.name.startswith("scene_bg_")
                )
                should_skip_normalize = normalized_hint or is_temp_scene_bg

                if not should_skip_normalize:
                    # 正規化（失敗時は as-is）
                    try:
                        key_data = {
                            "input_path": str(bg_path.resolve()),
                            "video_params": self.video_params.__dict__,
                            "audio_params": self.audio_params.__dict__,
                        }

                        async def _normalize_bg_creator(temp_output_path: Path) -> Path:
                            return await normalize_media(
                                input_path=bg_path,
                                video_params=self.video_params,
                                audio_params=self.audio_params,
                                cache_manager=self.cache_manager,
                                ffmpeg_path=self.ffmpeg_path,
                            )

                        # cache_manager.get_or_create は Path を返すことを期待
                        bg_path_result = await self.cache_manager.get_or_create(
                            key_data=key_data,
                            file_name="normalized_bg",
                            extension="mp4",
                            creator_func=_normalize_bg_creator,
                        )
                        if bg_path_result is None:
                            raise PipelineError(
                                f"Failed to normalize background video: {bg_path}"
                            )
                        bg_path = bg_path_result
                    except Exception as e:
                        print(
                            f"[Warning] Could not inspect/normalize BG video {bg_path.name}: {e}. Using as-is."
                        )
                cmd.extend(
                    [
                        "-ss",
                        str(background_config.get("start_time", 0.0)),
                        "-i",
                        str(bg_path),
                    ]
                )
            except Exception as e:  # 外側の try に対応する except を追加
                logger.warning(
                    "Failed to process background video: %s. Falling back to image loop.",
                    e,
                )
                cmd.extend(["-loop", "1", "-i", str(bg_path)])
        else:  # if background_config.get("type") == "video": の else
            cmd.extend(["-loop", "1", "-i", str(bg_path)])
        input_layers.append({"type": "video", "index": len(input_layers)})

        # 1) Speech audio
        cmd.extend(["-i", str(audio_path)])
        speech_audio_index = len(input_layers)
        input_layers.append({"type": "audio", "index": speech_audio_index})

        # 2) (Removed) Subtitle PNG pre-injection is handled later via SubtitleGenerator snippet
        subtitle_ffmpeg_index = -1
        subtitle_png_used = False

        # 3) Insert media (optional)
        insert_ffmpeg_index = -1
        insert_audio_index = -1
        insert_is_image = False
        insert_path: Optional[Path] = None
        if insert_config:
            insert_path = Path(insert_config["path"])
            insert_is_image = insert_path.suffix.lower() in [
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".webp",
            ]
            if not insert_is_image:
                try:
                    # 事前正規化済みフラグがあればスキップ
                    if not bool(insert_config.get("normalized", False)):
                        normalized_insert = await normalize_media(
                            input_path=insert_path,
                            video_params=self.video_params,
                            audio_params=self.audio_params,
                            cache_manager=self.cache_manager,
                            ffmpeg_path=self.ffmpeg_path,
                        )
                        insert_path = normalized_insert
                except Exception as e:
                    logger.warning(
                        "Could not inspect/normalize insert video %s: %s. Using as-is.",
                        insert_path.name,
                        e,
                    )
                cmd.extend(["-i", str(insert_path)])
            else:
                cmd.extend(["-loop", "1", "-i", str(insert_path.resolve())])
            insert_ffmpeg_index = len(input_layers)
            input_layers.append({"type": "video", "index": insert_ffmpeg_index})
            if not insert_is_image and await has_audio_stream(str(insert_path)):
                insert_audio_index = insert_ffmpeg_index

        # 4) Characters (optional)
        character_indices: Dict[int, int] = {}
        char_effective_scale: Dict[int, float] = {}
        # record character overlay placement for later face animation overlays
        char_overlay_placement: Dict[str, Dict[str, str]] = {}
        any_character_visible = False
        for i, char_config in enumerate(characters_config):
            if not char_config.get("visible", False):
                continue
            any_character_visible = True
            char_name = char_config.get("name")
            char_expression = char_config.get("expression", "default")
            if not char_name:
                logger.warning("Skipping character with missing name.")
                continue
            # Resolve character base image with new expression-first layout and legacy fallbacks
            def _resolve_char_base_image(name: str, expr: str) -> Optional[Path]:
                base_dir = Path(f"assets/characters/{name}")
                candidates = [
                    base_dir / expr / "base.png",           # new: <name>/<expr>/base.png
                    base_dir / f"{expr}.png",                # legacy: <name>/<expr>.png
                    base_dir / "default" / "base.png",       # new default: <name>/default/base.png
                    base_dir / "default.png",                # legacy default: <name>/default.png
                ]
                for c in candidates:
                    try:
                        if c.exists():
                            return c
                    except Exception:
                        pass
                return None

            char_image_path = _resolve_char_base_image(str(char_name), str(char_expression))
            if not char_image_path:
                logger.warning(
                    "Character image not found for %s/%s (and default). Skipping.",
                    char_name,
                    char_expression,
                )
                continue
            # Pre-scale character image via Pillow cache when enabled
            effective_scale = 1.0
            try:
                scale_cfg = float(char_config.get("scale", 1.0))
            except Exception:
                scale_cfg = 1.0
            use_char_cache = os.environ.get("CHAR_CACHE_DISABLE", "0") != "1"
            if use_char_cache and abs(scale_cfg - 1.0) > 1e-6:
                try:
                    thr_env = os.environ.get("CHAR_ALPHA_THRESHOLD")
                    thr = int(thr_env) if (thr_env and thr_env.isdigit()) else 128
                    scaled_path = await self.face_cache.get_scaled_overlay(
                        char_image_path, float(scale_cfg), thr
                    )
                    character_indices[i] = len(input_layers)
                    cmd.extend(["-loop", "1", "-i", str(scaled_path.resolve())])
                    input_layers.append({"type": "video", "index": len(input_layers)})
                    effective_scale = 1.0  # already applied by cache
                except Exception:
                    character_indices[i] = len(input_layers)
                    cmd.extend(["-loop", "1", "-i", str(char_image_path.resolve())])
                    input_layers.append({"type": "video", "index": len(input_layers)})
                    effective_scale = scale_cfg
            else:
                character_indices[i] = len(input_layers)
                cmd.extend(["-loop", "1", "-i", str(char_image_path.resolve())])
                input_layers.append({"type": "video", "index": len(input_layers)})
                effective_scale = scale_cfg
            # Keep the per-index effective scale for later filter decisions
            char_effective_scale[i] = float(effective_scale)

        # ---- ここで GPU フィルタ使用可否を判定 --------------------------------
        # RGBAを含むオーバーレイ（字幕PNG/立ち絵/挿入画像）が1つでもあれば CPU 合成へ（実験フラグで緩和）
        # RGBA を含むオーバーレイ（字幕PNG/立ち絵/挿入画像）が1つでもあれば CPU 合成へ（実験フラグで緩和）
        uses_alpha_overlay = (
            any_character_visible
            or (insert_config and insert_is_image)
            or (bool(subtitle_text) and str(subtitle_text).strip() != "")
        )
        # If experimental flag is on, try GPU overlays even with RGBA inputs
        global_mode = get_hw_filter_mode()
        use_cuda_filters = (
            self.has_cuda_filters
            and self.hw_kind == "nvenc"
            and (self.gpu_overlay_experimental or not uses_alpha_overlay)
            and not _force_cpu
            and global_mode != "cpu"
        )
        # Even when alpha overlays exist, allow GPU scaling of background only to reduce CPU work
        # Config gate for hybrid path
        allow_gpu_scale_only_cfg = bool(
            self.config.get("video", {}).get("gpu_scale_with_cpu_overlay", True)
        )
        global_mode = get_hw_filter_mode()
        # Allow hybrid path in non-CPU mode as before; additionally, if CPU mode
        # is active due to overlay failures, permit scale-only when the smoke passed.
        allow_in_cpu_mode = self.cuda_scale_only_ok
        scale_only_available = bool(self.scale_only_backend) or self.has_gpu_scale or self.has_cuda_filters
        use_gpu_scale_only = (
            (not use_cuda_filters)
            and scale_only_available
            and self.hw_kind == "nvenc"
            and allow_gpu_scale_only_cfg
            and (not _force_cpu)
            and ((global_mode != "cpu") or allow_in_cpu_mode)
        )
        if use_cuda_filters:
            logger.info(
                "[Filters] CUDA path: scaling/overlay on GPU (no RGBA overlays)"
            )
            try:
                self.path_counters["cuda_overlay"] += 1
            except Exception:
                pass
        else:
            # Prefer hybrid GPU scale-only when allowed (independent of overlay CUDA availability)
            if use_gpu_scale_only:
                logger.info(
                    "[Filters] Hybrid path: GPU scale + CPU overlay (background only)%s",
                    " [cpu-mode-override]" if global_mode == "cpu" else "",
                )
                try:
                    self.path_counters["gpu_scale_only"] += 1
                except Exception:
                    pass
            elif self.hw_kind == "nvenc" and uses_alpha_overlay:
                logger.info(
                    "[Filters] CPU path: RGBA overlays detected; forcing CPU overlays while keeping NVENC encoding"
                )
                try:
                    self.path_counters["cpu"] += 1
                except Exception:
                    pass
            else:
                logger.info("[Filters] CPU path: using CPU filters for scaling/overlay")
                try:
                    self.path_counters["cpu"] += 1
                except Exception:
                    pass

        # --- Filter Graph -------------------------------------------------------
        filter_complex_parts: List[str] = []

        # 背景スケール
        pre_scaled = bool(background_config.get("pre_scaled", False))
        fps_part = f",fps={fps}" if self.apply_fps_filter else ""
        if pre_scaled:
            # すでに width/height/fps に整形済みのベース映像（シーンベース）
            # 無駄な再スケールを避けるため passthrough
            filter_complex_parts.append("[0:v]null[bg]")
        else:
            if use_cuda_filters:
                # CUDA: 一旦GPUへ上げてスケール＋fps。RGBA→NV12 変換はCUDA側に任せる。
                filter_complex_parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
                filter_complex_parts.append(
                    f"[hw_bg_in]{self.scale_filter}={width}:{height}{(f',fps={fps}' if self.apply_fps_filter else '')}[bg]"
                )
            elif use_gpu_scale_only:
                # Hybrid: scale on GPU then download for CPU overlays
                if self.scale_only_backend == "opencl":
                    filter_complex_parts.append("[0:v]format=rgba,hwupload[hw_bg_in]")
                    filter_complex_parts.append(
                        f"[hw_bg_in]scale_opencl={width}:{height}{(f',fps={fps}' if self.apply_fps_filter else '')}[bg_gpu_scaled]"
                    )
                    filter_complex_parts.append(
                        "[bg_gpu_scaled]hwdownload,format=rgba[bg]"
                    )
                else:
                    filter_complex_parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
                    filter_complex_parts.append(
                        f"[hw_bg_in]{self.scale_filter}={width}:{height}{(f',fps={fps}' if self.apply_fps_filter else '')}[bg_gpu_scaled]"
                    )
                    filter_complex_parts.append(
                        "[bg_gpu_scaled]hwdownload,format=rgba[bg]"
                    )
            elif self.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or self.allow_opencl_overlay_in_cpu_mode):
                # OpenCL: 背景のスケールはCPUで行い、その後にGPUへアップロードして合成に回す
                filter_complex_parts.append(
                    f"[0:v]scale={width}:{height}:flags={self.scale_flags}{fps_part}[bg]"
                )
                filter_complex_parts.append("[bg]format=rgba,hwupload[bg_gpu]")
                current_video_stream = "[bg_gpu]"
            else:
                filter_complex_parts.append(
                    f"[0:v]scale={width}:{height}:flags={self.scale_flags}{fps_part}[bg]"
                )
        if not (self.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or self.allow_opencl_overlay_in_cpu_mode)):
            current_video_stream = "[bg]"
        overlay_streams: List[str] = []
        overlay_filters: List[str] = []

        # 挿入メディア overlay
        if insert_config and insert_ffmpeg_index != -1:
            scale = float(insert_config.get("scale", 1.0))
            anchor = insert_config.get("anchor", "middle_center")
            pos = insert_config.get("position", {"x": "0", "y": "0"})
            x_expr, y_expr = calculate_overlay_position(
                "W",
                "H",
                "w",
                "h",
                anchor,
                str(pos.get("x", "0")),
                str(pos.get("y", "0")),
            )

            if use_cuda_filters:
                # CUDA オンリー（RGBAなし前提）
                if insert_is_image:
                    # ここに来るのは想定外（uses_alpha_overlay=True でCPUに落ちる想定）
                    # ただ、保険として rgba→hwupload_cuda→scale_cuda
                    filter_complex_parts.append(
                        f"[{insert_ffmpeg_index}:v]format=rgba,hwupload_cuda,{self.scale_filter}=iw*{scale}:ih*{scale}[insert_scaled]"
                    )
                else:
                    filter_complex_parts.append(
                        f"[{insert_ffmpeg_index}:v]format=nv12,hwupload_cuda,{self.scale_filter}=iw*{scale}:ih*{scale}[insert_scaled]"
                    )
                overlay_streams.append("[insert_scaled]")
                overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
            elif self.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or self.allow_opencl_overlay_in_cpu_mode):
                # スケールはCPUで前処理 → OpenCL へアップロードして overlay_opencl
                filter_complex_parts.append(
                    f"[{insert_ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}[insert_scaled]"
                )
                filter_complex_parts.append(
                    f"[insert_scaled]format=rgba,hwupload[insert_gpu]"
                )
                overlay_streams.append("[insert_gpu]")
                overlay_filters.append(f"overlay_opencl=x={x_expr}:y={y_expr}")
            else:
                filter_complex_parts.append(
                    f"[{insert_ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}:flags={self.scale_flags}[insert_scaled]"
                )
                overlay_streams.append("[insert_scaled]")
                overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

        # 立ち絵 overlay
        # For character pre-scaling via Pillow cache (values filled above)
        preproc_alpha_thr = 128
        try:
            thr_env = os.environ.get("CHAR_ALPHA_THRESHOLD")
            if thr_env and thr_env.isdigit():
                preproc_alpha_thr = int(thr_env)
        except Exception:
            preproc_alpha_thr = 128

        for i, char_config in enumerate(characters_config):
            if not char_config.get("visible", False) or i not in character_indices:
                continue
            ffmpeg_index = character_indices[i]
            scale = float(char_effective_scale.get(i, float(char_config.get("scale", 1.0))))
            anchor = char_config.get("anchor", "bottom_center")
            pos = char_config.get("position", {"x": "0", "y": "0"})
            x_expr, y_expr = calculate_overlay_position(
                "W",
                "H",
                "w",
                "h",
                anchor,
                str(pos.get("x", "0")),
                str(pos.get("y", "0")),
            )

            if use_cuda_filters:
                # 想定上ここには来ない（uses_alpha_overlay True → CPU 合成）
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]format=rgba,hwupload_cuda,{self.scale_filter}=iw*{scale}:ih*{scale}[char_scaled_{i}]"
                )
                overlay_streams.append(f"[char_scaled_{i}]")
                overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
            elif self.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or self.allow_opencl_overlay_in_cpu_mode):
                # 前段で Pillow による事前スケールが有効な場合、scale は 1.0 に縮退
                if os.environ.get("CHAR_CACHE_DISABLE", "0") != "1":
                    try:
                        from .face_overlay_cache import FaceOverlayCache

                        cache = self.face_cache  # same cache instance
                        # 事前スケール済み PNG を別入力として差し替え（ffmpeg_index の実入力を置換）
                        # ここではフィルタでのスケールを行わず、GPU に上げて overlay のみ実施
                        # 既存 ffmpeg_index はそのまま使用し、format=rgba,hwupload を適用
                        filter_complex_parts.append(
                            f"[{ffmpeg_index}:v]format=rgba,hwupload[char_gpu_{i}]"
                        )
                        overlay_streams.append(f"[char_gpu_{i}]")
                        overlay_filters.append(
                            f"overlay_opencl=x={x_expr}:y={y_expr}"
                        )
                        char_effective_scale[i] = 1.0
                    except Exception:
                        # フォールバック: CPU スケール→GPUへ
                        filter_complex_parts.append(
                            f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}[char_scaled_{i}]"
                        )
                        filter_complex_parts.append(
                            f"[char_scaled_{i}]format=rgba,hwupload[char_gpu_{i}]"
                        )
                        overlay_streams.append(f"[char_gpu_{i}]")
                        overlay_filters.append(
                            f"overlay_opencl=x={x_expr}:y={y_expr}"
                        )
                        char_effective_scale[i] = 1.0
            else:
                # CPU 経路: 事前スケールが有効なら scale を省いて format のみ
                if os.environ.get("CHAR_CACHE_DISABLE", "0") != "1" and abs(scale - 1.0) < 1e-6:
                    filter_complex_parts.append(
                        f"[{ffmpeg_index}:v]format=rgba[char_scaled_{i}]"
                    )
                else:
                    filter_complex_parts.append(
                        f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}:flags={self.scale_flags}[char_scaled_{i}]"
                    )
                overlay_streams.append(f"[char_scaled_{i}]")
                overlay_filters.append(f"overlay=x={x_expr}:y={y_expr}")

            # Remember placement for face animation use keyed by char name
            try:
                # Compute numeric top-left for stable face overlays to avoid anchor jitter
                def _to_num(v: Any) -> float:
                    try:
                        return float(v)
                    except Exception:
                        return 0.0
                xn = yn = 0.0
                try:
                    from PIL import Image as _PILImage
                    w0, h0 = _PILImage.open(char_image_path).size
                except Exception:
                    w0, h0 = 0, 0
                try:
                    vw, vh = self.video_params.width, self.video_params.height
                    sx = _to_num(pos.get("x", "0"))
                    sy = _to_num(pos.get("y", "0"))
                    # Use original config scale for face overlay reference, not effective (pre-scaled) scale
                    try:
                        scale_orig = float(char_config.get("scale", 1.0))
                    except Exception:
                        scale_orig = float(scale)
                    cw = w0 * float(scale_orig)
                    ch = h0 * float(scale_orig)
                    a = str(anchor)
                    if a == "top_left":
                        xn, yn = sx, sy
                    elif a == "top_center":
                        xn, yn = (vw - cw) / 2 + sx, sy
                    elif a == "top_right":
                        xn, yn = vw - cw + sx, sy
                    elif a == "middle_left":
                        xn, yn = sx, (vh - ch) / 2 + sy
                    elif a == "middle_center":
                        xn, yn = (vw - cw) / 2 + sx, (vh - ch) / 2 + sy
                    elif a == "middle_right":
                        xn, yn = vw - cw + sx, (vh - ch) / 2 + sy
                    elif a == "bottom_left":
                        xn, yn = sx, vh - ch + sy
                    elif a == "bottom_center":
                        xn, yn = (vw - cw) / 2 + sx, vh - ch + sy
                    elif a == "bottom_right":
                        xn, yn = vw - cw + sx, vh - ch + sy
                except Exception:
                    pass
                char_overlay_placement[str(char_name)] = {
                    "x_expr": x_expr,
                    "y_expr": y_expr,
                    "scale_orig": str(scale_orig),
                    "scale_eff": str(scale),
                    "x_num": str(int(round(xn))),
                    "y_num": str(int(round(yn))),
                    "expression": str(char_expression),
                }
            except Exception:
                pass

        # Helper: build enable expr from segments
        def _enable_expr(segments: List[Dict[str, Any]]) -> Optional[str]:
            try:
                parts = [
                    f"between(t,{float(seg['start']):.3f},{float(seg['end']):.3f})"
                    for seg in segments
                    if float(seg.get("end", 0)) > float(seg.get("start", 0))
                ]
                if not parts:
                    return None
                return "+".join(parts)
            except Exception:
                return None

        # Face animation overlays (mouth/eyes) for the speaking character
        if face_anim and isinstance(face_anim, dict) and face_anim.get("target_name"):
            target_name = str(face_anim.get("target_name"))
            # Find placement: from rendered characters, or from original line config if character pre-composited in base
            placement = char_overlay_placement.get(target_name)
            if not placement and subtitle_line_config:
                try:
                    for ch in (subtitle_line_config.get("characters") or []):
                        if ch.get("name") == target_name:
                            scale = float(ch.get("scale", 1.0))
                            anchor = ch.get("anchor", "bottom_center")
                            pos = ch.get("position", {"x": "0", "y": "0"}) or {}
                            x_expr, y_expr = calculate_overlay_position(
                                "W",
                                "H",
                                "w",
                                "h",
                                str(anchor),
                                str(pos.get("x", "0")),
                                str(pos.get("y", "0")),
                            )
                            placement = {
                                "x_expr": x_expr,
                                "y_expr": y_expr,
                                "scale": str(scale),
                                "expression": str(ch.get("expression", "default")),
                            }
                            break
                except Exception:
                    placement = None

            if placement:
                scale = placement.get("scale_orig") or placement.get("scale") or "1.0"
                # Use numeric top-left position for stability (independent of each overlay's w/h)
                x_fix = placement.get("x_num") or placement.get("x_expr") or "0"
                y_fix = placement.get("y_num") or placement.get("y_expr") or "0"

                # Asset discovery
                base_dir = Path(f"assets/characters/{target_name}")
                expr = str(placement.get("expression") or "default")
                expr_dir = base_dir / expr
                # Prefer expression-local mouth/eyes, then legacy common directories,
                # then legacy style mouth/<expr> and eyes/<expr> as a last resort.
                mouth_dir_candidates = [
                    expr_dir / "mouth",
                    base_dir / "mouth",
                    base_dir / "mouth" / expr,
                ]
                eyes_dir_candidates = [
                    expr_dir / "eyes",
                    base_dir / "eyes",
                    base_dir / "eyes" / expr,
                ]
                def _first_dir(dirs: List[Path]) -> Path:
                    for d in dirs:
                        try:
                            if d.exists() and d.is_dir():
                                return d
                        except Exception:
                            pass
                    # fallback to base_dir to build non-existing files below (exists checks later)
                    return base_dir
                mouth_dir = _first_dir(mouth_dir_candidates)
                eyes_dir = _first_dir(eyes_dir_candidates)

                # File candidates: expression-local first, then common directory
                def _pick_file(expr_dir: Path, common_dir: Path, fname: str) -> Path:
                    cand1 = expr_dir / fname
                    cand2 = common_dir / fname
                    return cand1 if cand1.exists() else cand2

                mouth_close = _pick_file(expr_dir / "mouth", base_dir / "mouth", "close.png")
                mouth_half = _pick_file(expr_dir / "mouth", base_dir / "mouth", "half.png")
                mouth_open = _pick_file(expr_dir / "mouth", base_dir / "mouth", "open.png")
                eyes_open = _pick_file(expr_dir / "eyes", base_dir / "eyes", "open.png")
                eyes_close = _pick_file(expr_dir / "eyes", base_dir / "eyes", "close.png")

                # Debug info
                try:
                    m_segments = face_anim.get("mouth") or []
                    e_segments = face_anim.get("eyes") or []
                    logger.debug(
                        "[FaceAnim] target=%s scale=%s mouth_pngs(close=%s,half=%s,open=%s) eyes_pngs(open=%s,close=%s) segs(m=%d,e=%d)",
                        target_name,
                        scale,
                        mouth_close.exists(),
                        mouth_half.exists(),
                        mouth_open.exists(),
                        eyes_open.exists(),
                        eyes_close.exists(),
                        len(m_segments) if isinstance(m_segments, list) else 0,
                        len(e_segments) if isinstance(e_segments, list) else 0,
                    )
                except Exception:
                    pass

                # Only enable when assets exist
                # add inputs lazily and build filters
                def _add_image_input(path: Path) -> Optional[int]:
                    if path.exists():
                        cmd.extend(["-loop", "1", "-i", str(path.resolve())])
                        idx = len(input_layers)
                        input_layers.append({"type": "video", "index": idx})
                        return idx
                    return None

                # Prepare overlay chain; prefer preprocessed cached PNG, fallback to inline filter
                preprocessed_inputs: set[int] = set()
                async def _add_preprocessed_overlay(path: Path, scale_val: float) -> Optional[int]:
                    try:
                        if os.environ.get("FACE_CACHE_DISABLE", "0") == "1":
                            return _add_image_input(path)
                        thr_env = os.environ.get("FACE_ALPHA_THRESHOLD")
                        thr = int(thr_env) if (thr_env and thr_env.isdigit()) else 128
                        cached = await self.face_cache.get_scaled_overlay(path, float(scale_val), thr)
                        idx = _add_image_input(cached)
                        if idx is not None:
                            preprocessed_inputs.add(idx)
                        return idx
                    except Exception:
                        return _add_image_input(path)
                
                def _prep_overlay(idx: int, scale_val: float, out_label: str) -> None:
                    if idx in preprocessed_inputs:
                        # Already scaled via Pillow; only ensure rgba passthrough
                        filter_complex_parts.append(
                            f"[{idx}:v]format=rgba[{out_label}]"
                        )
                    else:
                        filter_complex_parts.append(
                            f"[{idx}:v]format=rgba,scale=iw*{scale_val}:ih*{scale_val}[{out_label}]"
                        )

                # Eyes: show only 'close' during blink to avoid doubling base open eyes
                eyes_segments = face_anim.get("eyes") or []
                eyes_close_expr = _enable_expr(eyes_segments) if eyes_segments else None
                if eyes_close.exists() and eyes_close_expr:
                    idx = await _add_preprocessed_overlay(eyes_close, float(scale))
                    if idx is not None:
                        label = f"eyes_close_scaled_{idx}"
                        _prep_overlay(idx, float(scale), label)
                        overlay_streams.append(f"[{label}]")
                        overlay_filters.append(
                            f"overlay=x={x_fix}:y={y_fix}:enable='{eyes_close_expr}'"
                        )

                # Mouth: overlay only 'half'/'open' states; avoid baseline 'close' to prevent doubling
                mouth_segments = face_anim.get("mouth") or []
                half_expr = open_expr = None
                if isinstance(mouth_segments, list) and mouth_segments:
                    half_segments = [s for s in mouth_segments if s.get("state") == "half"]
                    open_segments = [s for s in mouth_segments if s.get("state") == "open"]
                    half_expr = _enable_expr(half_segments) if half_segments else None
                    open_expr = _enable_expr(open_segments) if open_segments else None

                if mouth_half.exists() and half_expr:
                    idx = await _add_preprocessed_overlay(mouth_half, float(scale))
                    if idx is not None:
                        label = f"mouth_half_scaled_{idx}"
                        _prep_overlay(idx, float(scale), label)
                        overlay_streams.append(f"[{label}]")
                        overlay_filters.append(
                            f"overlay=x={x_fix}:y={y_fix}:enable='{half_expr}'"
                        )

                if mouth_open.exists() and open_expr:
                    idx = await _add_preprocessed_overlay(mouth_open, float(scale))
                    if idx is not None:
                        label = f"mouth_open_scaled_{idx}"
                        _prep_overlay(idx, float(scale), label)
                        overlay_streams.append(f"[{label}]")
                        overlay_filters.append(
                            f"overlay=x={x_fix}:y={y_fix}:enable='{open_expr}'"
                        )

        # オーバーレイを連結
        if overlay_streams:
            # OpenCL 使用時は overlay フィルタ名を置換
            if self.gpu_overlay_backend == "opencl" and not _force_cpu and get_hw_filter_mode() != "cpu":
                overlay_filters = [
                    (f.replace("overlay=", "overlay_opencl=") if f.startswith("overlay=") else f)
                    for f in overlay_filters
                ]
                try:
                    self.path_counters["opencl_overlay"] += 1
                except Exception:
                    pass
            chain = current_video_stream
            for i, stream in enumerate(overlay_streams):
                chain += f"{stream}{overlay_filters[i]}"
                if i < len(overlay_streams) - 1:
                    chain += f"[tmp_overlay_{i}];[tmp_overlay_{i}]"
                else:
                    chain += "[final_v_overlays]"
            filter_complex_parts.append(chain)
            # OpenCL で作成したフレームは CPU へ戻す
            if self.gpu_overlay_backend == "opencl" and not _force_cpu and get_hw_filter_mode() != "cpu":
                filter_complex_parts.append(
                    "[final_v_overlays]hwdownload,format=yuv420p[final_v_overlays_cpu]"
                )
                current_video_stream = "[final_v_overlays_cpu]"
            else:
                current_video_stream = "[final_v_overlays]"
        else:
            current_video_stream = "[bg]"

        # 字幕スニペットを反映（存在時）
        subtitle_snippet = None
        if subtitle_text and isinstance(subtitle_text, str) and subtitle_text.strip():
            try:
                # この時点での字幕入力インデックスを確定
                subtitle_ffmpeg_index = len(input_layers)
                in_label_name = current_video_stream.strip("[]")
                extra_inputs, subtitle_snippet = await self.subtitle_gen.build_subtitle_overlay(
                    subtitle_text,
                    duration,
                    subtitle_line_config or {},
                    in_label=in_label_name,
                    index=subtitle_ffmpeg_index,
                    force_cpu=_force_cpu,
                    allow_cuda=use_cuda_filters,
                    existing_png_path=str(subtitle_png_path) if subtitle_png_path else None,
                )
                # PNG 入力を追加
                if isinstance(extra_inputs, dict) and extra_inputs.get("-i"):
                    loop_val = extra_inputs.get("-loop", "1")
                    png_path = extra_inputs["-i"]
                    cmd.extend(["-loop", loop_val, "-i", str(Path(png_path).resolve())])
                    input_layers.append({"type": "video", "index": subtitle_ffmpeg_index})
                    subtitle_png_used = True
                    # Keep for potential retry reuse
                    try:
                        subtitle_png_path = Path(png_path)
                    except Exception:
                        pass
                else:
                    logger.warning(
                        "Unexpected subtitle extra inputs: %s. Skipping subtitle overlay.",
                        extra_inputs,
                    )
                    subtitle_snippet = None
                # フィルタスニペットを適用
                if subtitle_snippet:
                    filter_complex_parts.append(subtitle_snippet)
                    current_video_stream = f"[with_subtitle_{subtitle_ffmpeg_index}]"
            except Exception as e:
                logger.warning("Failed to build subtitle overlay snippet: %s", e)
                subtitle_snippet = None

        # 最終フォーマット変換（CUDA使用がどこかであれば hwdownload を挟む）
        used_any_cuda = use_cuda_filters or (
            isinstance(subtitle_snippet, str) and ("overlay_cuda" in subtitle_snippet)
        )
        if used_any_cuda and self.hw_kind == "nvenc":
            # GPU内完結: そのまま NVENC に渡す（CPUへの hwdownload を回避）
            filter_complex_parts.append(f"{current_video_stream}null[final_v]")
        else:
            # CPU 経路（または NVENC 以外）は従来通り yuv420p へ確定
            filter_complex_parts.append(f"{current_video_stream}format=yuv420p[final_v]")

        # --- Audio --------------------------------------------------------------
        # has_audio_stream is async; ensure we await it to get a boolean
        has_speech_audio = await has_audio_stream(str(audio_path))

        if insert_config and insert_audio_index != -1:
            volume = float(insert_config.get("volume", 1.0))
            filter_complex_parts.append(
                f"[{insert_audio_index}:a]volume={volume}[insert_audio_vol]"
            )
            if has_speech_audio:
                filter_complex_parts.append(
                    f"[{speech_audio_index}:a][insert_audio_vol]amix=inputs=2:duration=longest:dropout_transition=0[final_a]"
                )
                audio_map = "[final_a]"
            else:
                filter_complex_parts.append(f"[insert_audio_vol]anull[final_a]")
                audio_map = "[final_a]"
        else:
            if has_speech_audio:
                filter_complex_parts.append(f"[{speech_audio_index}:a]anull[final_a]")
                audio_map = "[final_a]"
            else:
                # 無音生成
                filter_complex_parts.append(
                    f"anullsrc=channel_layout=stereo:sample_rate={self.audio_params.sample_rate},duration={duration}[final_a]"
                )
                audio_map = "[final_a]"

        # --- Assemble & Run -----------------------------------------------------
        cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
        cmd.extend(["-map", "[final_v]", "-map", audio_map])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(None if _force_cpu else self.hw_kind))
        cmd.extend(self.audio_params.to_ffmpeg_opts())
        cmd.extend(["-shortest", str(output_path)])

        try:
            logger.debug("Executing FFmpeg command: %s", " ".join(cmd))
            process = await _run_ffmpeg_async(cmd)
            if process.stderr:
                # warning ログも拾っておく
                logger.debug("FFmpeg stderr (non-fatal):\n%s", process.stderr.strip())
            try:
                _elapsed = _time.time() - _t0
                logger.info("[Video] Finished clip %s in %.2fs", output_filename, _elapsed)
            except Exception:
                pass
        except subprocess.CalledProcessError as e:
            logger.error("ffmpeg failed for %s", output_filename)
            logger.error("FFmpeg STDERR:\n%s", (e.stderr or "").strip())
            logger.error("FFmpeg STDOUT:\n%s", (e.stdout or "").strip())
            # NVENC/CUDA 系の失敗時は一度だけ CPU でリトライ
            msg = (e.stderr or "") + "\n" + (e.stdout or "")
            rc = getattr(e, "returncode", None)
            should_fallback = (
                ("exit status 234" in msg)
                or ("exit code 234" in msg)
                or (rc == 234)
                or ("exit status 218" in msg)
                or ("exit code 218" in msg)
                or ("h264_nvenc" in msg)
                or ("nvenc" in msg.lower())
                or ("overlay_cuda" in msg)
                or ("scale_cuda" in msg)
            )
            if not _force_cpu and should_fallback:
                logger.warning(
                    "[Fallback] NVENC/CUDA path failed. Retrying with CPU filters/encoder."
                )
                # 実行時CUDA失敗時も一度だけ診断ダンプを出力
                try:
                    await _dump_cuda_diag_once(self.ffmpeg_path)
                except Exception:
                    pass
                # Process-wide backoff to CPU filters to avoid repeat failures
                try:
                    set_hw_filter_mode("cpu")
                except Exception:
                    pass
                prev_hw = os.environ.get("DISABLE_HWENC")
                prev_ft = os.environ.get("FFMPEG_FILTER_THREADS")
                prev_fct = os.environ.get("FFMPEG_FILTER_COMPLEX_THREADS")
                prev_ath = os.environ.get("DISABLE_ALPHA_HARD_THRESHOLD")
                os.environ["DISABLE_HWENC"] = "1"
                # 安定化のためフィルタグラフ並列を最小化
                os.environ["FFMPEG_FILTER_THREADS"] = "1"
                os.environ["FFMPEG_FILTER_COMPLEX_THREADS"] = "1"
                # Disable alpha hard-threshold path on retry in case of filter incompatibility
                os.environ["DISABLE_ALPHA_HARD_THRESHOLD"] = "1"
                try:
                    return await self.render_clip(
                        audio_path=audio_path,
                        duration=duration,
                        background_config=background_config,
                        characters_config=characters_config,
                        output_filename=output_filename,
                        subtitle_text=subtitle_text,
                        subtitle_line_config=subtitle_line_config,
                        insert_config=insert_config,
                        subtitle_png_path=subtitle_png_path,
                        face_anim=face_anim,
                        _force_cpu=True,
                    )
                finally:
                    if prev_hw is None:
                        os.environ.pop("DISABLE_HWENC", None)
                    else:
                        os.environ["DISABLE_HWENC"] = prev_hw
                    if prev_ft is None:
                        os.environ.pop("FFMPEG_FILTER_THREADS", None)
                    else:
                        os.environ["FFMPEG_FILTER_THREADS"] = prev_ft
                    if prev_fct is None:
                        os.environ.pop("FFMPEG_FILTER_COMPLEX_THREADS", None)
                    else:
                        os.environ["FFMPEG_FILTER_COMPLEX_THREADS"] = prev_fct
                    if prev_ath is None:
                        os.environ.pop("DISABLE_ALPHA_HARD_THRESHOLD", None)
                    else:
                        os.environ["DISABLE_ALPHA_HARD_THRESHOLD"] = prev_ath
            raise
        except Exception as e:
            logger.error("Unexpected exception during ffmpeg: %s", e)
            raise

        return output_path

    # --------------------------
    # シーンベース（背景のみ、静的）
    # --------------------------
    async def render_scene_base(
        self,
        background_config: Dict[str, Any],
        duration: float,
        output_filename: str,
    ) -> Path:
        """
        背景のみでシーン全長のベース映像を事前生成。
        - 背景が動画: ループ＋正規化して width/height/fps に整える（無音でも可）
        - 背景が静止画: 画像ループで映像を作成（無音のサイレントトラック付き）

        返り値は temp_dir 配下のパス。
        """
        bg_type = background_config.get("type")
        bg_path = Path(background_config.get("path"))
        # 動画背景 → 既存のループ関数を使用
        if bg_type == "video":
            return await self.render_looped_background_video(
                str(bg_path), duration, output_filename
            )

        # 画像背景 → wait クリップ相当で全長の無音ビデオを生成
        # line_config は未使用のため空でOK
        line_cfg: Dict[str, Any] = {}
        base_path = await self.render_wait_clip(
            duration=duration,
            background_config={"type": "image", "path": str(bg_path)},
            output_filename=output_filename,
            line_config=line_cfg,
        )
        if base_path is None:
            raise PipelineError("Failed to render scene base from image background.")
        return base_path

    async def render_scene_base_composited(
        self,
        background_config: Dict[str, Any],
        duration: float,
        output_filename: str,
        overlays: List[Dict[str, Any]],
    ) -> Path:
        """
        背景に複数の静的画像レイヤを事前合成して、シーン全長のベース映像を生成。
        - overlays: [{ path, scale, anchor, position: {x,y} }]
        - 出力は width/height/fps に整形済みの H.264/HEVC ベース映像（音声なし）
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            *get_profile_flags(),
        ]
        cmd.extend(self._thread_flags())
        cmd.extend(get_profile_flags())

        # Inputs
        bg_type = background_config.get("type")
        bg_path = Path(background_config.get("path"))
        if bg_type == "video":
            # 正規化（キャッシュ込み）
            try:
                key_data = {
                    "input_path": str(bg_path.resolve()),
                    "video_params": self.video_params.__dict__,
                    "audio_params": self.audio_params.__dict__,
                }

                async def _normalize_bg_creator(temp_output_path: Path) -> Path:
                    return await normalize_media(
                        input_path=bg_path,
                        video_params=self.video_params,
                        audio_params=self.audio_params,
                        cache_manager=self.cache_manager,
                        ffmpeg_path=self.ffmpeg_path,
                    )

                bg_path = await self.cache_manager.get_or_create(
                    key_data=key_data,
                    file_name="normalized_bg",
                    extension="mp4",
                    creator_func=_normalize_bg_creator,
                )
            except Exception:
                pass
            cmd.extend(["-stream_loop", "-1", "-i", str(bg_path)])
        else:
            cmd.extend(["-loop", "1", "-i", str(bg_path)])

        overlay_indices: List[int] = []
        for ov in overlays:
            cmd.extend(["-loop", "1", "-i", str(Path(ov["path"]).resolve())])
            overlay_indices.append(len(overlay_indices) + 1)  # 1-based against bg as 0

        # Filters
        filter_parts: List[str] = []
        fps_part = f",fps={fps}" if self.apply_fps_filter else ""
        if bg_type == "video":
            filter_parts.append(
                f"[0:v]scale={width}:{height}:flags={self.scale_flags}{fps_part}[bg]"
            )
        else:
            filter_parts.append(
                f"[0:v]scale={width}:{height}:flags={self.scale_flags}{fps_part},trim=duration={duration}[bg]"
            )

        chain = "[bg]"
        for i, ov in enumerate(overlays):
            idx = i + 1  # ffmpeg input index for this overlay (after bg)
            scale = float(ov.get("scale", 1.0))
            anchor = ov.get("anchor", "middle_center")
            pos = ov.get("position", {"x": "0", "y": "0"})
            x_expr, y_expr = calculate_overlay_position(
                "W",
                "H",
                "w",
                "h",
                anchor,
                str(pos.get("x", "0")),
                str(pos.get("y", "0")),
            )
            filter_parts.append(
                f"[{idx}:v]scale=iw*{scale}:ih*{scale}:flags={self.scale_flags}[ov_{i}]"
            )
            if i < len(overlays) - 1:
                chain += f"[ov_{i}]overlay=x={x_expr}:y={y_expr}[tmp_{i}];[tmp_{i}]"
            else:
                chain += f"[ov_{i}]overlay=x={x_expr}:y={y_expr}[ov_final]"
        if overlays:
            filter_parts.append(f"{chain}")
            final_stream = "[ov_final]"
        else:
            final_stream = "[bg]"

        filter_parts.append(f"{final_stream}format=yuv420p[final_v]")

        cmd.extend(["-filter_complex", ";".join(filter_parts)])
        cmd.extend(["-map", "[final_v]"])
        if bg_type == "video":
            cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(["-an"])  # ベースは映像のみ
        cmd.extend([str(output_path)])

        try:
            process = await _run_ffmpeg_async(cmd)
            if process.stderr:
                print(process.stderr.strip())
            return output_path
        except subprocess.CalledProcessError as e:
            print(
                f"[Error] ffmpeg failed for composited scene base {output_filename}"
            )
            print("---- FFmpeg STDERR ----")
            print((e.stderr or "").strip())
            print("---- FFmpeg STDOUT ----")
            print((e.stdout or "").strip())
            raise

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
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        print(f"[Video] Rendering wait clip -> {output_path.name}")

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]
        cmd.extend(self._thread_flags())

        # 1) Background
        bg_path_str = background_config.get("path")
        if not bg_path_str:
            raise ValueError("Background path is missing.")
        bg_path = Path(bg_path_str)

        if background_config.get("type") == "video":
            try:
                # ループ済みシーンBGなど、既に正規化済みの入力はスキップ
                normalized_hint = bool(background_config.get("normalized", False))
                is_temp_scene_bg = (
                    bg_path.parent.resolve() == self.temp_dir.resolve()
                    and bg_path.name.startswith("scene_bg_")
                )
                should_skip_normalize = normalized_hint or is_temp_scene_bg

                if not should_skip_normalize:
                    # 正規化（失敗時は as-is）
                    try:
                        key_data = {
                            "input_path": str(bg_path.resolve()),
                            "video_params": self.video_params.__dict__,
                            "audio_params": self.audio_params.__dict__,
                        }

                        async def _normalize_bg_creator_wait(
                            temp_output_path: Path,
                        ) -> Path:
                            return await normalize_media(
                                input_path=bg_path,
                                video_params=self.video_params,
                                audio_params=self.audio_params,
                                cache_manager=self.cache_manager,
                                ffmpeg_path=self.ffmpeg_path,
                            )

                        bg_path = await self.cache_manager.get_or_create(
                            key_data=key_data,
                            file_name="normalized_bg",
                            extension="mp4",
                            creator_func=_normalize_bg_creator_wait,
                        )
                    except Exception as e:
                        print(
                            f"[Warning] Could not inspect/normalize BG video {bg_path.name}: {e}. Using as-is."
                        )
                cmd.extend(
                    [
                        "-ss",
                        str(background_config.get("start_time", 0.0)),
                        "-i",
                        str(bg_path),
                    ]
                )
            except Exception as e:
                print(
                    f"[Warning] Failed to process background video: {e}. Falling back to image loop."
                )
                cmd.extend(["-loop", "1", "-i", str(bg_path)])
        else:
            cmd.extend(["-loop", "1", "-i", str(bg_path)])

        # 2) Silent audio
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate={self.audio_params.sample_rate}",
            ]
        )

        # Filters（CPUで十分）
        pre_scaled = bool(background_config.get("pre_scaled", False))
        if pre_scaled:
            # ベースがすでに width/height/fps に整形済みなら再スケール不要
            filter_complex = f"[0:v]trim=duration={duration},format=yuv420p[final_v]"
        else:
            filter_complex = f"[0:v]scale={width}:{height}:flags={self.scale_flags},trim=duration={duration},format=yuv420p[final_v]"

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[final_v]", "-map", "1:a"])
        cmd.extend(["-t", str(duration)])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(self.audio_params.to_ffmpeg_opts())
        cmd.extend(["-shortest", str(output_path)])

        try:
            print(f"Executing FFmpeg command:\n{' '.join(cmd)}")
            process = await _run_ffmpeg_async(cmd)
            if process.stderr:
                print(process.stderr.strip())
        except subprocess.CalledProcessError as e:
            print(
                f"[Error] ffmpeg failed for looped background video {output_filename}"
            )
            print("---- FFmpeg STDERR ----")
            print((e.stderr or "").strip())
            print("---- FFmpeg STDOUT ----")
            print((e.stdout or "").strip())
            raise
        except Exception as e:
            print(f"[Error] Unexpected exception during ffmpeg: {e}")
            raise

        return output_path

    # --------------------------
    # BG動画の指定長ループ
    # --------------------------
    async def render_looped_background_video(
        self, bg_video_path_str: str, duration: float, output_filename: str
    ) -> Path:
        """
        指定長でBG動画をループ書き出し。
        """
        output_path = self.temp_dir / f"{output_filename}.mp4"
        width = self.video_params.width
        height = self.video_params.height
        fps = self.video_params.fps

        print(f"[Video] Rendering looped background video -> {output_path.name}")

        cmd: List[str] = [
            self.ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]
        cmd.extend(self._thread_flags())

        bg_video_path = Path(bg_video_path_str)
        # 正規化（失敗時は as-is）
        try:
            key_data = {
                "input_path": str(bg_video_path.resolve()),
                "video_params": self.video_params.__dict__,
                "audio_params": self.audio_params.__dict__,
            }

            async def _normalize_bg_creator_looped(temp_output_path: Path) -> Path:
                return await normalize_media(
                    input_path=bg_video_path,
                    video_params=self.video_params,
                    audio_params=self.audio_params,
                    cache_manager=self.cache_manager,
                    ffmpeg_path=self.ffmpeg_path,
                )

            bg_video_path = await self.cache_manager.get_or_create(
                key_data=key_data,
                file_name="normalized_looped_bg",
                extension="mp4",
                creator_func=_normalize_bg_creator_looped,
            )
        except Exception as e:
            print(
                f"[Warning] Could not inspect/normalize looped BG video {bg_video_path.name}: {e}. Using as-is."
            )

        vf = f"scale={width}:{height}:flags={self.scale_flags}"
        if self.apply_fps_filter:
            vf += f",fps={fps}"
        vf += ",format=yuv420p"
        cmd.extend([
            "-stream_loop",
            "-1",
            "-i",
            str(bg_video_path),
            "-t",
            str(duration),
            "-vf",
            vf,
        ])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        cmd.extend(["-an"])  # 音声は不要
        cmd.extend([str(output_path)])

        try:
            print(f"Executing FFmpeg command:\n{' '.join(cmd)}")
            process = await _run_ffmpeg_async(cmd)
            if process.stderr:
                print(process.stderr.strip())
        except subprocess.CalledProcessError as e:
            print(
                f"[Error] ffmpeg failed for looped background video {output_filename}"
            )
            print("---- FFmpeg STDERR ----")
            print((e.stderr or "").strip())
            print("---- FFmpeg STDOUT ----")
            print((e.stdout or "").strip())
            raise
        except Exception as e:
            print(f"[Error] Unexpected exception during ffmpeg: {e}")
            raise

        return output_path

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

    async def apply_foreground_overlays(
        self, base_video: Path, overlays: List[Dict[str, Any]]
    ) -> Path:
        """Apply foreground overlay videos onto a base video using ffmpeg."""
        if not overlays:
            return base_video

        output_path = self.temp_dir / f"{base_video.stem}_fg.mp4"
        # Bound output to base video duration to avoid infinite overlays (e.g. -stream_loop)
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None

        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]

        for ov in overlays:
            timing = ov.get("timing", {})
            loop = timing.get("loop")
            if loop:
                cmd.extend(["-stream_loop", "-1"])
            cmd.extend(["-i", str(Path(ov["src"]).resolve())])

        cmd.extend(self._thread_flags())

        filter_parts: List[str] = []
        prev_stream = "[0:v]"

        for idx, ov in enumerate(overlays):
            in_stream = f"[{idx + 1}:v]"
            steps: List[str] = []
            mode = ov.get("mode", "overlay")
            fps = ov.get("fps")
            if fps:
                steps.append(f"fps={int(fps)}")
            scale_cfg = ov.get("scale", {})
            w = scale_cfg.get("w")
            h = scale_cfg.get("h")
            keep = scale_cfg.get("keep_aspect")
            if w and h:
                if keep:
                    steps.append(
                        f"scale={w}:{h}:flags={self.scale_flags}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
                    )
                else:
                    steps.append(f"scale={w}:{h}:flags={self.scale_flags}")
            if mode == "chroma":
                chroma = ov.get("chroma", {})
                key_color = chroma.get("key_color", "#000000").replace("#", "0x")
                similarity = chroma.get("similarity", 0.1)
                blend = chroma.get("blend", 0.0)
                steps.append(f"colorkey={key_color}:{similarity}:{blend}")
            steps.append("format=rgba")
            opacity = ov.get("opacity")
            if opacity is not None:
                steps.append(f"colorchannelmixer=aa={float(opacity)}")
            processed = f"[ov{idx}]"
            filter_parts.append(f"{in_stream}{','.join(steps)}{processed}")

            pos = ov.get("position", {})
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            timing = ov.get("timing", {})
            start = float(timing.get("start", 0.0))
            duration = timing.get("duration")
            if duration is not None:
                end = start + float(duration)
                enable = f"between(t,{start},{end})"
            else:
                enable = f"gte(t,{start})"

            if mode == "blend":
                blend_mode = ov.get("blend_mode", "screen")
                filter_parts.append(
                    f"{prev_stream}{processed}blend=all_mode={blend_mode}:enable='{enable}'[tmp{idx}]"
                )
            else:
                filter_parts.append(
                    f"{prev_stream}{processed}overlay=x={x}:y={y}:enable='{enable}'[tmp{idx}]"
                )
            prev_stream = f"[tmp{idx}]"

        filter_complex = ";".join(filter_parts)

        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        # Keep audio stream as-is (no re-encode) for overlay-only operations
        cmd.extend(["-c:a", "copy"])
        # Ensure we don't run past base video length
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg_async(cmd)
        return output_path

    async def apply_overlays(
        self,
        base_video: Path,
        overlays: List[Dict[str, Any]],
        subtitles: List[Dict[str, Any]],
    ) -> Path:
        """Apply foreground overlays and timed subtitle overlays in a single pass.

        - Foreground overlays are applied first in the order provided.
        - Subtitles are then applied sequentially on top so they always appear above.
        """
        if not overlays and not subtitles:
            return base_video

        output_path = self.temp_dir / f"{base_video.stem}_fg_sub.mp4"
        # Bound to base duration to avoid running past the base (e.g., loops)
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None

        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]

        # 1) Add overlay inputs
        for ov in overlays or []:
            timing = ov.get("timing", {})
            if timing.get("loop"):
                cmd.extend(["-stream_loop", "-1"])
            cmd.extend(["-i", str(Path(ov["src"]).resolve())])

        # We'll compute subtitle PNG inputs while building filter graph

        cmd.extend(self._thread_flags())

        filter_parts: List[str] = []
        prev_stream = "[0:v]"

        # 2) Foreground overlays
        for idx, ov in enumerate(overlays or []):
            in_stream = f"[{idx + 1}:v]"
            steps: List[str] = []
            mode = ov.get("mode", "overlay")
            fps = ov.get("fps")
            if fps:
                steps.append(f"fps={int(fps)}")
            scale_cfg = ov.get("scale", {})
            w = scale_cfg.get("w")
            h = scale_cfg.get("h")
            keep = scale_cfg.get("keep_aspect")
            if w and h:
                if keep:
                    steps.append(
                        f"scale={w}:{h}:flags={self.scale_flags}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
                    )
                else:
                    steps.append(f"scale={w}:{h}:flags={self.scale_flags}")
            if mode == "chroma":
                chroma = ov.get("chroma", {})
                key_color = chroma.get("key_color", "#000000").replace("#", "0x")
                similarity = chroma.get("similarity", 0.1)
                blend = chroma.get("blend", 0.0)
                steps.append(f"colorkey={key_color}:{similarity}:{blend}")
            steps.append("format=rgba")
            opacity = ov.get("opacity")
            if opacity is not None:
                steps.append(f"colorchannelmixer=aa={float(opacity)}")
            processed = f"[ov{idx}]"
            filter_parts.append(f"{in_stream}{','.join(steps)}{processed}")

            pos = ov.get("position", {})
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            timing = ov.get("timing", {})
            start = float(timing.get("start", 0.0))
            duration = timing.get("duration")
            if duration is not None:
                end = start + float(duration)
                enable = f"between(t,{start},{end})"
            else:
                enable = f"gte(t,{start})"

            if mode == "blend":
                blend_mode = ov.get("blend_mode", "screen")
                filter_parts.append(
                    f"{prev_stream}{processed}blend=all_mode={blend_mode}:enable='{enable}'[tmp{idx}]"
                )
            else:
                filter_parts.append(
                    f"{prev_stream}{processed}overlay=x={x}:y={y}:enable='{enable}'[tmp{idx}]"
                )
            prev_stream = f"[tmp{idx}]"

        # 3) Subtitle overlays (add PNG inputs on-the-fly)
        overlay_input_count = len(overlays or [])
        png_added = 0
        for sidx, sub in enumerate(subtitles or []):
            # Compute ffmpeg input index for this PNG (base=0, overlays=1..N, then PNGs)
            png_input_index = overlay_input_count + png_added + 1
            extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                sub.get("text", ""),
                float(sub.get("duration", 0.0)),
                sub.get("line_config", {}),
                in_label=prev_stream.strip("[]"),
                index=png_input_index,
                allow_cuda=self.gpu_overlay_backend == "cuda",
            )
            # Attach PNG input to cmd
            for k, v in extra_input.items():
                cmd.extend([k, v])
            png_added += 1
            # Adjust snippet timing to absolute scene time
            start = float(sub.get("start", 0.0))
            end = start + float(sub.get("duration", 0.0))
            snippet = snippet.replace(
                f"between(t,0,{sub.get('duration')})",
                f"between(t,{start},{end})",
            )
            filter_parts.append(snippet)
            prev_stream = f"[with_subtitle_{png_input_index}]"

        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        # Keep audio stream as-is (no re-encode) for overlay-only operations
        cmd.extend(["-c:a", "copy"])
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg_async(cmd)
        return output_path

    async def apply_subtitle_overlays(
        self, base_video: Path, subtitles: List[Dict[str, Any]]
    ) -> Path:
        """Overlay subtitles on top of ``base_video``.

        Subtitles are applied sequentially so they always appear above any
        foreground overlays or other visuals.  Each subtitle entry must
        contain ``text``, ``duration`` and ``start`` fields, optionally with a
        ``line_config`` dictionary to override style.
        """

        if not subtitles:
            return base_video

        output_path = self.temp_dir / f"{base_video.stem}_sub.mp4"
        # Bound to base duration (static PNG overlays may be looped)
        try:
            base_dur = await get_media_duration(str(base_video))
        except Exception:
            base_dur = None
        cmd: List[str] = [self.ffmpeg_path, "-y", "-nostdin", "-i", str(base_video)]

        filter_parts: List[str] = []
        prev_stream = "[0:v]"

        for idx, sub in enumerate(subtitles):
            extra_input, snippet = await self.subtitle_gen.build_subtitle_overlay(
                sub["text"],
                sub["duration"],
                sub.get("line_config", {}),
                in_label=prev_stream.strip("[]"),
                index=idx + 1,
                allow_cuda=self.gpu_overlay_backend == "cuda",
            )
            for k, v in extra_input.items():
                cmd.extend([k, v])

            start = float(sub["start"])
            end = start + float(sub["duration"])
            snippet = snippet.replace(
                f"between(t,0,{sub['duration']})", f"between(t,{start},{end})"
            )
            filter_parts.append(snippet)
            prev_stream = f"[with_subtitle_{idx + 1}]"

        cmd.extend(self._thread_flags())
        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex, "-map", prev_stream, "-map", "0:a?"])
        cmd.extend(self.video_params.to_ffmpeg_opts(self.hw_kind))
        # Keep audio stream as-is (no re-encode) when only adding subtitle overlays
        cmd.extend(["-c:a", "copy"])
        if base_dur and base_dur > 0:
            cmd.extend(["-t", f"{base_dur:.3f}"])
        cmd.append(str(output_path))

        await _run_ffmpeg_async(cmd)
        return output_path
