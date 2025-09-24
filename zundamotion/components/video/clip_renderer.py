"""クリップ描画処理を VideoRenderer から切り出したモジュール。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...exceptions import PipelineError
from ...utils.ffmpeg_audio import has_audio_stream
from ...utils.ffmpeg_hw import get_hw_filter_mode, get_profile_flags, set_hw_filter_mode
from ...utils.ffmpeg_ops import calculate_overlay_position, normalize_media
from ...utils.ffmpeg_capabilities import _dump_cuda_diag_once
from ...utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from ...utils.logger import logger

if TYPE_CHECKING:
    from .renderer import VideoRenderer


async def render_clip(
    renderer: "VideoRenderer",
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
    audio_delay: float = 0.0,
) -> Optional[Path]:
    """
    drawtext 全廃版:
    - 字幕は SubtitleGenerator の GPU/CPU スニペットを使用し、PNG 事前生成入力（-loop 1 -i png）→ overlay
    - 位置/スタイルは line_config の subtitle 設定 + デフォルトを反映
    """
    output_path = renderer.temp_dir / f"{output_filename}.mp4"
    width = renderer.video_params.width
    height = renderer.video_params.height
    fps = renderer.video_params.fps

    import time as _time
    _t0 = _time.time()
    logger.info("[Video] Rendering clip -> %s", output_path.name)

    cmd: List[str] = [
        renderer.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        *get_profile_flags(),
    ]
    cmd.extend(renderer.ffmpeg_thread_flags())

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
                bg_path.parent.resolve() == renderer.temp_dir.resolve()
                and bg_path.name.startswith("scene_bg_")
            )
            should_skip_normalize = normalized_hint or is_temp_scene_bg

            if not should_skip_normalize:
                # 正規化（失敗時は as-is）
                try:
                    key_data = {
                        "input_path": str(bg_path.resolve()),
                        "video_params": renderer.video_params.__dict__,
                        "audio_params": renderer.audio_params.__dict__,
                    }

                    async def _normalize_bg_creator(temp_output_path: Path) -> Path:
                        return await normalize_media(
                            input_path=bg_path,
                            video_params=renderer.video_params,
                            audio_params=renderer.audio_params,
                            cache_manager=renderer.cache_manager,
                            ffmpeg_path=renderer.ffmpeg_path,
                        )

                    # cache_manager.get_or_create は Path を返すことを期待
                    bg_path_result = await renderer.cache_manager.get_or_create(
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
                        video_params=renderer.video_params,
                        audio_params=renderer.audio_params,
                        cache_manager=renderer.cache_manager,
                        ffmpeg_path=renderer.ffmpeg_path,
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
                scaled_path = await renderer.face_cache.get_scaled_overlay(
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
        renderer.has_cuda_filters
        and renderer.hw_kind == "nvenc"
        and (renderer.gpu_overlay_experimental or not uses_alpha_overlay)
        and not _force_cpu
        and global_mode != "cpu"
    )
    # Even when alpha overlays exist, allow GPU scaling of background only to reduce CPU work
    # Config gate for hybrid path
    allow_gpu_scale_only_cfg = bool(
        renderer.config.get("video", {}).get("gpu_scale_with_cpu_overlay", True)
    )
    global_mode = get_hw_filter_mode()
    # Allow hybrid path in non-CPU mode as before; additionally, if CPU mode
    # is active due to overlay failures, permit scale-only when the smoke passed.
    allow_in_cpu_mode = renderer.cuda_scale_only_ok
    scale_only_available = bool(renderer.scale_only_backend) or renderer.has_gpu_scale or renderer.has_cuda_filters
    use_gpu_scale_only = (
        (not use_cuda_filters)
        and scale_only_available
        and renderer.hw_kind == "nvenc"
        and allow_gpu_scale_only_cfg
        and (not _force_cpu)
        and ((global_mode != "cpu") or allow_in_cpu_mode)
    )
    if use_cuda_filters:
        logger.info(
            "[Filters] CUDA path: scaling/overlay on GPU (no RGBA overlays)"
        )
        try:
            renderer.path_counters["cuda_overlay"] += 1
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
                renderer.path_counters["gpu_scale_only"] += 1
            except Exception:
                pass
        elif renderer.hw_kind == "nvenc" and uses_alpha_overlay:
            logger.info(
                "[Filters] CPU path: RGBA overlays detected; forcing CPU overlays while keeping NVENC encoding"
            )
            try:
                renderer.path_counters["cpu"] += 1
            except Exception:
                pass
        else:
            logger.info("[Filters] CPU path: using CPU filters for scaling/overlay")
            try:
                renderer.path_counters["cpu"] += 1
            except Exception:
                pass

    # --- Filter Graph -------------------------------------------------------
    filter_complex_parts: List[str] = []

    # 背景スケール
    pre_scaled = bool(background_config.get("pre_scaled", False))
    fps_part = f",fps={fps}" if renderer.apply_fps_filter else ""
    if pre_scaled:
        # すでに width/height/fps に整形済みのベース映像（シーンベース）
        # 無駄な再スケールを避けるため passthrough
        filter_complex_parts.append("[0:v]null[bg]")
    else:
        if use_cuda_filters:
            # CUDA: 一旦GPUへ上げてスケール＋fps。RGBA→NV12 変換はCUDA側に任せる。
            filter_complex_parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
            filter_complex_parts.append(
                f"[hw_bg_in]{renderer.scale_filter}={width}:{height}{(f',fps={fps}' if renderer.apply_fps_filter else '')}[bg]"
            )
        elif use_gpu_scale_only:
            # Hybrid: scale on GPU then download for CPU overlays
            if renderer.scale_only_backend == "opencl":
                filter_complex_parts.append("[0:v]format=rgba,hwupload[hw_bg_in]")
                filter_complex_parts.append(
                    f"[hw_bg_in]scale_opencl={width}:{height}{(f',fps={fps}' if renderer.apply_fps_filter else '')}[bg_gpu_scaled]"
                )
                filter_complex_parts.append(
                    "[bg_gpu_scaled]hwdownload,format=rgba[bg]"
                )
            else:
                filter_complex_parts.append("[0:v]format=rgba,hwupload_cuda[hw_bg_in]")
                filter_complex_parts.append(
                    f"[hw_bg_in]{renderer.scale_filter}={width}:{height}{(f',fps={fps}' if renderer.apply_fps_filter else '')}[bg_gpu_scaled]"
                )
                filter_complex_parts.append(
                    "[bg_gpu_scaled]hwdownload,format=rgba[bg]"
                )
        elif renderer.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode):
            # OpenCL: 背景のスケールはCPUで行い、その後にGPUへアップロードして合成に回す
            filter_complex_parts.append(
                f"[0:v]scale={width}:{height}:flags={renderer.scale_flags}{fps_part}[bg]"
            )
            filter_complex_parts.append("[bg]format=rgba,hwupload[bg_gpu]")
            current_video_stream = "[bg_gpu]"
        else:
            filter_complex_parts.append(
                f"[0:v]scale={width}:{height}:flags={renderer.scale_flags}{fps_part}[bg]"
            )
    if not (renderer.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode)):
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
                    f"[{insert_ffmpeg_index}:v]format=rgba,hwupload_cuda,{renderer.scale_filter}=iw*{scale}:ih*{scale}[insert_scaled]"
                )
            else:
                filter_complex_parts.append(
                    f"[{insert_ffmpeg_index}:v]format=nv12,hwupload_cuda,{renderer.scale_filter}=iw*{scale}:ih*{scale}[insert_scaled]"
                )
            overlay_streams.append("[insert_scaled]")
            overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
        elif renderer.gpu_overlay_backend == "opencl" and not _force_cpu and (get_hw_filter_mode() != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode):
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
                f"[{insert_ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}:flags={renderer.scale_flags}[insert_scaled]"
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
        scale = float(
            char_effective_scale.get(i, float(char_config.get("scale", 1.0)))
        )
        anchor = char_config.get("anchor", "bottom_center")
        pos = char_config.get("position", {"x": "0", "y": "0"})
        x_base, y_base = calculate_overlay_position(
            "W",
            "H",
            "w",
            "h",
            anchor,
            str(pos.get("x", "0")),
            str(pos.get("y", "0")),
        )
        enter_duration = 0.3
        try:
            enter_duration = float(char_config.get("enter_duration", 0.3))
        except Exception:
            enter_duration = 0.3
        leave_duration = 0.3
        try:
            leave_duration = float(char_config.get("leave_duration", 0.3))
        except Exception:
            leave_duration = 0.3
        enter_val = char_config.get("enter")
        leave_val = char_config.get("leave")
        enter_effect = ""
        leave_effect = ""
        if enter_val:
            enter_effect = (
                str(enter_val).lower() if not isinstance(enter_val, bool) else "fade"
            )
        if leave_val:
            leave_effect = (
                str(leave_val).lower() if not isinstance(leave_val, bool) else "fade"
            )
        fade = ""
        x_expr, y_expr = x_base, y_base
        if enter_effect == "fade":
            fade += f",fade=t=in:st=0:d={enter_duration}:alpha=1"
        if leave_effect == "fade":
            fade += (
                f",fade=t=out:st={max(0.0, duration - leave_duration)}:d={leave_duration}:alpha=1"
            )
        if enter_effect == "slide_left":
            x_expr = (
                f"if(lt(t,{enter_duration}), -w+({x_base}+w)*t/{enter_duration}, {x_expr})"
            )
        elif enter_effect == "slide_right":
            x_expr = (
                f"if(lt(t,{enter_duration}), W+({x_base}-W)*t/{enter_duration}, {x_expr})"
            )
        elif enter_effect == "slide_top":
            y_expr = (
                f"if(lt(t,{enter_duration}), -h+({y_base}+h)*t/{enter_duration}, {y_expr})"
            )
        elif enter_effect == "slide_bottom":
            y_expr = (
                f"if(lt(t,{enter_duration}), H+({y_base}-H)*t/{enter_duration}, {y_expr})"
            )
        leave_start = max(0.0, duration - leave_duration)
        if leave_effect == "slide_left":
            x_expr = (
                f"if(gt(t,{leave_start}), {x_base} + (-w-{x_base})*(t-{leave_start})/{leave_duration}, {x_expr})"
            )
        elif leave_effect == "slide_right":
            x_expr = (
                f"if(gt(t,{leave_start}), {x_base} + (W-{x_base})*(t-{leave_start})/{leave_duration}, {x_expr})"
            )
        elif leave_effect == "slide_top":
            y_expr = (
                f"if(gt(t,{leave_start}), {y_base} + (-h-{y_base})*(t-{leave_start})/{leave_duration}, {y_expr})"
            )
        elif leave_effect == "slide_bottom":
            y_expr = (
                f"if(gt(t,{leave_start}), {y_base} + (H-{y_base})*(t-{leave_start})/{leave_duration}, {y_expr})"
            )

        # ffmpegのfiltergraphでは`,`がフィルタ区切りと解釈されるため
        # 式中に含まれるカンマをエスケープする
        def _esc_commas(expr: str) -> str:
            return expr.replace(",", "\\,")

        x_expr = _esc_commas(x_expr)
        y_expr = _esc_commas(y_expr)

        if use_cuda_filters:
            # 想定上ここには来ない（uses_alpha_overlay True → CPU 合成）
            filter_complex_parts.append(
                f"[{ffmpeg_index}:v]format=rgba{fade},hwupload_cuda,{renderer.scale_filter}=iw*{scale}:ih*{scale}[char_scaled_{i}]"
            )
            overlay_streams.append(f"[char_scaled_{i}]")
            overlay_filters.append(f"overlay_cuda=x={x_expr}:y={y_expr}")
        elif renderer.gpu_overlay_backend == "opencl" and not _force_cpu and (
            get_hw_filter_mode() != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode
        ):
            # 前段で Pillow による事前スケールが有効な場合、scale は 1.0 に縮退
            if os.environ.get("CHAR_CACHE_DISABLE", "0") != "1":
                try:
                    from .face_overlay_cache import FaceOverlayCache

                    cache = renderer.face_cache  # same cache instance
                    # 事前スケール済み PNG を別入力として差し替え（ffmpeg_index の実入力を置換）
                    filter_complex_parts.append(
                        f"[{ffmpeg_index}:v]format=rgba{fade},hwupload[char_gpu_{i}]"
                    )
                    overlay_streams.append(f"[char_gpu_{i}]")
                    overlay_filters.append(
                        f"overlay_opencl=x={x_expr}:y={y_expr}"
                    )
                    char_effective_scale[i] = 1.0
                except Exception:
                    # フォールバック: CPU スケール→GPUへ
                    filter_complex_parts.append(
                        f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale},format=rgba{fade},hwupload[char_gpu_{i}]"
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
                    f"[{ffmpeg_index}:v]format=rgba{fade}[char_scaled_{i}]"
                )
            else:
                filter_complex_parts.append(
                    f"[{ffmpeg_index}:v]scale=iw*{scale}:ih*{scale}:flags={renderer.scale_flags},format=rgba{fade}[char_scaled_{i}]"
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
                vw, vh = renderer.video_params.width, renderer.video_params.height
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
                "enter_effect": enter_effect,
                "enter_duration": f"{enter_duration:.3f}",
                "leave_effect": leave_effect,
                "fade": fade,
                "scale_orig": str(scale_orig),
                "scale_eff": str(scale),
                "x_num": str(int(round(xn))),
                "y_num": str(int(round(yn))),
                "expression": str(char_expression),
            }
        except Exception:
            pass

    # Helper: build enable expr from segments
    def _enable_expr(
        segments: List[Dict[str, Any]], *, start_offset: float = 0.0
    ) -> Optional[str]:
        try:
            parts: List[str] = []
            for seg in segments:
                end = float(seg.get("end", 0))
                start = float(seg.get("start", 0))
                if start_offset > 0.0:
                    if end <= start_offset:
                        continue
                    if start < start_offset:
                        start = start_offset
                if end <= start:
                    continue
                parts.append(f"between(t,{start:.3f},{end:.3f})")
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
                        enter_val = ch.get("enter")
                        enter_effect = (
                            str(enter_val).lower()
                            if enter_val and not isinstance(enter_val, bool)
                            else ("fade" if enter_val else "")
                        )
                        enter_dur = 0.0
                        try:
                            enter_dur = float(ch.get("enter_duration", 0.0))
                        except Exception:
                            enter_dur = 0.0
                        placement = {
                            "x_expr": x_expr,
                            "y_expr": y_expr,
                            "scale": str(scale),
                            "enter_effect": enter_effect,
                            "enter_duration": f"{enter_dur:.3f}",
                            "expression": str(ch.get("expression", "default")),
                        }
                        break
            except Exception:
                placement = None

        if placement:
            scale = placement.get("scale_orig") or placement.get("scale") or "1.0"
            x_fix = placement.get("x_num") or placement.get("x_expr") or "0"
            y_fix = placement.get("y_num") or placement.get("y_expr") or "0"
            enter_eff = str(placement.get("enter_effect") or "")
            enter_duration_val = 0.0
            try:
                enter_duration_val = float(placement.get("enter_duration", 0.0) or 0.0)
            except Exception:
                enter_duration_val = 0.0
            fade_str = placement.get("fade", "")
            use_dynamic = enter_eff.startswith("slide")
            x_pos = placement.get("x_expr") if use_dynamic else x_fix
            y_pos = placement.get("y_expr") if use_dynamic else y_fix

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
                    cached = await renderer.face_cache.get_scaled_overlay(path, float(scale_val), thr)
                    idx = _add_image_input(cached)
                    if idx is not None:
                        preprocessed_inputs.add(idx)
                    return idx
                except Exception:
                    return _add_image_input(path)

            def _prep_overlay(idx: int, scale_val: float, out_label: str, fade_add: str = "") -> None:
                if idx in preprocessed_inputs:
                    filter_complex_parts.append(
                        f"[{idx}:v]format=rgba{fade_add}[{out_label}]"
                    )
                else:
                    filter_complex_parts.append(
                        f"[{idx}:v]format=rgba{fade_add},scale=iw*{scale_val}:ih*{scale_val}[{out_label}]"
                    )

            # Eyes: show only 'close' during blink to avoid doubling base open eyes
            eyes_segments = face_anim.get("eyes") or []
            eyes_close_expr = _enable_expr(eyes_segments) if eyes_segments else None
            if eyes_close.exists() and eyes_close_expr:
                idx = await _add_preprocessed_overlay(eyes_close, float(scale))
                if idx is not None:
                    label = f"eyes_close_scaled_{idx}"
                    _prep_overlay(idx, float(scale), label, fade_str)
                    overlay_streams.append(f"[{label}]")
                    overlay_filters.append(
                        f"overlay=x={x_pos}:y={y_pos}:enable='{eyes_close_expr}'"
                    )

            # Mouth: overlay only 'half'/'open' states; avoid baseline 'close' to prevent doubling
            mouth_segments = face_anim.get("mouth") or []
            half_expr = open_expr = None
            if isinstance(mouth_segments, list) and mouth_segments:
                half_segments = [s for s in mouth_segments if s.get("state") == "half"]
                open_segments = [s for s in mouth_segments if s.get("state") == "open"]
                delayed_effects = {
                    "fade",
                    "slide_left",
                    "slide_right",
                    "slide_top",
                    "slide_bottom",
                }
                requires_delay = enter_eff in delayed_effects and enter_duration_val > 0.0
                start_offset = enter_duration_val if requires_delay else 0.0
                if start_offset > 0.0:
                    logger.debug(
                        "[FaceAnim] Deferring mouth animation until %.2fs due to enter=%s",
                        start_offset,
                        enter_eff,
                    )
                if half_segments:
                    half_expr = _enable_expr(half_segments, start_offset=start_offset)
                if open_segments:
                    open_expr = _enable_expr(open_segments, start_offset=start_offset)

            if mouth_half.exists() and half_expr:
                idx = await _add_preprocessed_overlay(mouth_half, float(scale))
                if idx is not None:
                    label = f"mouth_half_scaled_{idx}"
                    _prep_overlay(idx, float(scale), label, fade_str)
                    overlay_streams.append(f"[{label}]")
                    overlay_filters.append(
                        f"overlay=x={x_pos}:y={y_pos}:enable='{half_expr}'"
                    )

            if mouth_open.exists() and open_expr:
                idx = await _add_preprocessed_overlay(mouth_open, float(scale))
                if idx is not None:
                    label = f"mouth_open_scaled_{idx}"
                    _prep_overlay(idx, float(scale), label, fade_str)
                    overlay_streams.append(f"[{label}]")
                    overlay_filters.append(
                        f"overlay=x={x_pos}:y={y_pos}:enable='{open_expr}'"
                    )

    # オーバーレイを連結
    if overlay_streams:
        # OpenCL 使用時は overlay フィルタ名を置換
        if renderer.gpu_overlay_backend == "opencl" and not _force_cpu and get_hw_filter_mode() != "cpu":
            overlay_filters = [
                (f.replace("overlay=", "overlay_opencl=") if f.startswith("overlay=") else f)
                for f in overlay_filters
            ]
            try:
                renderer.path_counters["opencl_overlay"] += 1
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
        if renderer.gpu_overlay_backend == "opencl" and not _force_cpu and get_hw_filter_mode() != "cpu":
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
            extra_inputs, subtitle_snippet = await renderer.subtitle_gen.build_subtitle_overlay(
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
    if used_any_cuda and renderer.hw_kind == "nvenc":
        # GPU内完結: そのまま NVENC に渡す（CPUへの hwdownload を回避）
        filter_complex_parts.append(f"{current_video_stream}null[final_v]")
    else:
        # CPU 経路（または NVENC 以外）は従来通り yuv420p へ確定
        filter_complex_parts.append(f"{current_video_stream}format=yuv420p[final_v]")

    # --- Audio --------------------------------------------------------------
    # has_audio_stream is async; ensure we await it to get a boolean
    has_speech_audio = await has_audio_stream(str(audio_path))

    audio_src = None
    if insert_config and insert_audio_index != -1:
        volume = float(insert_config.get("volume", 1.0))
        filter_complex_parts.append(
            f"[{insert_audio_index}:a]volume={volume}[insert_audio_vol]"
        )
        if has_speech_audio:
            filter_complex_parts.append(
                f"[{speech_audio_index}:a][insert_audio_vol]amix=inputs=2:duration=longest:dropout_transition=0[mixed_a]"
            )
            audio_src = "[mixed_a]"
        else:
            audio_src = "[insert_audio_vol]"
    else:
        if has_speech_audio:
            audio_src = f"[{speech_audio_index}:a]"
        else:
            filter_complex_parts.append(
                f"anullsrc=channel_layout=stereo:sample_rate={renderer.audio_params.sample_rate}[sil]"
            )
            audio_src = "[sil]"

    delay_ms = max(0, int(audio_delay * 1000))
    filter_complex_parts.append(
        f"{audio_src}adelay={delay_ms}:all=1,apad=pad_dur={duration}[final_a]"
    )
    audio_map = "[final_a]"

    # --- Assemble & Run -----------------------------------------------------
    cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
    cmd.extend(["-map", "[final_v]", "-map", audio_map])
    cmd.extend(["-t", str(duration)])
    cmd.extend(renderer.video_params.to_ffmpeg_opts(None if _force_cpu else renderer.hw_kind))
    cmd.extend(renderer.audio_params.to_ffmpeg_opts())
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
                await _dump_cuda_diag_once(renderer.ffmpeg_path)
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
                return await renderer.render_clip(
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
                    audio_delay=audio_delay,
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
