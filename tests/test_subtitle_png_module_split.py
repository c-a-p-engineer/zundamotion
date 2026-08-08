from __future__ import annotations

import inspect

from zundamotion.components.subtitles.png import SubtitlePNGRenderer, _render_subtitle_png
from zundamotion.components.subtitles.png_draw import (
    _draw_text,
    _layout_text,
    _render_subtitle_png as draw_entry,
    _resolve_draw_style,
)


def test_png_facade_preserves_picklable_draw_entry() -> None:
    assert _render_subtitle_png is draw_entry
    assert inspect.isfunction(_render_subtitle_png)
    assert _render_subtitle_png.__module__.endswith("png_draw")


def test_png_render_orchestration_and_draw_helpers_stay_bounded() -> None:
    targets = [
        SubtitlePNGRenderer.render,
        _resolve_draw_style,
        _layout_text,
        _draw_text,
        _render_subtitle_png,
    ]
    for target in targets:
        lines, _ = inspect.getsourcelines(target)
        assert len(lines) <= 80, (target.__name__, len(lines))
