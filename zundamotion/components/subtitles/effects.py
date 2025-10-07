"""Utility helpers for resolving subtitle overlay effects."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from ...utils.logger import logger


@dataclass
class SubtitleEffectSnippet:
    """Result of resolving text-specific effects for subtitle overlays."""

    filter_chain: List[str]
    output_label: str
    overlay_kwargs: Dict[str, str]
    dynamic: bool = False


def resolve_subtitle_effects(
    *,
    effects: Optional[Iterable[Any]],
    input_label: str,
    base_x_expr: str,
    base_y_expr: str,
    duration: float,
    width: int,
    height: int,
    index: int,
) -> Optional[SubtitleEffectSnippet]:
    """Resolve configured subtitle effects into FFmpeg filter fragments."""

    if not effects:
        return None

    filter_chain: List[str] = []
    current_label = input_label
    current_x = base_x_expr
    current_y = base_y_expr
    dynamic = False

    for effect_index, raw in enumerate(effects, start=1):
        effect = _normalize_effect(raw)
        if not effect:
            continue

        effect_type = effect["type"]
        if effect_type == "text:bounce_text":
            snippet = _resolve_text_bounce(
                effect,
                input_label=current_label,
                base_x_expr=current_x,
                base_y_expr=current_y,
                duration=duration,
                width=width,
                height=height,
                index=index,
                effect_index=effect_index,
            )
        else:
            logger.debug("[Effects] Unsupported text effect type: %s", effect_type)
            continue

        if not snippet:
            continue

        if snippet.filter_chain:
            filter_chain.extend(snippet.filter_chain)
        if "x" in snippet.overlay_kwargs:
            current_x = snippet.overlay_kwargs["x"]
        if "y" in snippet.overlay_kwargs:
            current_y = snippet.overlay_kwargs["y"]
        current_label = snippet.output_label
        dynamic = dynamic or snippet.dynamic

    overlay_kwargs: Dict[str, str] = {}
    if current_x != base_x_expr:
        overlay_kwargs["x"] = current_x
    if current_y != base_y_expr:
        overlay_kwargs["y"] = current_y

    if not filter_chain and not overlay_kwargs:
        return None

    return SubtitleEffectSnippet(
        filter_chain=filter_chain,
        output_label=current_label,
        overlay_kwargs=overlay_kwargs,
        dynamic=dynamic,
    )


def _normalize_effect(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        return {"type": raw.strip().lower()}
    if not isinstance(raw, dict):
        return None
    effect_type = raw.get("type")
    if not isinstance(effect_type, str):
        return None
    normalized = dict(raw)
    normalized["type"] = effect_type.strip().lower()
    return normalized


def _resolve_text_bounce(
    effect: Dict[str, Any],
    *,
    input_label: str,
    base_x_expr: str,
    base_y_expr: str,
    duration: float,
    width: int,
    height: int,
    index: int,
    effect_index: int,
) -> Optional[SubtitleEffectSnippet]:
    """Create a perpetual vertical bounce controlled solely by amplitude."""

    try:
        amp_px = abs(float(effect.get("amplitude", effect.get("amount", 36.0))))
    except Exception:
        amp_px = 36.0

    try:
        freq = float(effect.get("frequency", 2.0))
        if freq <= 0:
            freq = 2.0
    except Exception:
        freq = 2.0

    phase = _extract_phase_shift(effect, default=0.0)
    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"
    phase_str = f"{phase:.6f}"

    wave_expr = f"abs(sin({omega_str}*t+{phase_str}))"

    base_bias = 0.0
    try:
        base_bias = float(effect.get("baseline_shift", 0.0))
    except Exception:
        base_bias = 0.0

    y_expr = f"({base_y_expr})-(({amp_px:.6f})*{wave_expr})+({base_bias:.6f})"

    overlay_kwargs = {"y": y_expr}

    return SubtitleEffectSnippet(
        filter_chain=[],
        output_label=input_label,
        overlay_kwargs=overlay_kwargs,
        dynamic=amp_px > 0.0,
    )


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
