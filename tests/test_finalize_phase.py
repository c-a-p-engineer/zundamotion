import asyncio
from pathlib import Path

from zundamotion.components.pipeline_phases.finalize_phase import FinalizePhase
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


class DummyCacheManager:
    async def get_or_create(self, *, file_name: str, extension: str, creator_func, **_kwargs):
        return await creator_func(Path(f"{file_name}.{extension}"))


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
