"""Scene関連のレンダリング処理を分離したユーティリティ。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...exceptions import PipelineError
from ...utils.ffmpeg_hw import get_profile_flags
from ...utils.ffmpeg_ops import (
    BACKGROUND_FIT_STRETCH,
    DEFAULT_BACKGROUND_ANCHOR,
    DEFAULT_BACKGROUND_FILL_COLOR,
    build_background_filter_complex,
    build_background_fit_steps,
    calculate_overlay_position,
    compose_background_filter_expression,
    normalize_media,
)
from ...utils.ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .clip.effects import resolve_background_effects, resolve_screen_effects

if TYPE_CHECKING:
    from .renderer import VideoRenderer


def _to_offset_expr(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "0"
    return str(value)


def _extract_background_layout(
    renderer: "VideoRenderer", background_config: Dict[str, Any]
) -> tuple[str, str, str, str, str, Dict[str, str]]:
    video_defaults = renderer.config.get("video", {}) or {}
    background_defaults = renderer.config.get("background", {}) or {}
    fit = str(
        background_config.get(
            "fit",
            video_defaults.get("background_fit", BACKGROUND_FIT_STRETCH),
        )
    ).lower()
    fill = str(
        background_config.get(
            "fill_color",
            background_defaults.get("fill_color", DEFAULT_BACKGROUND_FILL_COLOR),
        )
        or DEFAULT_BACKGROUND_FILL_COLOR
    )
    anchor = (
        background_config.get(
            "anchor",
            background_defaults.get("anchor", DEFAULT_BACKGROUND_ANCHOR),
        )
        or DEFAULT_BACKGROUND_ANCHOR
    )
    raw_position = background_config.get("position")
    if not isinstance(raw_position, dict):
        raw_position = background_defaults.get("position")
        if not isinstance(raw_position, dict):
            raw_position = {}
    offset_x = _to_offset_expr(raw_position.get("x"))
    offset_y = _to_offset_expr(raw_position.get("y"))
    position_exprs = {"x": offset_x, "y": offset_y}
    return fit, fill, str(anchor), offset_x, offset_y, position_exprs


async def render_scene_base(
    renderer: "VideoRenderer",
    background_config: Dict[str, Any],
    duration: float,
    output_filename: str,
) -> Path:
    """背景のみのシーンベース映像を生成する。"""
    bg_type = background_config.get("type")
    bg_path = Path(background_config.get("path"))
    fit, fill_color, anchor, offset_x, offset_y, position_exprs = _extract_background_layout(
        renderer, background_config
    )

    if bg_type == "video":
        return await render_looped_background_video(
            renderer,
            str(bg_path),
            duration,
            output_filename,
            fit_mode=fit,
            fill_color=fill_color,
            anchor=anchor,
            position=position_exprs,
        )

    line_cfg: Dict[str, Any] = {}
    base_path = await render_wait_clip(
        renderer,
        duration=duration,
        background_config={
            "type": "image",
            "path": str(bg_path),
            "fit": fit,
            "fill_color": fill_color,
            "anchor": anchor,
            "position": position_exprs,
        },
        output_filename=output_filename,
        line_config=line_cfg,
    )
    if base_path is None:
        raise PipelineError("Failed to render scene base from image background.")
    return base_path


async def render_scene_base_composited(
    renderer: "VideoRenderer",
    background_config: Dict[str, Any],
    duration: float,
    output_filename: str,
    overlays: List[Dict[str, Any]],
) -> Path:
    """背景と静的オーバーレイを合成したシーンベース映像を生成する。"""
    output_path = renderer.temp_dir / f"{output_filename}.mp4"
    width = renderer.video_params.width
    height = renderer.video_params.height
    fps = renderer.video_params.fps

    cmd: List[str] = [
        renderer.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        *get_profile_flags(),
    ]
    cmd.extend(renderer.ffmpeg_thread_flags())
    cmd.extend(get_profile_flags())

    bg_type = background_config.get("type")
    bg_path = Path(background_config.get("path"))
    fit, fill_color, anchor, offset_x, offset_y, position_exprs = _extract_background_layout(
        renderer, background_config
    )
    if bg_type == "video":
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
                    fit_mode=fit,
                    fill_color=fill_color,
                    anchor=anchor,
                    position=position_exprs,
                    scale_flags=renderer.scale_flags,
                )

            bg_path = await renderer.cache_manager.get_or_create(
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

    for ov in overlays:
        cmd.extend(["-loop", "1", "-i", str(Path(ov["path"]).resolve())])

    filter_parts: List[str] = []
    steps = build_background_fit_steps(
        width=width,
        height=height,
        fit_mode=fit,
        fill_color=fill_color,
        anchor=anchor,
        offset_x=offset_x,
        offset_y=offset_y,
        scale_flags=renderer.scale_flags,
    )
    cpu_chain = build_background_filter_complex(
        input_label="0:v",
        output_label="bg",
        steps=steps,
        apply_fps=renderer.apply_fps_filter,
        fps=fps,
    )
    if bg_type != "video" and cpu_chain:
        last = cpu_chain[-1]
        prefix, _, _ = last.rpartition("[bg]")
        cpu_chain[-1] = f"{prefix}trim=duration={duration}[bg]"
    filter_parts.extend(cpu_chain)

    chain = "[bg]"
    for i, ov in enumerate(overlays):
        idx = i + 1
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
            f"[{idx}:v]scale=iw*{scale}:ih*{scale}:flags={renderer.scale_flags}[ov_{i}]"
        )
        if i < len(overlays) - 1:
            chain += f"[ov_{i}]overlay=x={x_expr}:y={y_expr}[tmp_{i}];[tmp_{i}]"
        else:
            chain += f"[ov_{i}]overlay=x={x_expr}:y={y_expr}[ov_final]"
    if overlays:
        filter_parts.append(chain)
        final_stream = "[ov_final]"
    else:
        final_stream = "[bg]"

    filter_parts.append(f"{final_stream}format=yuv420p[final_v]")

    cmd.extend(["-filter_complex", ";".join(filter_parts)])
    cmd.extend(["-map", "[final_v]"])
    if bg_type == "video":
        cmd.extend(["-t", str(duration)])
    cmd.extend(renderer.video_params.to_ffmpeg_opts(renderer.hw_kind))
    cmd.extend(["-an"])
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


async def render_wait_clip(
    renderer: "VideoRenderer",
    duration: float,
    background_config: Dict[str, Any],
    output_filename: str,
    line_config: Dict[str, Any],
) -> Optional[Path]:
    output_path = renderer.temp_dir / f"{output_filename}.mp4"
    width = renderer.video_params.width
    height = renderer.video_params.height
    fps = renderer.video_params.fps

    print(f"[Video] Rendering wait clip -> {output_path.name}")

    cmd: List[str] = [
        renderer.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
    ]
    cmd.extend(renderer.ffmpeg_thread_flags())

    bg_path_str = background_config.get("path")
    if not bg_path_str:
        raise ValueError("Background path is missing.")
    bg_path = Path(bg_path_str)
    fit, fill_color, anchor, offset_x, offset_y, position_exprs = _extract_background_layout(
        renderer, background_config
    )

    if background_config.get("type") == "video":
        try:
            normalized_hint = bool(background_config.get("normalized", False))
            is_temp_scene_bg = (
                bg_path.parent.resolve() == renderer.temp_dir.resolve()
                and bg_path.name.startswith("scene_bg_")
            )
            should_skip_normalize = normalized_hint or is_temp_scene_bg

            if not should_skip_normalize:
                try:
                    key_data = {
                        "input_path": str(bg_path.resolve()),
                        "video_params": renderer.video_params.__dict__,
                        "audio_params": renderer.audio_params.__dict__,
                    }

                    async def _normalize_bg_creator_wait(
                        temp_output_path: Path,
                    ) -> Path:
                        return await normalize_media(
                            input_path=bg_path,
                            video_params=renderer.video_params,
                            audio_params=renderer.audio_params,
                            cache_manager=renderer.cache_manager,
                            ffmpeg_path=renderer.ffmpeg_path,
                            fit_mode=fit,
                            fill_color=fill_color,
                            anchor=anchor,
                            position=position_exprs,
                            scale_flags=renderer.scale_flags,
                        )

                    bg_path = await renderer.cache_manager.get_or_create(
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

    cmd.extend(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={renderer.audio_params.sample_rate}",
        ]
    )

    screen_effects = None
    background_effects = None
    try:
        if isinstance(line_config, dict):
            screen_effects = line_config.get("screen_effects")
            background_effects = line_config.get("background_effects")
    except Exception:
        screen_effects = None
        background_effects = None

    filter_parts: List[str] = []
    current_label = "[0:v]"

    pre_scaled = bool(background_config.get("pre_scaled", False))
    if not pre_scaled:
        steps = build_background_fit_steps(
            width=width,
            height=height,
            fit_mode=fit,
            fill_color=fill_color,
            anchor=anchor,
            offset_x=offset_x,
            offset_y=offset_y,
            scale_flags=renderer.scale_flags,
        )
        cpu_chain = build_background_filter_complex(
            input_label="0:v",
            output_label="wait_base",
            steps=steps,
            apply_fps=renderer.apply_fps_filter,
            fps=fps,
        )
        filter_parts.extend(cpu_chain)
        current_label = "[wait_base]"

    bg_snippet = resolve_background_effects(
        effects=background_effects,
        input_label=current_label,
        duration=duration,
        width=width,
        height=height,
        id_prefix="bgw",
    )
    if bg_snippet:
        filter_parts.extend(bg_snippet.filter_chain)
        if bg_snippet.output_label:
            current_label = bg_snippet.output_label

    filter_parts.append(f"{current_label}trim=duration={duration}[wait_trim]")
    current_label = "[wait_trim]"

    screen_snippet = resolve_screen_effects(
        effects=screen_effects,
        input_label=current_label,
        duration=duration,
        width=width,
        height=height,
        id_prefix="screenw",
    )
    if screen_snippet:
        filter_parts.extend(screen_snippet.filter_chain)
        current_label = screen_snippet.output_label

    filter_parts.append(f"{current_label}format=yuv420p[final_v]")

    cmd.extend(["-filter_complex", ";".join(filter_parts)])
    cmd.extend(["-map", "[final_v]", "-map", "1:a"])
    cmd.extend(["-t", str(duration)])
    cmd.extend(renderer.video_params.to_ffmpeg_opts(renderer.hw_kind))
    cmd.extend(renderer.audio_params.to_ffmpeg_opts())
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


async def render_looped_background_video(
    renderer: "VideoRenderer",
    bg_video_path_str: str,
    duration: float,
    output_filename: str,
    *,
    fit_mode: str = BACKGROUND_FIT_STRETCH,
    fill_color: str = DEFAULT_BACKGROUND_FILL_COLOR,
    anchor: str = DEFAULT_BACKGROUND_ANCHOR,
    position: Optional[Dict[str, str]] = None,
) -> Path:
    """指定長で背景動画をループさせた映像を生成する。"""
    output_path = renderer.temp_dir / f"{output_filename}.mp4"
    width = renderer.video_params.width
    height = renderer.video_params.height
    fps = renderer.video_params.fps

    position = position or {}
    offset_x = _to_offset_expr(position.get("x"))
    offset_y = _to_offset_expr(position.get("y"))
    position_exprs = {"x": offset_x, "y": offset_y}

    print(f"[Video] Rendering looped background video -> {output_path.name}")

    cmd: List[str] = [
        renderer.ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
    ]
    cmd.extend(renderer.ffmpeg_thread_flags())

    bg_video_path = Path(bg_video_path_str)
    try:
        key_data = {
            "input_path": str(bg_video_path.resolve()),
            "video_params": renderer.video_params.__dict__,
            "audio_params": renderer.audio_params.__dict__,
        }

        async def _normalize_bg_creator_looped(temp_output_path: Path) -> Path:
            return await normalize_media(
                input_path=bg_video_path,
                video_params=renderer.video_params,
                audio_params=renderer.audio_params,
                cache_manager=renderer.cache_manager,
                ffmpeg_path=renderer.ffmpeg_path,
                fit_mode=fit_mode,
                fill_color=fill_color,
                anchor=anchor,
                position=position_exprs,
                scale_flags=renderer.scale_flags,
            )

        bg_video_path = await renderer.cache_manager.get_or_create(
            key_data=key_data,
            file_name="normalized_looped_bg",
            extension="mp4",
            creator_func=_normalize_bg_creator_looped,
        )
    except Exception as e:
        print(
            f"[Warning] Could not inspect/normalize looped BG video {bg_video_path.name}: {e}. Using as-is."
        )

    steps = build_background_fit_steps(
        width=width,
        height=height,
        fit_mode=fit_mode,
        fill_color=fill_color,
        anchor=anchor,
        offset_x=offset_x,
        offset_y=offset_y,
        scale_flags=renderer.scale_flags,
    )
    vf_core = compose_background_filter_expression(
        steps=steps,
        apply_fps=renderer.apply_fps_filter,
        fps=fps,
    )
    vf = f"{vf_core},format=yuv420p"
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
    cmd.extend(renderer.video_params.to_ffmpeg_opts(renderer.hw_kind))
    cmd.extend(["-an"])
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
