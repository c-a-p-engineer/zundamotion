import re
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from PIL import Image
from PIL import ImageColor
import pysubs2

from ...cache import CacheManager

from ...utils.ffmpeg_capabilities import has_cuda_filters, is_nvenc_available
from ...utils.ffmpeg_hw import get_hw_filter_mode
from ...utils.logger import logger
from ...utils.subtitle_text import normalize_subtitle_text
from .effects import resolve_subtitle_effects
from .png import (
    SubtitlePNGRenderer,
    _estimate_auto_max_chars,
    _background_is_visible,
    _extract_background_config,
    _fits_within_width,
    _load_font_with_fallback,
    _normalize_padding,
    _resolve_rgba,
)


class SubtitleGenerator:
    def __init__(self, config: Dict[str, Any], cache_manager: CacheManager):
        self._config = config
        self.subtitle_config = config.get("subtitle", {})
        self._cache_manager = cache_manager
        self._png_renderer: SubtitlePNGRenderer | None = None

    @property
    def png_renderer(self) -> SubtitlePNGRenderer:
        if self._png_renderer is None:
            self._png_renderer = SubtitlePNGRenderer(self._cache_manager)
        return self._png_renderer

    @staticmethod
    def _normalize_style_aliases(style: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(style or {})
        alias_map = {
            "size": "font_size",
            "color": "font_color",
            "outline": "stroke_color",
            "outline_width": "stroke_width",
        }
        for src, dst in alias_map.items():
            if src in normalized:
                normalized[dst] = normalized[src]
                normalized.pop(src, None)
        return normalized

    def _wrap_text_for_ass(self, text: str, style: Dict[str, Any]) -> str:
        normalized = self._normalize_style_aliases(style)

        try:
            font_size = int(float(normalized.get("font_size", 64) or 64))
        except Exception:
            font_size = 64
        if font_size <= 0:
            font_size = 64

        font_path = str(normalized.get("font_path", "") or "")
        font = _load_font_with_fallback(font_path, font_size)

        try:
            max_width = max(1, int(normalized.get("max_pixel_width", 1800) or 1800))
        except Exception:
            max_width = 1800

        wrap_mode = str(normalized.get("wrap_mode", "") or "").strip().lower()
        max_chars = normalized.get("max_chars_per_line")
        auto_char_wrap = isinstance(max_chars, str) and max_chars.strip().lower() == "auto"

        if wrap_mode == "chars" or (max_chars is not None and wrap_mode != "pixel"):
            if auto_char_wrap:
                max_chars_i = _estimate_auto_max_chars(text, font, max_width)
                wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(text, max_chars_i)
                while max_chars_i > 4 and not _fits_within_width(
                    wrapped_text, font, max_width
                ):
                    max_chars_i -= 1
                    wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(
                        text, max_chars_i
                    )
            else:
                try:
                    max_chars_i = int(max_chars) if max_chars is not None else 0
                except Exception:
                    max_chars_i = 0
                wrapped_text = SubtitlePNGRenderer._wrap_text_by_chars_static(text, max_chars_i)
        else:
            wrapped_text = SubtitlePNGRenderer._wrap_text_by_pixel_static(text, font, max_width)

        return wrapped_text

    def resolve_subtitle_style(self, line_config: Dict[str, Any]) -> Dict[str, Any]:
        style = self._normalize_style_aliases(self.subtitle_config.copy())
        if "subtitle" in line_config and isinstance(line_config["subtitle"], dict):
            style.update(self._normalize_style_aliases(line_config["subtitle"]))
        return style

    def subtitle_render_mode(self) -> str:
        # Rendering mode is selected internally from subtitle styling.
        return "auto"

    @staticmethod
    def _has_subtitle_effects(style: Dict[str, Any]) -> bool:
        effects = style.get("effects")
        if effects is None:
            return False
        if isinstance(effects, (list, tuple, set, dict)):
            return bool(effects)
        return bool(str(effects).strip())

    @staticmethod
    def _background_metric(value: Any, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return max(0, int(default))

    def style_requires_png(self, style: Dict[str, Any]) -> bool:
        normalized = self._normalize_style_aliases(style)
        if self._has_subtitle_effects(normalized):
            return True

        background_cfg = _extract_background_config(normalized)
        if not _background_is_visible(background_cfg):
            return False

        if background_cfg.get("image") or background_cfg.get("image_path"):
            return True
        if self._background_metric(
            background_cfg.get("radius", background_cfg.get("corner_radius", 0))
        ) > 0:
            return True
        if self._background_metric(background_cfg.get("border_width", 0)) > 0:
            return True
        padding_value = background_cfg.get("padding", normalized.get("box_padding"))
        if any(_normalize_padding(padding_value, 0)):
            return True
        return False

    def resolve_render_mode_for_line_configs(
        self,
        line_configs: Iterable[Dict[str, Any] | None],
    ) -> str:
        for line_config in line_configs:
            style = self.resolve_subtitle_style(line_config or {})
            if self.style_requires_png(style):
                return "png"
        return "ass"

    def resolve_render_mode_for_subtitles(
        self,
        subtitles: Iterable[Dict[str, Any]],
    ) -> str:
        return self.resolve_render_mode_for_line_configs(
            (subtitle.get("line_config", {}) for subtitle in subtitles)
        )

    @staticmethod
    def _ass_font_name(style: Dict[str, Any]) -> str:
        font_path = style.get("font_path")
        if font_path:
            try:
                return Path(str(font_path)).stem or "Arial"
            except Exception:
                return "Arial"
        return "Arial"

    @staticmethod
    def _parse_color(value: Any, alpha: int = 0) -> pysubs2.Color:
        try:
            rgb = ImageColor.getrgb(str(value or "#FFFFFF"))
            return pysubs2.Color(rgb[0], rgb[1], rgb[2], max(0, min(255, int(alpha))))
        except Exception:
            return pysubs2.Color(255, 255, 255, max(0, min(255, int(alpha))))

    @staticmethod
    def _parse_ass_rgba(rgba: tuple[int, int, int, int]) -> pysubs2.Color:
        r, g, b, alpha = rgba
        ass_alpha = max(0, min(255, 255 - int(alpha)))
        return pysubs2.Color(r, g, b, ass_alpha)

    @staticmethod
    def _alignment_for_text_align(value: Any) -> pysubs2.Alignment:
        align = str(value or "center").lower()
        if align == "left":
            return pysubs2.Alignment.BOTTOM_LEFT
        if align == "right":
            return pysubs2.Alignment.BOTTOM_RIGHT
        return pysubs2.Alignment.BOTTOM_CENTER

    @staticmethod
    def _margin_v_from_style(style: Dict[str, Any]) -> int:
        raw_y = str(style.get("y", "H-100-text_h/2")).replace(" ", "").lower()
        match = re.fullmatch(r"[hw]-([0-9]+(?:\.[0-9]+)?)-text_h/2", raw_y)
        if match:
            try:
                return max(0, int(round(float(match.group(1)))))
            except Exception:
                return 100
        return 100

    @staticmethod
    def _ass_middle_alignment_tag(style: Dict[str, Any]) -> str:
        align = str(style.get("text_align", "center") or "center").lower()
        if align == "left":
            return "4"
        if align == "right":
            return "6"
        return "5"

    @staticmethod
    def _position_override_from_style(
        style: Dict[str, Any],
        *,
        width: int,
        height: int,
    ) -> Optional[str]:
        raw_x = str(style.get("x", "") or "").replace(" ", "").lower()
        raw_y = str(style.get("y", "") or "").replace(" ", "").lower()

        x_pos: Optional[int]
        if raw_x in {"(w-text_w)/2", "(w-text_w)/2.0"}:
            x_pos = width // 2
        else:
            try:
                x_pos = int(round(float(raw_x)))
            except Exception:
                x_pos = None

        y_pos: Optional[int]
        match = re.fullmatch(r"[hw]-([0-9]+(?:\.[0-9]+)?)-text_h/2", raw_y)
        if match:
            try:
                y_pos = int(round(height - float(match.group(1))))
            except Exception:
                y_pos = None
        else:
            try:
                y_pos = int(round(float(raw_y)))
            except Exception:
                y_pos = None

        if x_pos is None or y_pos is None:
            return None

        align_tag = SubtitleGenerator._ass_middle_alignment_tag(style)
        return rf"{{\an{align_tag}\pos({x_pos},{y_pos})}}"

    @staticmethod
    def _build_ass_style_name(style: Dict[str, Any]) -> str:
        payload = repr(sorted(style.items())).encode("utf-8")
        return f"Style_{hashlib.sha1(payload).hexdigest()[:10]}"

    def subtitle_background_visible(self, style: Dict[str, Any]) -> bool:
        normalized = self._normalize_style_aliases(style)
        background_cfg = _extract_background_config(normalized)
        return _background_is_visible(background_cfg)

    def _build_ass_style(self, style: Dict[str, Any]) -> pysubs2.SSAStyle:
        normalized = self._normalize_style_aliases(style)
        try:
            font_size = float(normalized.get("font_size", 64) or 64)
        except Exception:
            font_size = 64.0
        try:
            stroke_width = float(normalized.get("stroke_width", 2) or 0)
        except Exception:
            stroke_width = 2.0
        try:
            shadow = float(normalized.get("shadow", 0) or 0)
        except Exception:
            shadow = 0.0

        style_obj = pysubs2.SSAStyle()
        style_obj.fontname = self._ass_font_name(normalized)
        style_obj.fontsize = font_size
        style_obj.primarycolor = self._parse_color(normalized.get("font_color", "white"))
        style_obj.outlinecolor = self._parse_color(normalized.get("stroke_color", "black"))
        style_obj.backcolor = self._parse_color("#000000", 255)
        style_obj.secondarycolor = self._parse_color(normalized.get("font_color", "white"))
        style_obj.alignment = self._alignment_for_text_align(normalized.get("text_align"))
        style_obj.marginl = int(normalized.get("margin_left", 32) or 32)
        style_obj.marginr = int(normalized.get("margin_right", 32) or 32)
        style_obj.marginv = self._margin_v_from_style(normalized)
        style_obj.bold = bool(normalized.get("bold", False))
        style_obj.italic = bool(normalized.get("italic", False))
        style_obj.outline = max(0.0, stroke_width)
        style_obj.shadow = max(0.0, shadow)
        style_obj.encoding = 1
        background_cfg = _extract_background_config(normalized)
        if _background_is_visible(background_cfg):
            background_rgba = _resolve_rgba(
                background_cfg.get("color") or background_cfg.get("fill"),
                background_cfg.get("opacity"),
            )
            if background_rgba is not None:
                style_obj.borderstyle = 3
                # libass opaque box rendering is more reliable when both
                # OutlineColour and BackColour are aligned to the same RGBA.
                ass_box_color = self._parse_ass_rgba(background_rgba)
                style_obj.outlinecolor = ass_box_color
                style_obj.backcolor = ass_box_color
        return style_obj

    def _video_resolution(self) -> tuple[int, int]:
        video_cfg = self._config.get("video", {}) if isinstance(self._config, dict) else {}
        try:
            width = int(video_cfg.get("width", 1920) or 1920)
        except Exception:
            width = 1920
        try:
            height = int(video_cfg.get("height", 1080) or 1080)
        except Exception:
            height = 1080
        return max(1, width), max(1, height)

    def build_ass_subtitle_file(
        self,
        subtitles: Iterable[Dict[str, Any]],
        output_path: Path,
    ) -> Path:
        subs = pysubs2.SSAFile()
        play_res_x, play_res_y = self._video_resolution()
        subs.info["PlayResX"] = str(play_res_x)
        subs.info["PlayResY"] = str(play_res_y)
        default_style_name: Optional[str] = None

        for sub in subtitles:
            text = normalize_subtitle_text(sub.get("text", ""))
            if not text:
                continue
            style = self.resolve_subtitle_style(sub.get("line_config", {}) or {})
            text = self._wrap_text_for_ass(text, style)
            style_name = self._build_ass_style_name(style)
            if style_name not in subs.styles:
                subs.styles[style_name] = self._build_ass_style(style)
            if default_style_name is None:
                default_style_name = style_name
                subs.styles["Default"] = subs.styles[style_name].copy()

            start_ms = int(round(float(sub.get("start", 0.0)) * 1000))
            end_ms = int(
                round(
                    (float(sub.get("start", 0.0)) + float(sub.get("duration", 0.0))) * 1000
                )
            )
            if end_ms <= start_ms:
                continue
            pos_override = self._position_override_from_style(
                style,
                width=play_res_x,
                height=play_res_y,
            )
            ass_text = text.replace("\n", r"\N")
            if pos_override:
                ass_text = f"{pos_override}{ass_text}"
            subs.append(
                pysubs2.SSAEvent(
                    start=start_ms,
                    end=end_ms,
                    text=ass_text,
                    style=style_name,
                )
            )

        if default_style_name is None:
            subs.styles["Default"] = self._build_ass_style(self.subtitle_config)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        subs.save(str(output_path), format="ass")
        return output_path

    @staticmethod
    def _normalize_overlay_expr(value: Any, default: str) -> str:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return str(value)
        expr = str(value).strip()
        return expr or default

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

        style = self.resolve_subtitle_style(line_config)

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
        def convert_expr(expr: Any, default: str) -> str:
            expr = self._normalize_overlay_expr(expr, default)
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

        y_expr = convert_expr(style.get("y"), "H-100")
        x_expr = convert_expr(style.get("x"), "(W-w)/2")

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
