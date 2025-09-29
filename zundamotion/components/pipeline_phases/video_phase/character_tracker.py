from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CharacterState:
    """シーン内でのキャラクター状態を保持する。"""

    name: str
    expression: str = "default"
    anchor: str = "bottom_center"
    position: Dict[str, Any] = field(default_factory=lambda: {"x": "0", "y": "0"})
    scale: float = 1.0
    z: int = 0
    visible: bool = True


class CharacterTracker:
    """VNモード用のキャラクター状態トラッカー。"""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._states: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        self._states.clear()

    def apply(self, updates: List[Dict[str, Any]]) -> None:
        for upd in updates:
            name = upd.get("name")
            if not name:
                continue
            if upd.get("exit"):
                self._states.pop(name, None)
                continue
            state = self._states.get(name, {}).copy()
            if "enter" in upd:
                state["enter"] = upd.get("enter")
                if "enter_duration" in upd:
                    state["enter_duration"] = upd["enter_duration"]
            if "leave" in upd:
                state["leave"] = upd.get("leave")
                if "leave_duration" in upd:
                    state["leave_duration"] = upd["leave_duration"]
            state.update(
                {
                    k: v
                    for k, v in upd.items()
                    if k
                    not in {
                        "enter",
                        "exit",
                        "enter_duration",
                        "leave",
                        "leave_duration",
                    }
                }
            )
            state.setdefault("visible", True)
            self._states[name] = state

    def snapshot(self) -> List[Dict[str, Any]]:
        snap: List[Dict[str, Any]] = []
        for name, st in list(self._states.items()):
            snap.append(st.copy())
            st.pop("enter", None)
            st.pop("enter_duration", None)
            if st.pop("leave", None) is not None:
                st.pop("leave_duration", None)
                self._states.pop(name, None)
            else:
                st.pop("leave_duration", None)
        return snap
