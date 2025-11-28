"""Built-in overlay effect builders exposed as a plugin."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _coerce_float(value: Any, *, default: float, min_value: float | None = None) -> float:
    try:
        result = float(value)
    except Exception:
        result = default
    if min_value is not None:
        result = max(result, min_value)
    return result


def _coerce_int(value: Any, *, default: int, min_value: int | None = None) -> int:
    try:
        result = int(value)
    except Exception:
        result = default
    if min_value is not None:
        result = max(result, min_value)
    return result


def _build_blur(params: Dict[str, Any]) -> List[str]:
    sigma = _coerce_float(params.get("sigma", params.get("r", 10.0)), default=10.0, min_value=0.0)
    return [f"gblur=sigma={sigma:.4f}"]


def _build_vignette(_: Dict[str, Any]) -> List[str]:
    return ["vignette"]


def _build_eq(params: Dict[str, Any]) -> Optional[List[str]]:
    allowed_keys = ("contrast", "brightness", "saturation", "gamma", "gamma_r", "gamma_g", "gamma_b")
    parts: List[str] = []
    for key in allowed_keys:
        if key in params:
            parts.append(f"{key}={_coerce_float(params[key], default=0.0):.6f}")
    if not parts:
        return None
    return ["eq=" + ":".join(parts)]


def _build_hue(params: Dict[str, Any]) -> Optional[List[str]]:
    parts: List[str] = []
    if "h" in params:
        parts.append(f"h={_coerce_float(params['h'], default=0.0):.6f}")
    if "s" in params:
        parts.append(f"s={_coerce_float(params['s'], default=0.0):.6f}")
    if "b" in params:
        parts.append(f"b={_coerce_float(params['b'], default=0.0):.6f}")
    if not parts:
        return None
    return ["hue=" + ":".join(parts)]


def _build_curves(params: Dict[str, Any]) -> Optional[List[str]]:
    preset = params.get("preset")
    if isinstance(preset, str) and preset.strip():
        return [f"curves=preset={preset.strip()}"]
    return None


def _build_unsharp(params: Dict[str, Any]) -> List[str]:
    lx = _coerce_int(params.get("lx", 5), default=5, min_value=0)
    ly = _coerce_int(params.get("ly", 5), default=5, min_value=0)
    la = _coerce_float(params.get("la", 1.0), default=1.0, min_value=0.0)
    cx = _coerce_int(params.get("cx", 5), default=5, min_value=0)
    cy = _coerce_int(params.get("cy", 5), default=5, min_value=0)
    ca = _coerce_float(params.get("ca", 0.0), default=0.0, min_value=0.0)
    return [f"unsharp={lx}:{ly}:{la}:{cx}:{cy}:{ca}"]


def _build_lut3d(params: Dict[str, Any]) -> Optional[List[str]]:
    file = params.get("file")
    if isinstance(file, str) and file.strip():
        return [f"lut3d=file={file}"]
    return None


def _build_rotate(params: Dict[str, Any]) -> List[str]:
    angle = params.get("angle")
    if angle is None and "degrees" in params:
        try:
            angle = float(params["degrees"]) * math.pi / 180.0
        except Exception:
            angle = 0.0
    ang = _coerce_float(angle, default=0.0) if angle is not None else 0.0
    fill = params.get("fill", "0x00000000")
    return [f"rotate={ang:.6f}:fillcolor={fill}"]


BUILDERS = {
    "blur": _build_blur,
    "vignette": _build_vignette,
    "eq": _build_eq,
    "hue": _build_hue,
    "curves": _build_curves,
    "unsharp": _build_unsharp,
    "lut3d": _build_lut3d,
    "rotate": _build_rotate,
}

ALIASES = {"blur": ["gblur"]}
