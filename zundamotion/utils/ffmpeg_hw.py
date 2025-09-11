"""ハードウェアフィルタ利用モードを管理するユーティリティ。"""

from __future__ import annotations

import os
from typing import List

from .logger import logger

_hw_filter_mode: str = (
    os.environ.get("HW_FILTER_MODE", "auto").lower()
    if os.environ.get("HW_FILTER_MODE", "auto").lower() in {"auto", "cuda", "cpu"}
    else "auto"
)


def set_hw_filter_mode(mode: str) -> None:
    """グローバルなハードウェアフィルタモードを設定する。"""
    global _hw_filter_mode
    mode_l = (mode or "").lower()
    if mode_l not in {"auto", "cuda", "cpu"}:
        logger.warning(f"Invalid HW filter mode '{mode}'; keeping '{_hw_filter_mode}'.")
        return
    if _hw_filter_mode != mode_l:
        logger.info(f"Setting HW filter mode to '{mode_l}'.")
    _hw_filter_mode = mode_l


def get_hw_filter_mode() -> str:
    """現在のハードウェアフィルタモードを返す。"""
    return _hw_filter_mode


def get_profile_flags() -> List[str]:
    """FFMPEG_PROFILE_MODE=1 のときにプロファイル用フラグを返す。"""
    try:
        if os.getenv("FFMPEG_PROFILE_MODE", "0") == "1":
            return ["-benchmark", "-stats"]
    except Exception:
        pass
    return []
