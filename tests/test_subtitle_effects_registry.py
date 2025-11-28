from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.subtitles import effects as subtitle_effects
from zundamotion.components.subtitles.effects import resolve_subtitle_effects


def test_bounce_effect_updates_overlay_y_and_marks_dynamic():
    result = resolve_subtitle_effects(
        effects=[
            {
                "type": "text:bounce_text",
                "amplitude": 24,
                "frequency": 1.25,
                "baseline_shift": -6,
            }
        ],
        input_label="[txt0]",
        base_x_expr="(main_w-text_w)/2",
        base_y_expr="(main_h-text_h)/2",
        duration=3.0,
        width=1920,
        height=1080,
        index=0,
    )

    assert result is not None
    assert result.filter_chain == []
    assert result.output_label == "[txt0]"
    assert result.dynamic is True
    assert result.overlay_kwargs.get("y", "").startswith("((main_h-text_h)/2)-((24.000000)*abs(sin(")
    assert result.overlay_kwargs.get("y", "").endswith("))+(-6.000000)")


def test_unknown_subtitle_effect_returns_none():
    assert (
        resolve_subtitle_effects(
            effects=[{"type": "unknown"}],
            input_label="[txt]",
            base_x_expr="10",
            base_y_expr="20",
            duration=1.0,
            width=640,
            height=480,
            index=1,
        )
        is None
    )


def test_failure_in_subtitle_effect_builder_is_swallowed():
    def _boom(*_, **__):  # pragma: no cover - invoked via registry
        raise RuntimeError("boom")

    previous = subtitle_effects._EFFECT_REGISTRY.get("text:boom")
    subtitle_effects.register_subtitle_effect("text:boom", _boom)

    try:
        assert (
            resolve_subtitle_effects(
                effects=[{"type": "text:boom"}],
                input_label="[txt]",
                base_x_expr="x",
                base_y_expr="y",
                duration=1.0,
                width=320,
                height=240,
                index=2,
            )
            is None
        )
    finally:
        if previous:
            subtitle_effects._EFFECT_REGISTRY["text:boom"] = previous
        else:
            subtitle_effects._EFFECT_REGISTRY.pop("text:boom", None)
