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
    output_label: Optional[str] = None


@dataclass
class ScreenEffectSnippet:
    """Filter chain snippet applied to the entire screen stream."""

    filter_chain: List[str]
    output_label: str
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
        elif effect_type == "char:bob_char":
            snippet = _resolve_char_bob(effect, current_y, duration)
        elif effect_type == "char:sway_char":
            snippet = _resolve_char_sway(effect, current_x, duration)
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


def resolve_background_effects(
    *,
    effects: Optional[Iterable[Any]],
    input_label: str,
    duration: float,
    width: int,
    height: int,
    id_prefix: str = "bg",
) -> Optional[FilterSnippet]:
    """Resolve background-specific effects applied before overlay composition."""

    if not effects:
        return None

    filter_chain: List[str] = []
    current_label = input_label
    dynamic = False

    for idx, raw in enumerate(effects, start=1):
        effect = _normalize_effect(raw)
        if not effect:
            continue

        effect_type = effect["type"]
        if effect_type == "bg:shake_bg":
            snippet = _resolve_background_shake(
                effect,
                input_label=current_label,
                duration=duration,
                width=width,
                height=height,
                index=idx,
                id_prefix=id_prefix,
            )
        else:
            logger.debug("[Effects] Unsupported background effect type: %s", effect_type)
            continue

        if not snippet:
            continue

        filter_chain.extend(snippet.filter_chain)
        if snippet.output_label:
            current_label = snippet.output_label
        dynamic = dynamic or snippet.dynamic

    if filter_chain and current_label != input_label:
        return FilterSnippet(
            filter_chain=filter_chain,
            overlay_kwargs={},
            dynamic=dynamic,
            output_label=current_label,
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
    amp_x, amp_y = _extract_amplitudes(effect, default=18.0)
    freq = _extract_frequency(effect, default=8.0)
    easing_type, easing_power = _extract_easing(effect)
    envelope_expr = _build_envelope_expr(duration, easing_type, easing_power)

    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"

    phase_shift_rad = _extract_phase_shift(effect, default=math.pi / 2.0)
    phase_str = f"{phase_shift_rad:.6f}"

    offset_x, offset_y = _extract_offsets(effect)

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
        dynamic=(amp_x > 0.0 or amp_y > 0.0),
    )


def _extract_amplitudes(effect: Dict[str, Any], default: float) -> tuple[float, float]:
    """Parse amplitude configuration supporting scalar or per-axis dict."""

    try:
        amplitude_cfg = effect.get("amplitude", default)
        if isinstance(amplitude_cfg, dict):
            amp_x = float(amplitude_cfg.get("x", amplitude_cfg.get("horizontal", default)))
            amp_y = float(amplitude_cfg.get("y", amplitude_cfg.get("vertical", amp_x)))
        else:
            amp_x = amp_y = float(amplitude_cfg)
    except Exception:
        amp_x = amp_y = default
    return abs(amp_x), abs(amp_y)


def _extract_frequency(effect: Dict[str, Any], default: float) -> float:
    """Parse oscillation frequency (Hz) with sane fallback."""

    try:
        freq = float(effect.get("freq", effect.get("frequency", default)))
        if freq <= 0:
            return default
        return freq
    except Exception:
        return default


def _extract_easing(effect: Dict[str, Any], default: str = "ease_in_out") -> tuple[str, float]:
    """Parse easing configuration for shake envelope."""

    easing_cfg = effect.get("easing", default)
    easing_type = default
    easing_power = 1.0
    if isinstance(easing_cfg, str):
        easing_type = easing_cfg.strip().lower() or default
    elif isinstance(easing_cfg, dict):
        easing_type = str(easing_cfg.get("type", default)).strip().lower()
        try:
            easing_power = float(easing_cfg.get("power", 1.0))
        except Exception:
            easing_power = 1.0
    easing_power = max(0.1, min(easing_power, 6.0))
    return easing_type, easing_power


def _build_envelope_expr(duration: float, easing_type: str, easing_power: float) -> str:
    """Build a time-dependent envelope expression for shake intensity."""

    duration_safe = max(duration, 0.001)
    duration_str = f"{duration_safe:.6f}"
    progress_expr = f"min(max(t/{duration_str},0),1)"

    if easing_type == "constant":
        return "1"
    if easing_type in {"linear", "ease_out_linear", "ease_out"}:
        return f"pow(1-{progress_expr},{easing_power})"
    if easing_type in {"ease_in", "ease_in_linear"}:
        return f"pow({progress_expr},{easing_power})"
    if easing_power == 1.0:
        return f"sin({progress_expr}*PI)"
    return f"pow(sin({progress_expr}*PI),{easing_power})"


def _extract_phase_shift(effect: Dict[str, Any], default: float) -> float:
    """Parse optional phase shift (radians)."""

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


def _resolve_char_bob(
    effect: Dict[str, Any],
    base_y_expr: str,
    duration: float,
) -> Optional[FilterSnippet]:
    """Apply a gentle vertical bobbing motion to the character overlay."""

    _, amp_y = _extract_amplitudes(effect, default=12.0)
    freq = _extract_frequency(effect, default=1.2)
    easing_type, easing_power = _extract_easing(effect, default="constant")
    envelope_expr = _build_envelope_expr(duration, easing_type, easing_power)
    phase_shift_rad = _extract_phase_shift(effect, default=0.0)
    _, offset_y = _extract_offsets(effect)

    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"
    phase_str = f"{phase_shift_rad:.6f}"
    amp_y_str = f"{amp_y:.6f}"
    offset_y_str = f"{offset_y:.6f}"

    y_expr = (
        f"({base_y_expr})+({offset_y_str})+({amp_y_str}*{envelope_expr}*sin({omega_str}*t+{phase_str}))"
    )

    return FilterSnippet(
        filter_chain=[],
        overlay_kwargs={"y": y_expr},
        dynamic=amp_y > 0.0,
    )


def _resolve_char_sway(
    effect: Dict[str, Any],
    base_x_expr: str,
    duration: float,
) -> Optional[FilterSnippet]:
    """Apply a gentle horizontal sway motion to the character overlay."""

    amp_x, _ = _extract_amplitudes(effect, default=16.0)
    freq = _extract_frequency(effect, default=1.0)
    easing_type, easing_power = _extract_easing(effect, default="constant")
    envelope_expr = _build_envelope_expr(duration, easing_type, easing_power)
    phase_shift_rad = _extract_phase_shift(effect, default=0.0)
    offset_x, _ = _extract_offsets(effect)

    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"
    phase_str = f"{phase_shift_rad:.6f}"
    amp_x_str = f"{amp_x:.6f}"
    offset_x_str = f"{offset_x:.6f}"

    x_expr = (
        f"({base_x_expr})+({offset_x_str})+({amp_x_str}*{envelope_expr}*sin({omega_str}*t+{phase_str}))"
    )

    return FilterSnippet(
        filter_chain=[],
        overlay_kwargs={"x": x_expr},
        dynamic=amp_x > 0.0,
    )


def _extract_offsets(effect: Dict[str, Any]) -> tuple[float, float]:
    """Parse constant positional offsets for shake centre."""

    offset_cfg = effect.get("offset", {})
    if isinstance(offset_cfg, dict):
        try:
            offset_x = float(offset_cfg.get("x", 0.0))
        except Exception:
            offset_x = 0.0
        try:
            offset_y = float(offset_cfg.get("y", 0.0))
        except Exception:
            offset_y = 0.0
        return offset_x, offset_y
    return 0.0, 0.0


def _resolve_background_shake(
    effect: Dict[str, Any],
    *,
    input_label: str,
    duration: float,
    width: int,
    height: int,
    index: int,
    id_prefix: str,
) -> Optional[FilterSnippet]:
    """Translate the background stream using padding + crop (FFmpeg lacks translate)."""

    amp_x, amp_y = _extract_amplitudes(effect, default=24.0)
    freq = _extract_frequency(effect, default=8.0)
    easing_type, easing_power = _extract_easing(effect)
    envelope_expr = _build_envelope_expr(duration, easing_type, easing_power)
    phase_shift_rad = _extract_phase_shift(effect, default=math.pi / 2.0)
    offset_x, offset_y = _extract_offsets(effect)

    dynamic = amp_x > 0.0 or amp_y > 0.0

    if (not dynamic) and abs(offset_x) < 1e-6 and abs(offset_y) < 1e-6:
        return None

    padding_extra = 0.0
    try:
        padding_extra = max(0.0, float(effect.get("padding", 0.0)))
    except Exception:
        padding_extra = 0.0

    required_pad_x = max(abs(offset_x) + amp_x, 0.0) + padding_extra
    required_pad_y = max(abs(offset_y) + amp_y, 0.0) + padding_extra

    pad_x = int(math.ceil(required_pad_x))
    pad_y = int(math.ceil(required_pad_y))

    if pad_x == 0 and (abs(offset_x) > 0.0 or dynamic):
        pad_x = 1
    if pad_y == 0 and (abs(offset_y) > 0.0 or dynamic):
        pad_y = 1

    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"
    phase_str = f"{phase_shift_rad:.6f}"

    shift_x_expr = (
        f"({offset_x:.6f})+({amp_x:.6f}*{envelope_expr}*sin({omega_str}*t))"
    )
    shift_y_expr = (
        f"({offset_y:.6f})+({amp_y:.6f}*{envelope_expr}*sin({omega_str}*t+{phase_str}))"
    )

    clamp_max_x = pad_x * 2
    clamp_max_y = pad_y * 2
    x_expr = f"min(max({pad_x}-({shift_x_expr}),0),{clamp_max_x})"
    y_expr = f"min(max({pad_y}-({shift_y_expr}),0),{clamp_max_y})"

    def _escape_commas(expr: str) -> str:
        return expr.replace(",", "\\,")

    x_expr_escaped = _escape_commas(x_expr)
    y_expr_escaped = _escape_commas(y_expr)

    pad_label = f"[{id_prefix}_pad_{index}]"
    crop_label = f"[{id_prefix}_shake_{index}]"

    pad_filter = (
        f"{input_label}pad=iw+{pad_x*2}:ih+{pad_y*2}:{pad_x}:{pad_y}:color=0x00000000{pad_label}"
    )
    crop_filter = (
        f"{pad_label}crop={width}:{height}:{x_expr_escaped}:{y_expr_escaped}{crop_label}"
    )

    return FilterSnippet(
        filter_chain=[pad_filter, crop_filter],
        overlay_kwargs={},
        dynamic=dynamic,
        output_label=crop_label,
    )


def resolve_screen_effects(
    *,
    effects: Optional[Iterable[Any]],
    input_label: str,
    duration: float,
    width: int,
    height: int,
    id_prefix: str = "screen",
) -> Optional[ScreenEffectSnippet]:
    """Resolve screen-wide effects that operate on the final composed stream."""

    if not effects:
        return None

    filter_chain: List[str] = []
    current_label = input_label
    dynamic = False

    for idx, raw in enumerate(effects, start=1):
        effect = _normalize_effect(raw)
        if not effect:
            continue

        effect_type = effect["type"]
        if effect_type == "screen:shake_screen":
            snippet = _resolve_screen_shake(
                effect,
                input_label=current_label,
                duration=duration,
                width=width,
                height=height,
                index=idx,
                id_prefix=id_prefix,
            )
        else:
            logger.debug("[Effects] Unsupported screen effect type: %s", effect_type)
            continue

        if not snippet:
            continue

        filter_chain.extend(snippet.filter_chain)
        current_label = snippet.output_label
        dynamic = dynamic or snippet.dynamic

    if filter_chain and current_label != input_label:
        return ScreenEffectSnippet(
            filter_chain=filter_chain,
            output_label=current_label,
            dynamic=dynamic,
        )

    return None


def _resolve_screen_shake(
    effect: Dict[str, Any],
    *,
    input_label: str,
    duration: float,
    width: int,
    height: int,
    index: int,
    id_prefix: str,
) -> Optional[ScreenEffectSnippet]:
    """Translate the entire frame using a sine-driven shake motion."""

    amp_x, amp_y = _extract_amplitudes(effect, default=24.0)
    # Prevent impossible offsets (keep within frame bounds)
    amp_x = min(amp_x, max(0.0, width / 2 - 2))
    amp_y = min(amp_y, max(0.0, height / 2 - 2))

    freq = _extract_frequency(effect, default=8.0)
    easing_type, easing_power = _extract_easing(effect)
    envelope_expr = _build_envelope_expr(duration, easing_type, easing_power)
    phase_shift_rad = _extract_phase_shift(effect, default=math.pi / 2.0)
    offset_x, offset_y = _extract_offsets(effect)

    padding_extra = 0.0
    try:
        padding_extra = max(0.0, float(effect.get("padding", 0.0)))
    except Exception:
        padding_extra = 0.0

    required_pad_x = max(abs(offset_x) + amp_x, 0.0) + padding_extra
    required_pad_y = max(abs(offset_y) + amp_y, 0.0) + padding_extra

    pad_x = int(math.ceil(required_pad_x))
    pad_y = int(math.ceil(required_pad_y))

    dynamic = amp_x > 0.0 or amp_y > 0.0

    if pad_x == 0 and pad_y == 0 and not dynamic and abs(offset_x) < 1e-6 and abs(offset_y) < 1e-6:
        # No visible effect -> skip
        return None

    # Ensure at least 1px padding when motion or offset exists to keep cropping safe
    if pad_x == 0 and (abs(offset_x) > 0.0 or dynamic):
        pad_x = 1
    if pad_y == 0 and (abs(offset_y) > 0.0 or dynamic):
        pad_y = 1

    omega = 2.0 * math.pi * freq
    omega_str = f"{omega:.6f}"
    phase_str = f"{phase_shift_rad:.6f}"

    shift_x_expr = (
        f"({offset_x:.6f})+({amp_x:.6f}*{envelope_expr}*sin({omega_str}*t))"
    )
    shift_y_expr = (
        f"({offset_y:.6f})+({amp_y:.6f}*{envelope_expr}*sin({omega_str}*t+{phase_str}))"
    )

    clamp_max_x = pad_x * 2
    clamp_max_y = pad_y * 2
    x_expr = f"min(max({pad_x}-({shift_x_expr}),0),{clamp_max_x})"
    y_expr = f"min(max({pad_y}-({shift_y_expr}),0),{clamp_max_y})"

    def _escape_commas(expr: str) -> str:
        return expr.replace(",", "\\,")

    x_expr_escaped = _escape_commas(x_expr)
    y_expr_escaped = _escape_commas(y_expr)

    pad_label = f"[{id_prefix}_pad_{index}]"
    crop_label = f"[{id_prefix}_shake_{index}]"

    pad_filter = (
        f"{input_label}pad=iw+{pad_x*2}:ih+{pad_y*2}:{pad_x}:{pad_y}:color=0x00000000{pad_label}"
    )
    crop_filter = (
        f"{pad_label}crop={width}:{height}:{x_expr_escaped}:{y_expr_escaped}{crop_label}"
    )

    return ScreenEffectSnippet(
        filter_chain=[pad_filter, crop_filter],
        output_label=crop_label,
        dynamic=dynamic,
    )
