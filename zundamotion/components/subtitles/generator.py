import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from PIL import Image

from ...cache import CacheManager

from ...utils.ffmpeg_capabilities import has_cuda_filters, is_nvenc_available
from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.logger import logger
from ...utils.subtitle_text import normalize_subtitle_text
from .effects import resolve_subtitle_effects
from .png import SubtitlePNGRenderer


class SubtitleGenerator:
    def __init__(self, config: Dict[str, Any], cache_manager: CacheManager):
        self.subtitle_config = config.get("subtitle", {})
        self.png_renderer = SubtitlePNGRenderer(cache_manager)

    async def build_subtitle_overlay(
        self,
        text: str,
        duration: float,
        line_config: Dict[str, Any],
        in_label: str,
        index: int,
        force_cpu: bool = False,
        allow_cuda: bool | None = None,
        existing_png_path: str | None = None,
    ) -> Tuple[Dict[str, Any], str]:
        """
        Returns:
            extra_input: {"-loop": "1", "-i": <png>}
            filter_snippet: FFmpeg filter graph snippet
        """
        text = normalize_subtitle_text(text)

        style = self.subtitle_config.copy()
        style.update(line_config)
        if "subtitle" in line_config and isinstance(line_config["subtitle"], dict):
            style.update(line_config["subtitle"])

        effects_cfg_raw = style.get("effects")
        if effects_cfg_raw is None:
            effects_cfg: Optional[Iterable[Any]] = None
        elif isinstance(effects_cfg_raw, (list, tuple)):
            effects_cfg = effects_cfg_raw
        else:
            effects_cfg = [effects_cfg_raw]

        style_for_render = dict(style)
        style_for_render.pop("effects", None)

        png_path: Path
        dims: Dict[str, int] = {"w": 0, "h": 0}
        # Reuse pre-generated subtitle PNG if provided (e.g., on fallback retry)
        if existing_png_path:
            p = Path(existing_png_path)
            if p.exists():
                png_path = p
                try:
                    with Image.open(png_path) as img:
                        dims = {"w": img.width, "h": img.height}
                except Exception:
                    png_path, dims = await self.png_renderer.render(text, style_for_render)
            else:
                png_path, dims = await self.png_renderer.render(text, style_for_render)
        else:
            png_path, dims = await self.png_renderer.render(text, style_for_render)

        # 位置式（あなたの置換ロジックはそのまま活かす）
        # Convert drawtext-style expr to overlay(_cuda) variables
        def convert_expr(expr: str) -> str:
            # Preserve text_* first using placeholders to avoid nested replacements
            expr = expr.replace("text_w", "{OVERLAY_W}").replace("text_h", "{OVERLAY_H}")
            # drawtext: w/h => main width/height; overlay: W/H are main dims
            # Replace lone 'w'/'h' tokens with 'W'/'H'
            expr = re.sub(r"(?<![A-Za-z_])w(?![A-Za-z_])", "W", expr)
            expr = re.sub(r"(?<![A-Za-z_])h(?![A-Za-z_])", "H", expr)
            # Uppercase W/H can be kept as-is for overlay filters
            # Restore placeholders to overlay input dims (w/h)
            expr = expr.replace("{OVERLAY_W}", "w").replace("{OVERLAY_H}", "h")
            return expr

        y_expr = convert_expr(style.get("y", "H-100"))
        x_expr = convert_expr(style.get("x", "(W-w)/2"))

        effect_snippet = resolve_subtitle_effects(
            effects=effects_cfg,
            input_label=f"{index}:v",
            base_x_expr=x_expr,
            base_y_expr=y_expr,
            duration=duration,
            width=int(dims.get("w", 0) or 0),
            height=int(dims.get("h", 0) or 0),
            index=index,
        )

        effect_filters: list[str] = []
        overlay_stream_label = f"[{index}:v]"
        if effect_snippet:
            effect_filters.extend(effect_snippet.filter_chain)
            overlay_stream_label = f"[{effect_snippet.output_label}]"
            if "x" in effect_snippet.overlay_kwargs:
                x_expr = effect_snippet.overlay_kwargs["x"]
            if "y" in effect_snippet.overlay_kwargs:
                y_expr = effect_snippet.overlay_kwargs["y"]
            logger.debug(
                "[SubtitleEffects] Applied effects to subtitle index=%s label=%s chain=%s kwargs=%s",
                index,
                effect_snippet.output_label,
                effect_snippet.filter_chain,
                effect_snippet.overlay_kwargs,
            )

        # CUDA 使用可否は VideoRenderer 側の判定結果（allow_cuda）を優先
        global_mode = get_hw_filter_mode()
        if global_mode == "cpu":
            use_cuda = False
        elif allow_cuda is None:
            use_cuda = (not force_cpu) and await is_nvenc_available() and await has_cuda_filters()
        else:
            use_cuda = (not force_cpu) and bool(allow_cuda)

        extra_input = {"-loop": "1", "-i": str(png_path)}

        if use_cuda:
            # GPU: メイン側/字幕側ともに GPU フレームへ upload → overlay_cuda
            # in_label が CPU のまま来ても自衛的に GPU 化（重複しても副作用なし）
            filter_parts: list[str] = [
                f"[{in_label}]format=nv12,hwupload_cuda[bg_gpu_{index}]",
            ]
            filter_parts.extend(effect_filters)
            rgba_label = f"sub_rgba_{index}"
            filter_parts.append(f"{overlay_stream_label}format=rgba[{rgba_label}]")
            filter_parts.append(f"[{rgba_label}]hwupload_cuda[sub_gpu_{index}]")
            filter_parts.append(
                f"[bg_gpu_{index}][sub_gpu_{index}]overlay_cuda="
                f"x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
                f"[with_subtitle_{index}]"
            )
            filter_snippet = ';'.join(filter_parts)
        else:
            # CPU fallback
            filter_parts = list(effect_filters)
            filter_parts.append(
                f"[{in_label}]{overlay_stream_label}overlay="
                f"x='{x_expr}':y='{y_expr}':enable='between(t,0,{duration})'"
                f"[with_subtitle_{index}]"
            )
            filter_snippet = ';'.join(filter_parts)

        return extra_input, filter_snippet
