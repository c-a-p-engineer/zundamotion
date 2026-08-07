from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.scene_assembly import (
    SceneAssemblyResult,
)
from zundamotion.components.pipeline_phases.video_phase.scene_result_cache import (
    SceneResultCacheMixin,
)


class _CacheManager:
    def __init__(self) -> None:
        self.calls = []

    def cache_file(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _Harness(SceneResultCacheMixin):
    def __init__(self) -> None:
        self.cache_manager = _CacheManager()

    @staticmethod
    def _cache_key_short(key_data):
        return str(key_data.get("key", "-"))


def _assembly() -> SceneAssemblyResult:
    return SceneAssemblyResult(
        line_clips=(Path("line-1.mp4"),),
        no_sub_path=Path("scene-no-sub.mp4"),
        final_path=Path("scene-final.mp4"),
    )


def _store(harness: _Harness, **overrides):
    kwargs = {
        "scene_id": "scene-a",
        "assembly": _assembly(),
        "cache_scene_base_video": False,
        "subtitle_entries": [],
        "generate_no_sub_video": False,
        "scene_hash_data": {"key": "scene"},
        "scene_base_hash_data": {"key": "base"},
        "scene_sub_hash_data": {"key": "sub"},
        "subtitle_timing_key": "timing",
    }
    kwargs.update(overrides)
    return harness._store_scene_result_cache(**kwargs)


def test_scene_without_subtitles_stores_final_compatibility_entry() -> None:
    harness = _Harness()

    result = _store(harness)

    assert result == Path("scene-final.mp4")
    assert harness.cache_manager.calls == [
        {
            "source_path": Path("scene-final.mp4"),
            "key_data": {"key": "scene"},
            "file_name": "scene_scene-a",
            "extension": "mp4",
        }
    ]


def test_base_and_subtitle_entries_preserve_store_order() -> None:
    harness = _Harness()

    _store(
        harness,
        cache_scene_base_video=True,
        subtitle_entries=[{"text": "hello"}],
    )

    assert harness.cache_manager.calls == [
        {
            "source_path": Path("scene-no-sub.mp4"),
            "key_data": {"key": "base"},
            "file_name": "scene_scene-a_base",
            "extension": "mp4",
        },
        {
            "source_path": Path("scene-final.mp4"),
            "key_data": {"key": "sub"},
            "file_name": "scene_scene-a_sub",
            "extension": "mp4",
        },
    ]


def test_generate_no_sub_video_adds_legacy_scene_hash_entries() -> None:
    harness = _Harness()

    _store(
        harness,
        subtitle_entries=[{"text": "hello"}],
        generate_no_sub_video=True,
    )

    assert harness.cache_manager.calls == [
        {
            "source_path": Path("scene-final.mp4"),
            "key_data": {"key": "sub"},
            "file_name": "scene_scene-a_sub",
            "extension": "mp4",
        },
        {
            "source_path": Path("scene-no-sub.mp4"),
            "key_data": {"key": "scene"},
            "file_name": "scene_scene-a",
            "extension": "mp4",
        },
        {
            "source_path": Path("scene-final.mp4"),
            "key_data": {"key": "scene"},
            "file_name": "scene_scene-a_sub",
            "extension": "mp4",
        },
    ]


def test_no_subtitle_mode_ignores_generate_no_sub_flag() -> None:
    harness = _Harness()

    _store(harness, generate_no_sub_video=True)

    assert len(harness.cache_manager.calls) == 1
    assert harness.cache_manager.calls[0]["file_name"] == "scene_scene-a"
