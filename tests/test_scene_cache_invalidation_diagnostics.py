from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from zundamotion.components.pipeline_phases.video_phase.scene_cache import (
    _SCENE_CACHE_MANIFEST_VERSION,
    SceneCacheMixin,
)


class _CacheManager:
    def __init__(self, cache_dir: Path, *, no_cache: bool = False) -> None:
        self.cache_dir = cache_dir
        self.no_cache = no_cache

    def _generate_hash(self, value: dict[str, Any]) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Subject(SceneCacheMixin):
    def __init__(self, cache_dir: Path) -> None:
        self.cache_manager = _CacheManager(cache_dir)
        self.scene = {"id": "intro/scene"}
        self.line_data_map: dict[str, Any] = {}


def _base(*, background: str = "a.png", width: int = 1920) -> dict[str, Any]:
    return {
        "background": {"path": background},
        "video_params": {"width": width, "height": 1080, "fps": 30},
        "scene_cache_layer": "base_no_subtitle",
    }


def test_first_observation_writes_hash_only_manifest(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)

    detail = subject._scene_cache_component_keys(
        {"subtitle_config": {"font_size": 64}},
        _base(),
    )

    assert detail["component_manifest_status"] == "first_observation"
    assert detail["manifest_read_status"] == "manifest_missing"
    assert detail["changed_components"] == []
    assert subject._explain_base_cache_miss(
        "base_video_not_cached", detail
    ) == "base_manifest_missing"
    manifest_path = subject._scene_cache_manifest_path("intro/scene")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["scene_id"] == "intro/scene"
    assert set(manifest["components"]) == {
        "background",
        "scene_cache_layer",
        "video_params",
    }
    serialized = manifest_path.read_text(encoding="utf-8")
    assert "a.png" not in serialized
    assert "1920" not in serialized


def test_changed_component_is_reported_by_name(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    subject._scene_cache_component_keys({}, _base())

    detail = subject._scene_cache_component_keys(
        {},
        _base(background="b.png"),
    )

    assert detail["component_manifest_status"] == "changed"
    assert detail["manifest_read_status"] == "observed"
    assert detail["changed_components"] == ["background"]
    assert subject._explain_base_cache_miss(
        "base_video_not_cached",
        detail,
    ) == "base_component_changed"


def test_unchanged_components_explain_missing_cache_entry(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    subject._scene_cache_component_keys({}, _base())

    detail = subject._scene_cache_component_keys({}, _base())

    assert detail["component_manifest_status"] == "unchanged"
    assert detail["manifest_read_status"] == "observed"
    assert detail["changed_components"] == []
    assert subject._explain_base_cache_miss(
        "base_video_not_cached",
        detail,
    ) == "base_cache_entry_missing"


def test_version_mismatch_is_distinct_from_first_observation(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    path = subject._scene_cache_manifest_path("intro/scene")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": "old", "components": {}, "base_key": "old"}),
        encoding="utf-8",
    )

    detail = subject._scene_cache_component_keys({}, _base())

    assert detail["manifest_read_status"] == "manifest_version_mismatch"
    assert subject._explain_base_cache_miss(
        "base_video_not_cached", detail
    ) == "base_manifest_version_changed"
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["version"] == _SCENE_CACHE_MANIFEST_VERSION


def test_corrupt_manifest_has_explicit_reason(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    path = subject._scene_cache_manifest_path("intro/scene")
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    detail = subject._scene_cache_component_keys({}, _base())

    assert detail["manifest_read_status"] == "manifest_corrupt"
    assert subject._explain_base_cache_miss(
        "base_video_not_cached", detail
    ) == "base_manifest_corrupt"


def test_unrelated_cache_reason_is_preserved(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    detail = subject._scene_cache_component_keys({}, _base())

    assert subject._explain_base_cache_miss("cache_disabled", detail) == "cache_disabled"


def test_no_cache_mode_does_not_persist_manifest(tmp_path: Path) -> None:
    subject = _Subject(tmp_path)
    subject.cache_manager.no_cache = True

    detail = subject._scene_cache_component_keys({}, _base())

    assert detail["component_manifest_status"] == "first_observation"
    assert detail["manifest_read_status"] == "cache_disabled"
    assert not subject._scene_cache_manifest_path("intro/scene").exists()
