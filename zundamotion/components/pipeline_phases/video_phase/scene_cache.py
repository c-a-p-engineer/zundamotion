"""Scene cache payloads, component manifests, and subtitle entry construction.

This module is an internal SceneRenderer mixin; use scene_renderer.SceneRenderer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from ....utils import perf_stats
from ....utils.logger import logger
from ....utils.subtitle_text import is_effective_subtitle_text


_SCENE_CACHE_MANIFEST_VERSION = "20260806_scene_components_v1"


class SceneCacheMixin:
    """Build cache payloads and explain scene cache invalidation."""

    def _scene_base_cache_data(self, scene_hash_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build cache data for the no-subtitle scene layer."""
        base_data = self._without_subtitle_only_fields(scene_hash_data)
        base_data.update(
            {
                "scene_cache_layer": "base_no_subtitle",
                "scene_base_cache_version": "20260717_scene_base_v2",
            }
        )
        return base_data

    @classmethod
    def _without_subtitle_only_fields(cls, value: Any) -> Any:
        """Remove fields that affect only the subtitle-burned layer."""

        if isinstance(value, dict):
            return {
                key: cls._without_subtitle_only_fields(item)
                for key, item in value.items()
                if key not in {"subtitle", "subtitle_config", "subtitle_text"}
            }
        if isinstance(value, list):
            return [cls._without_subtitle_only_fields(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._without_subtitle_only_fields(item) for item in value)
        return value

    def _scene_subtitle_cache_data(
        self,
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build cache data for the subtitle-burned scene layer."""
        return {
            **scene_hash_data,
            "scene_cache_layer": "subtitle_burned",
            "scene_subtitle_cache_version": "20260717_scene_sub_v2",
            "scene_base_cache_key": self.cache_manager._generate_hash(
                scene_base_hash_data
            ),
        }

    def _cache_key_short(self, key_data: Dict[str, Any]) -> str:
        try:
            return self.cache_manager._generate_hash(key_data)[:8]
        except Exception:
            return "-"

    def _scene_cache_manifest_path(self, scene_id: str) -> Path:
        safe_scene_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", scene_id).strip("._")
        if not safe_scene_id:
            safe_scene_id = "scene"
        return (
            Path(self.cache_manager.cache_dir)
            / "scene-manifests"
            / f"{safe_scene_id}.base-components.json"
        )

    def _scene_base_component_hashes(
        self,
        scene_base_hash_data: Dict[str, Any],
    ) -> Dict[str, str]:
        """Hash top-level cache payload components without storing raw values."""
        components: Dict[str, str] = {}
        for key in sorted(scene_base_hash_data, key=str):
            component_data = {
                "scene_cache_component": str(key),
                "value": scene_base_hash_data[key],
            }
            components[str(key)] = self._cache_key_short(component_data)
        return components

    def _read_scene_cache_manifest(self, scene_id: str) -> Dict[str, Any] | None:
        if bool(getattr(self.cache_manager, "no_cache", False)):
            return None
        path = self._scene_cache_manifest_path(scene_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "[SceneCacheExplain] scene=%s manifest_read_failed=%s",
                scene_id,
                type(exc).__name__,
            )
            return None
        if data.get("version") != _SCENE_CACHE_MANIFEST_VERSION:
            return None
        return data

    def _write_scene_cache_manifest(
        self,
        *,
        scene_id: str,
        base_key: str,
        components: Dict[str, str],
    ) -> None:
        if bool(getattr(self.cache_manager, "no_cache", False)):
            return
        path = self._scene_cache_manifest_path(scene_id)
        payload = {
            "version": _SCENE_CACHE_MANIFEST_VERSION,
            "scene_id": scene_id,
            "base_key": base_key,
            "components": components,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as exc:
            logger.warning(
                "[SceneCacheExplain] scene=%s manifest_write_failed=%s",
                scene_id,
                type(exc).__name__,
            )

    def _scene_cache_component_keys(
        self,
        scene_hash_data: Dict[str, Any],
        scene_base_hash_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return component keys and differences that explain invalidation."""
        subtitle_config_data = {
            "scene_cache_component": "subtitle_config",
            "subtitle_config": scene_hash_data.get("subtitle_config", {}),
        }
        base_key = self._cache_key_short(scene_base_hash_data)
        current_components = self._scene_base_component_hashes(scene_base_hash_data)
        scene = getattr(self, "scene", {}) or {}
        scene_id = str(scene.get("id") or "unknown")
        previous = self._read_scene_cache_manifest(scene_id)
        previous_components = (
            previous.get("components", {})
            if isinstance(previous, dict)
            and isinstance(previous.get("components", {}), dict)
            else {}
        )
        changed_components = sorted(
            key
            for key in set(previous_components) | set(current_components)
            if previous_components.get(key) != current_components.get(key)
        )
        if previous is None:
            manifest_status = "first_observation"
        elif changed_components:
            manifest_status = "changed"
        else:
            manifest_status = "unchanged"

        detail: Dict[str, Any] = {
            "base_key": base_key,
            "subtitle_config_key": self._cache_key_short(subtitle_config_data),
            "base_components": current_components,
            "previous_base_key": (
                str(previous.get("base_key", "-"))
                if isinstance(previous, dict)
                else "-"
            ),
            "changed_components": changed_components,
            "component_manifest_status": manifest_status,
        }
        self._write_scene_cache_manifest(
            scene_id=scene_id,
            base_key=base_key,
            components=current_components,
        )
        return detail

    def _subtitle_timing_key(self, subtitle_entries: List[Dict[str, Any]]) -> str:
        timing_data = {
            "scene_cache_component": "subtitle_timing",
            "entries": [
                {
                    "text": item.get("text", ""),
                    "start": round(float(item.get("start", 0.0) or 0.0), 3),
                    "duration": round(float(item.get("duration", 0.0) or 0.0), 3),
                    "line_config": item.get("line_config", {}),
                }
                for item in subtitle_entries
            ],
        }
        return self._cache_key_short(timing_data)

    @staticmethod
    def _explain_base_cache_miss(
        reason: str | None,
        detail: Dict[str, Any] | None,
    ) -> str | None:
        if reason != "base_video_not_cached" or not detail:
            return reason
        changed = detail.get("changed_components") or []
        if changed:
            return "base_component_changed"
        if detail.get("component_manifest_status") == "unchanged":
            return "base_cache_entry_missing"
        return "base_cache_not_observed"

    def _record_scene_cache_event(
        self,
        *,
        scene_id: str,
        layer: str,
        status: str,
        key: str = "-",
        reason: str | None = None,
        detail: Dict[str, Any] | None = None,
    ) -> None:
        explained_reason = (
            self._explain_base_cache_miss(reason, detail)
            if layer == "base" and status == "MISS"
            else reason
        )
        changed = list((detail or {}).get("changed_components") or [])
        if layer == "base" and status == "MISS":
            logger.info(
                "[SceneCacheExplain] scene=%s reason=%s changed_components=%s previous_key=%s current_key=%s",
                scene_id,
                explained_reason or "unknown",
                ",".join(changed) if changed else "none",
                (detail or {}).get("previous_base_key", "-"),
                (detail or {}).get("base_key", key),
            )
        perf_stats.record_scene_cache_event(
            scene_id=scene_id,
            layer=layer,
            status=status,
            key=key,
            reason=explained_reason,
            detail=detail,
        )

    def _build_subtitle_entries(
        self,
        scene_id: str,
        start_time_by_idx: Dict[int, float],
    ) -> List[Dict[str, Any]]:
        subtitle_entries: List[Dict[str, Any]] = []
        for idx, _line in enumerate(self.scene.get("lines", []) or [], start=1):
            data = self.line_data_map.get(f"{scene_id}_{idx}") or {}
            text = data.get("text")
            if not is_effective_subtitle_text(text):
                continue
            subtitle_entries.append(
                {
                    "text": text,
                    "line_config": data.get("line_config", {}),
                    "duration": float(data.get("duration", 0.0)),
                    "start": float(start_time_by_idx.get(idx, 0.0)),
                }
            )
        subtitle_entries.sort(key=lambda item: item["start"])
        return subtitle_entries
