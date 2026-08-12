"""Build the optional subtitle overlay stage for one clip."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ...utils.logger import logger
from .clip_image_input import append_looped_image_input
from ...utils.subtitle_text import is_effective_subtitle_text
from .clip_filter_policy import ClipFilterPolicy
from .clip_input_collection import ClipInputCollection

if TYPE_CHECKING:
    from .renderer import VideoRenderer


async def append_subtitle_overlay(
    *, renderer: "VideoRenderer", inputs: ClipInputCollection,
    subtitle_text: Optional[str], subtitle_line_config: Optional[Dict[str, Any]],
    subtitle_png_path: Optional[Path], duration: float,
    current_video_stream: str, policy: ClipFilterPolicy,
    force_cpu: bool, parts: List[str],
) -> tuple[str, Optional[Path], Any]:
    if not is_effective_subtitle_text(subtitle_text):
        return current_video_stream, subtitle_png_path, None
    snippet = None
    try:
        index = len(inputs.input_layers)
        extra_inputs, snippet = await renderer.subtitle_gen.build_subtitle_overlay(
            str(subtitle_text), duration, subtitle_line_config or {},
            in_label=current_video_stream.strip("[]"), index=index,
            force_cpu=force_cpu, allow_cuda=policy.use_cuda_filters,
            existing_png_path=str(subtitle_png_path) if subtitle_png_path else None,
        )
        if not (isinstance(extra_inputs, dict) and extra_inputs.get("-i")):
            logger.warning("Unexpected subtitle extra inputs: %s. Skipping subtitle overlay.", extra_inputs)
            return current_video_stream, subtitle_png_path, None
        loop_value, png_path = extra_inputs.get("-loop", "1"), extra_inputs["-i"]
        append_looped_image_input(
            inputs.cmd,
            Path(png_path).resolve(),
            duration=duration,
            fps=renderer.video_params.fps,
            loop=loop_value,
        )
        inputs.input_layers.append({"type": "video", "index": index})
        try:
            subtitle_png_path = Path(png_path)
        except Exception:
            pass
        if snippet:
            parts.append(snippet)
            current_video_stream = f"[with_subtitle_{index}]"
    except Exception as exc:
        logger.warning("Failed to build subtitle overlay snippet: %s", exc)
        snippet = None
    return current_video_stream, subtitle_png_path, snippet
