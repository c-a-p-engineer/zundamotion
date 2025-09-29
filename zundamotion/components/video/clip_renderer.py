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
from .clip.characters import collect_character_inputs, build_character_overlays
from .clip.face import apply_face_overlays

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
    char_inputs = await collect_character_inputs(
        renderer=renderer,
        characters_config=characters_config,
        cmd=cmd,
        input_layers=input_layers,
    )
    character_indices = char_inputs.indices
    char_effective_scale = char_inputs.effective_scales
    any_character_visible = char_inputs.any_visible
    char_metadata = char_inputs.metadata

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
    use_opencl_overlays = (
        renderer.gpu_overlay_backend == "opencl"
        and not _force_cpu
        and (get_hw_filter_mode() != "cpu" or renderer.allow_opencl_overlay_in_cpu_mode)
    )
    char_overlay_placement = build_character_overlays(
        renderer=renderer,
        characters_config=characters_config,
        duration=duration,
        character_indices=character_indices,
        char_effective_scale=char_effective_scale,
        filter_complex_parts=filter_complex_parts,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
        use_cuda_filters=use_cuda_filters,
        use_opencl=use_opencl_overlays,
        metadata=char_metadata,
    )

    # Face animation overlays (mouth/eyes) for the speaking character
    await apply_face_overlays(
        renderer=renderer,
        face_anim=face_anim,
        subtitle_line_config=subtitle_line_config,
        char_overlay_placement=char_overlay_placement,
        duration=duration,
        cmd=cmd,
        input_layers=input_layers,
        filter_complex_parts=filter_complex_parts,
        overlay_streams=overlay_streams,
        overlay_filters=overlay_filters,
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
