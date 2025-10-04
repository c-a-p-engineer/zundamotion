from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from zundamotion.utils.logger import logger


@dataclass
class FilterSnippet:
    """Result of resolving a high-level effect into filter fragments."""

    filter_chain: List[str]
    overlay_kwargs: Dict[str, str]
    dynamic: bool = False


def resolve_character_effects(
    *,
    effects: Optional[Iterable[Any]],
    base_x_expr: str,
    base_y_expr: str,
    duration: float,
) -> Optional[FilterSnippet]:
    """Resolve configured character effects into FFmpeg expressions.

    Parameters
    ----------
    effects:
        Iterable of effect configuration entries (string or dict).
    base_x_expr, base_y_expr:
        Overlay expressions already computed for the character placement.
    duration:
        Clip duration in seconds. Used to clamp time dependent effects.

    Returns
    -------
    Optional[FilterSnippet]
        Filter snippet describing additional filters and overlay keyword overrides.
    """

    if not effects:
        return None

    filter_chain: List[str] = []
    current_x = base_x_expr
    current_y = base_y_expr
    dynamic = False

    for raw in effects:
        effect = _normalize_effect(raw)
        if not effect:
            continue

        effect_type = effect["type"]
        if effect_type == "char:shake_char":
            snippet = _resolve_char_shake(effect, current_x, current_y, duration)
        else:
            logger.debug("[Effects] Unsupported character effect type: %s", effect_type)
            continue

        if snippet is None:
            continue

        # Accumulate filters and overlay overrides.
        if snippet.filter_chain:
            filter_chain.extend(snippet.filter_chain)
        if "x" in snippet.overlay_kwargs:
            current_x = snippet.overlay_kwargs["x"]
        if "y" in snippet.overlay_kwargs:
            current_y = snippet.overlay_kwargs["y"]
        dynamic = dynamic or snippet.dynamic

    if filter_chain or current_x != base_x_expr or current_y != base_y_expr:
        overlay_kwargs: Dict[str, str] = {}
        if current_x != base_x_expr:
            overlay_kwargs["x"] = current_x
        if current_y != base_y_expr:
            overlay_kwargs["y"] = current_y
        return FilterSnippet(
            filter_chain=filter_chain,
            overlay_kwargs=overlay_kwargs,
            dynamic=dynamic,
        )

    return None


def _normalize_effect(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        return {"type": raw.strip().lower()}
    if not isinstance(raw, dict):
        return None
    effect_type = raw.get("type")
    if not isinstance(effect_type, str) or not effect_type.strip():
        return None
    # Preserve original case for downstream consumers but normalise for lookup.
    normalized = raw.copy()
    normalized["type"] = effect_type.strip().lower()
    return normalized


def _resolve_char_shake(
    effect: Dict[str, Any],
    base_x_expr: str,
    base_y_expr: str,
    duration: float,
) -> Optional[FilterSnippet]:
    """Create a shake effect by modulating overlay positions with sine waves."""

    try:
        amplitude_cfg = effect.get("amplitude", 18.0)
        if isinstance(amplitude_cfg, dict):
            amp_x = float(amplitude_cfg.get("x", amplitude_cfg.get("horizontal", 18.0)))
            amp_y = float(amplitude_cfg.get("y", amplitude_cfg.get("vertical", amp_x)))
        else:
            amp_x = amp_y = float(amplitude_cfg)
    except Exception:
        amp_x = amp_y = 18.0

    try:
        freq = float(effect.get("freq", effect.get("frequency", 8.0)))
        if freq <= 0:
            freq = 8.0
    except Exception:
        freq = 8.0

    easing_cfg = effect.get("easing", "ease_in_out")
    easing_type = "ease_in_out"
    easing_power = 1.0
    if isinstance(easing_cfg, str):
        easing_type = easing_cfg.strip().lower() or "ease_in_out"
    elif isinstance(easing_cfg, dict):
        easing_type = str(easing_cfg.get("type", "ease_in_out")).strip().lower()
        try:
            easing_power = float(easing_cfg.get("power", 1.0))
        except Exception:
            easing_power = 1.0
        easing_power = max(0.1, min(easing_power, 6.0))

    duration_safe = max(duration, 0.001)
    duration_str = f"{duration_safe:.6f}"
    progress_expr = f"min(max(t/{duration_str},0),1)"

    if easing_type == "constant":
        envelope_expr = "1"
    elif easing_type in {"linear", "ease_out_linear", "ease_out"}:
        envelope_expr = f"pow(1-{progress_expr},{easing_power})"
    elif easing_type in {"ease_in", "ease_in_linear"}:
        envelope_expr = f"pow({progress_expr},{easing_power})"
    else:  # ease_in_out (default)
        if easing_power == 1.0:
            envelope_expr = f"sin({progress_expr}*PI)"
        else:
            envelope_expr = f"pow(sin({progress_expr}*PI),{easing_power})"

    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"

    # Allow optional phase difference overrides (default quarter-period phase shift on Y).
    phase_shift_rad: float
    if "phase_offset" in effect:
        try:
            phase_shift_rad = float(effect.get("phase_offset"))
        except Exception:
            phase_shift_rad = math.pi / 2.0
    elif "phase_offset_deg" in effect:
        try:
            phase_shift_rad = math.radians(float(effect.get("phase_offset_deg")))
        except Exception:
            phase_shift_rad = math.pi / 2.0
    else:
        phase_shift_rad = math.pi / 2.0
    phase_str = f"{phase_shift_rad:.6f}"

    # Optional per-axis offsets to bias the shake position.
    offset_cfg = effect.get("offset", {})
    try:
        offset_x = float(offset_cfg.get("x", 0.0)) if isinstance(offset_cfg, dict) else 0.0
    except Exception:
        offset_x = 0.0
    try:
        offset_y = float(offset_cfg.get("y", 0.0)) if isinstance(offset_cfg, dict) else 0.0
    except Exception:
        offset_y = 0.0

    amp_x_str = f"{amp_x:.6f}"
    amp_y_str = f"{amp_y:.6f}"
    x_expr = (
        f"({base_x_expr})+({offset_x:.6f})+({amp_x_str}*{envelope_expr}*sin({omega_str}*t))"
    )
    y_expr = (
        f"({base_y_expr})+({offset_y:.6f})+({amp_y_str}*{envelope_expr}*sin({omega_str}*t+{phase_str}))"
    )

    return FilterSnippet(
        filter_chain=[],
        overlay_kwargs={"x": x_expr, "y": y_expr},
        dynamic=True,
    )
