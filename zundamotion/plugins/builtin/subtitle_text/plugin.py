"""Built-in subtitle effects exposed as a plugin."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from zundamotion.components.subtitles.effects import SubtitleEffectContext, SubtitleEffectSnippet


def _coerce_float(value: Any, *, default: float, min_value: float | None = None) -> float:
    try:
        result = float(value)
    except Exception:
        result = default
    if min_value is not None:
        result = max(result, min_value)
    return result


def _extract_phase_shift(effect: Dict[str, Any], default: float) -> float:
    if "phase_offset" in effect:
        try:
            return float(effect.get("phase_offset"))
        except Exception:
            return default
    if "phase_offset_deg" in effect:
        try:
            return math.radians(float(effect.get("phase_offset_deg")))
        except Exception:
            return default
    return default


def _resolve_text_bounce(
    context: SubtitleEffectContext, effect: Dict[str, Any]
) -> Optional[SubtitleEffectSnippet]:
    amp_px = abs(_coerce_float(effect.get("amplitude", effect.get("amount", 36.0)), default=36.0))
    freq = _coerce_float(effect.get("frequency", 2.0), default=2.0, min_value=0.0001)

    phase = _extract_phase_shift(effect, default=0.0)
    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"
    phase_str = f"{phase:.6f}"

    wave_expr = f"abs(sin({omega_str}*t+{phase_str}))"

    base_bias = _coerce_float(effect.get("baseline_shift", 0.0), default=0.0)

    y_expr = f"({context.base_y_expr})-(({amp_px:.6f})*{wave_expr})+({base_bias:.6f})"

    overlay_kwargs = {"y": y_expr}

    return SubtitleEffectSnippet(
        filter_chain=[],
        output_label=context.input_label,
        overlay_kwargs=overlay_kwargs,
        dynamic=amp_px > 0.0,
    )


BUILDERS = {"text:bounce_text": _resolve_text_bounce}
ALIASES = {"text:bounce_text": ["bounce_text"]}
