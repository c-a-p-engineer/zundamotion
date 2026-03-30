import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zundamotion.components.pipeline_phases.video_phase.scene_renderer import SceneRenderer
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams


class _DummyPbar:
    def update(self, _value: int) -> None:
        return None

    def set_description(self, _value: str) -> None:
        return None


class _DummyCacheManager:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached_path(self, **_kwargs):
        return None

    async def get_or_create(self, *, file_name: str, extension: str, creator_func, **_kwargs):
        return await creator_func(self.cache_dir / f"{file_name}.{extension}")

    def cache_file(self, **_kwargs) -> None:
        return None


class _DummySubtitleGen:
    def subtitle_render_mode(self) -> str:
        return "ass"


class _DummyVideoRenderer:
    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.ffmpeg_path = "ffmpeg"
        self.scale_flags = "lanczos"
        self.apply_fps_filter = False
        self.subtitle_gen = _DummySubtitleGen()
        self.render_clip_calls: list[dict[str, object]] = []
        self.apply_subtitle_calls: list[list[dict[str, object]]] = []

    async def render_clip(self, **kwargs):
        self.render_clip_calls.append(
            {
                "subtitle_text": kwargs.get("subtitle_text"),
                "subtitle_line_config": kwargs.get("subtitle_line_config"),
            }
        )
        output_path = self.temp_dir / f"{kwargs['output_filename']}.mp4"
        output_path.write_bytes(b"clip")
        return output_path

    async def concat_clips(self, _clips, output_path: str):
        out = Path(output_path)
        out.write_bytes(b"scene")
        return out

    async def apply_subtitle_overlays(self, _base_video: Path, subtitles):
        self.apply_subtitle_calls.append(subtitles)
        output_path = self.temp_dir / "scene_output_demo_sub.mp4"
        output_path.write_bytes(b"scene-sub")
        return output_path

    async def apply_foreground_overlays(self, base_video: Path, _overlays):
        return base_video

    async def apply_overlays(self, base_video: Path, _overlays, _subtitles):
        return base_video


def test_scene_renderer_keeps_subtitles_scene_level_while_passing_line_config_for_face_fallback(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"audio")

        line_config = {
            "subtitle": {"size": 48},
            "characters": [
                {
                    "name": "hero",
                    "visible": True,
                    "expression": "default",
                    "anchor": "bottom_center",
                    "position": {"x": 0, "y": 0},
                    "scale": 1.0,
                }
            ],
        }
        scene = {
            "id": "demo",
            "lines": [
                {
                    "text": "字幕テスト",
                    "characters": line_config["characters"],
                }
            ],
        }
        line_data_map = {
            "demo_1": {
                "type": "talk",
                "text": "字幕テスト",
                "audio_path": audio_path,
                "duration": 1.0,
                "line_config": line_config,
            }
        }

        cache_manager = _DummyCacheManager(tmp_path / "cache")
        video_renderer = _DummyVideoRenderer(tmp_path)
        phase = SimpleNamespace(
            config={
                "background": {"default": "assets/bg/sample.png"},
                "subtitle": {},
                "system": {"generate_no_sub_video": False},
                "video": {},
            },
            cache_manager=cache_manager,
            video_renderer=video_renderer,
            temp_dir=tmp_path,
            hw_kind=None,
            video_params=VideoParams(width=320, height=180, fps=30),
            audio_params=AudioParams(),
            video_extensions={".mp4", ".mov", ".webm", ".avi", ".mkv"},
            _norm_char_entries=lambda _line: {},
            clip_workers=1,
            auto_tune_enabled=False,
            parallel_scene_rendering=False,
            _profile_samples=[],
            profile_limit=4,
            _clip_samples_all=[],
            _retuned=False,
        )

        renderer = SceneRenderer(
            phase=phase,
            scene=scene,
            scene_hash_data={"scene": "demo"},
            scene_idx=0,
            total_scenes=1,
            line_data_map=line_data_map,
            timeline=None,
            pbar_scenes=_DummyPbar(),
        )

        outputs = await renderer.render_scene()

        assert outputs == [tmp_path / "scene_output_demo_sub.mp4"]
        assert len(video_renderer.render_clip_calls) == 1
        assert video_renderer.render_clip_calls[0]["subtitle_text"] is None
        assert video_renderer.render_clip_calls[0]["subtitle_line_config"] == line_config
        assert len(video_renderer.apply_subtitle_calls) == 1
        assert video_renderer.apply_subtitle_calls[0][0]["text"] == "字幕テスト"

    asyncio.run(_run())
