import asyncio
from pathlib import Path

import pytest

from zundamotion.components.pipeline_phases.finalize_phase import FinalizePhase
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


class DummyCacheManager:
    async def get_or_create(self, *, file_name: str, extension: str, creator_func, **_kwargs):
        return await creator_func(Path(f"{file_name}.{extension}"))


class PersistentDummyCacheManager:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.creator_calls = 0

    async def get_or_create(self, *, creator_func, **_kwargs):
        if self.cache_path.exists():
            return self.cache_path
        self.creator_calls += 1
        return await creator_func(self.cache_path)


def test_finalize_phase_uses_distinct_output_paths(monkeypatch, tmp_path: Path) -> None:
    async def _run() -> None:
        async def fake_get_media_duration(_path: str, caller: str | None = None) -> float:
            return 1.0

        async def fake_compare_media_params(_paths: list[str]) -> bool:
            return True

        async def fake_concat_videos_safe(
            _inputs: list[str],
            output_path: str,
            _audio_params,
            movflags_faststart: bool = True,
            context=None,
        ) -> str:
            Path(output_path).write_bytes(b"mp4")
            return "copy"

        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.get_media_duration",
            fake_get_media_duration,
        )
        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.compare_media_params",
            fake_compare_media_params,
        )
        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.concat_videos_safe",
            fake_concat_videos_safe,
        )

        phase = FinalizePhase(
            config={"system": {"finalize_cache": False}},
            temp_dir=tmp_path,
            cache_manager=DummyCacheManager(),
            video_params=VideoParams(),
            audio_params=AudioParams(),
        )

        scene_sub = tmp_path / "scene_output_demo_sub.mp4"
        scene_sub.write_bytes(b"scene-sub")
        scene_no_sub = tmp_path / "scene_output_demo.mp4"
        scene_no_sub.write_bytes(b"scene")

        final_with_sub = await phase.run(
            scenes=[{"id": "demo"}],
            timeline=None,
            line_data_map={},
            scene_video_paths=[scene_sub],
            used_voicevox_info=[],
            output_stem="final_output",
        )
        final_no_sub = await phase.run(
            scenes=[{"id": "demo"}],
            timeline=None,
            line_data_map={},
            scene_video_paths=[scene_no_sub],
            used_voicevox_info=[],
            output_stem="final_output_no_sub",
        )

        assert final_with_sub == tmp_path / "final_output.mp4"
        assert final_no_sub == tmp_path / "final_output_no_sub.mp4"
        assert final_with_sub.read_bytes() == b"mp4"
        assert final_no_sub.read_bytes() == b"mp4"

    asyncio.run(_run())


def test_finalize_phase_rebuilds_truncated_final_concat_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        scene_path = tmp_path / "scene.mp4"
        scene_path.write_bytes(b"scene")
        cached_path = tmp_path / "finalize_concat_cached.mp4"
        cached_path.write_bytes(b"truncated")
        cache_manager = PersistentDummyCacheManager(cached_path)

        async def fake_get_media_duration(path: str, caller: str | None = None) -> float:
            del caller
            return 0.63 if Path(path).read_bytes() == b"truncated" else 10.0

        async def fake_compare_media_params(_paths: list[str]) -> bool:
            return True

        async def fake_concat_videos_safe(
            _inputs: list[str],
            output_path: str,
            _audio_params,
            movflags_faststart: bool = True,
            context=None,
        ) -> str:
            del movflags_faststart, context
            Path(output_path).write_bytes(b"complete")
            return "copy"

        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.get_media_duration",
            fake_get_media_duration,
        )
        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.compare_media_params",
            fake_compare_media_params,
        )
        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.concat_videos_safe",
            fake_concat_videos_safe,
        )

        phase = FinalizePhase(
            config={"system": {"finalize_cache": True}},
            temp_dir=tmp_path,
            cache_manager=cache_manager,
            video_params=VideoParams(),
            audio_params=AudioParams(),
        )

        result = await phase.run(
            scenes=[{"id": "demo"}],
            timeline=None,
            line_data_map={},
            scene_video_paths=[scene_path],
            used_voicevox_info=[],
        )

        assert result == cached_path
        assert result.read_bytes() == b"complete"
        assert cache_manager.creator_calls == 1
        assert not list(tmp_path.glob("*.partial-*.mp4"))

    asyncio.run(_run())


def test_finalize_phase_keeps_valid_final_concat_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        scene_path = tmp_path / "scene.mp4"
        scene_path.write_bytes(b"scene")
        cached_path = tmp_path / "finalize_concat_cached.mp4"
        cached_path.write_bytes(b"complete")
        cache_manager = PersistentDummyCacheManager(cached_path)

        async def fake_get_media_duration(_path: str, caller: str | None = None) -> float:
            del caller
            return 10.0

        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.finalize_phase.get_media_duration",
            fake_get_media_duration,
        )

        phase = FinalizePhase(
            config={"system": {"finalize_cache": True}},
            temp_dir=tmp_path,
            cache_manager=cache_manager,
            video_params=VideoParams(),
            audio_params=AudioParams(),
        )

        result = await phase.run(
            scenes=[{"id": "demo"}],
            timeline=None,
            line_data_map={},
            scene_video_paths=[scene_path],
            used_voicevox_info=[],
        )

        assert result == cached_path
        assert result.read_bytes() == b"complete"
        assert cache_manager.creator_calls == 0

    asyncio.run(_run())


def test_finalize_phase_does_not_publish_failed_partial_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        cached_path = tmp_path / "finalize_concat_cached.mp4"
        cache_manager = PersistentDummyCacheManager(cached_path)

        async def failing_creator(output_path: Path) -> Path:
            output_path.write_bytes(b"partial")
            raise RuntimeError("render stopped")

        phase = FinalizePhase(
            config={"system": {"finalize_cache": True}},
            temp_dir=tmp_path,
            cache_manager=cache_manager,
            video_params=VideoParams(),
            audio_params=AudioParams(),
        )

        with pytest.raises(RuntimeError, match="render stopped"):
            await phase._get_or_create_finalize_cache(
                key_data={"test": "failed-partial"},
                file_name="finalize_concat",
                extension="mp4",
                creator_func=failing_creator,
                expected_duration=10.0,
                cache_label="final concat",
            )

        assert not cached_path.exists()
        assert not list(tmp_path.glob("*.partial-*.mp4"))

    asyncio.run(_run())
