from __future__ import annotations

from typing import Any, Dict, List


class BadgeTracker:
    """Scene-local tracker for persistent badges toggled by line updates."""

    def __init__(self) -> None:
        self._states: Dict[str, Dict[str, Any]] = {}

    def prime(self, definitions: List[Dict[str, Any]]) -> None:
        for item in definitions or []:
            badge_id = item.get("id")
            if not badge_id:
                continue
            state = dict(item)
            state.setdefault("visible", True)
            self._states[str(badge_id)] = state

    def has(self, badge_id: str) -> bool:
        return str(badge_id) in self._states

    def apply(self, updates: List[Dict[str, Any]]) -> None:
        for upd in updates or []:
            badge_id = upd.get("id")
            if not badge_id:
                continue
            current = self._states.get(str(badge_id), {}).copy()
            current.update({k: v for k, v in upd.items() if k != "id"})
            current["id"] = str(badge_id)
            current.setdefault("visible", False)
            self._states[str(badge_id)] = current

    def snapshot(self) -> List[Dict[str, Any]]:
        visible: List[Dict[str, Any]] = []
        for state in self._states.values():
            if state.get("visible", False):
                visible.append(state.copy())
        return visible
