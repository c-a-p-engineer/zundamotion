from pathlib import Path

from zundamotion.components.pipeline_phases.video_phase.scene_completion import (
    SceneCompletionMixin,
)


class _Progress:
    def __init__(self) -> None:
        self.updates = []

    def update(self, amount: int) -> None:
        self.updates.append(amount)


class _CacheManager:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir


class _Harness(SceneCompletionMixin):
    def __init__(self, cache_dir: Path) -> None:
        self.cache_manager = _CacheManager(cache_dir)
        self.pbar_scenes = _Progress()


def test_external_temporary_scene_base_is_removed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    temporary = tmp_path / "scene-base.mp4"
    temporary.write_bytes(b"video")
    harness = _Harness(cache_dir)

    harness._complete_scene_render(temporary)

    assert not temporary.exists()
    assert harness.pbar_scenes.updates == [1]


def test_cached_scene_base_is_preserved(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached = cache_dir / "scene-base.mp4"
    cached.write_bytes(b"video")
    harness = _Harness(cache_dir)

    harness._complete_scene_render(cached)

    assert cached.exists()
    assert harness.pbar_scenes.updates == [1]


def test_missing_scene_base_still_advances_progress(tmp_path: Path) -> None:
    harness = _Harness(tmp_path / "cache")

    harness._complete_scene_render(None)

    assert harness.pbar_scenes.updates == [1]


def test_unlink_failure_is_swallowed_and_progress_advances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    temporary = tmp_path / "scene-base.mp4"
    temporary.write_bytes(b"video")
    harness = _Harness(cache_dir)
    original_unlink = Path.unlink

    def failing_unlink(path: Path, *args, **kwargs):
        if path == temporary:
            raise OSError("busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    harness._complete_scene_render(temporary)

    assert temporary.exists()
    assert harness.pbar_scenes.updates == [1]
