import asyncio
import hashlib
import json
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
        self.cache_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def get_cached_path(self, *, key_data, file_name: str, extension: str):
        self.get_calls.append(
            {
                "key_data": key_data,
                "key_hash": self._generate_hash(key_data),
                "file_name": file_name,
                "extension": extension,
            }
        )
        path = self.get_cache_path(
            key_data=key_data,
            file_name=file_name,
            extension=extension,
        )
        return path if path.exists() else None

    def _generate_hash(self, data):
        payload = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_cache_path(self, *, key_data, file_name: str, extension: str) -> Path:
        return self.cache_dir / f"{file_name}_{self._generate_hash(key_data)}.{extension}"

    async def get_or_create(self, *, file_name: str, extension: str, creator_func, **_kwargs):
        return await creator_func(self.cache_dir / f"{file_name}.{extension}")

    def cache_file(self, *, source_path: Path, key_data, file_name: str, extension: str) -> Path:
        target = self.get_cache_path(
            key_data=key_data,
            file_name=file_name,
            extension=extension,
        )
        target.write_bytes(Path(source_path).read_bytes())
        self.cache_calls.append(
            {
                "source_path": source_path,
                "key_data": key_data,
                "key_hash": self._generate_hash(key_data),
                "file_name": file_name,
                "extension": extension,
                "target": target,
            }
        )
        return target


class _DummySubtitleGen:
    def subtitle_render_mode(self) -> str:
        return "ass"


class _DummyFaceCache:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get_scaled_overlay(
        self,
        path: Path,
        scale: float,
        alpha_threshold: int,
        *,
        horizontal_flip: bool = False,
        vertical_flip: bool = False,
    ) -> Path:
        self.calls.append(
            {
                "path": path,
                "scale": scale,
                "alpha_threshold": alpha_threshold,
                "horizontal_flip": horizontal_flip,
                "vertical_flip": vertical_flip,
            }
        )
        return path


class _DummyVideoRenderer:
    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.ffmpeg_path = "ffmpeg"
        self.scale_flags = "lanczos"
        self.apply_fps_filter = False
        self.subtitle_gen = _DummySubtitleGen()
        self.face_cache = _DummyFaceCache()
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


def test_scene_renderer_reuses_cached_base_before_subtitle_burn(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"audio")

        line_config = {"subtitle": {"size": 48}}
        scene = {
            "id": "demo",
            "lines": [{"text": "字幕テスト"}],
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
        phase_base = {
            "config": {
                "background": {"default": "assets/bg/sample.png"},
                "subtitle": {},
                "system": {
                    "generate_no_sub_video": False,
                    "cache_scene_base_video": True,
                },
                "video": {},
            },
            "temp_dir": tmp_path,
            "hw_kind": None,
            "video_params": VideoParams(width=320, height=180, fps=30),
            "audio_params": AudioParams(),
            "video_extensions": {".mp4", ".mov", ".webm", ".avi", ".mkv"},
            "_norm_char_entries": lambda _line: {},
            "clip_workers": 1,
            "auto_tune_enabled": False,
            "parallel_scene_rendering": False,
            "_profile_samples": [],
            "profile_limit": 4,
            "_clip_samples_all": [],
            "_retuned": False,
        }

        cache_manager = _DummyCacheManager(tmp_path / "cache")
        first_video_renderer = _DummyVideoRenderer(tmp_path)
        first_phase = SimpleNamespace(
            **phase_base,
            cache_manager=cache_manager,
            video_renderer=first_video_renderer,
        )
        first_renderer = SceneRenderer(
            phase=first_phase,
            scene=scene,
            scene_hash_data={"scene": "demo", "subtitle_config": {}},
            scene_idx=0,
            total_scenes=1,
            line_data_map=line_data_map,
            timeline=None,
            pbar_scenes=_DummyPbar(),
        )

        await first_renderer.render_scene()

        assert any(call["file_name"] == "scene_demo_base" for call in cache_manager.cache_calls)
        assert any(call["file_name"] == "scene_demo_sub" for call in cache_manager.cache_calls)

        for call in list(cache_manager.cache_calls):
            if call["file_name"] == "scene_demo_sub":
                Path(call["target"]).unlink()

        second_video_renderer = _DummyVideoRenderer(tmp_path)
        second_phase = SimpleNamespace(
            **phase_base,
            cache_manager=cache_manager,
            video_renderer=second_video_renderer,
        )
        second_renderer = SceneRenderer(
            phase=second_phase,
            scene=scene,
            scene_hash_data={"scene": "demo", "subtitle_config": {"font_size": 52}},
            scene_idx=0,
            total_scenes=1,
            line_data_map=line_data_map,
            timeline=None,
            pbar_scenes=_DummyPbar(),
        )

        outputs = await second_renderer.render_scene()

        assert outputs == [tmp_path / "scene_output_demo_sub.mp4"]
        assert second_video_renderer.render_clip_calls == []
        assert len(second_video_renderer.apply_subtitle_calls) == 1
        assert second_video_renderer.apply_subtitle_calls[0][0]["text"] == "字幕テスト"

    asyncio.run(_run())


def test_scene_renderer_scene_cache_key_stays_stable_after_character_persist_mutation(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"audio")

        line_config = {"subtitle": {"size": 48}}
        scene = {
            "id": "demo",
            "characters_persist": True,
            "lines": [
                {
                    "text": "最初",
                    "characters": [
                        {
                            "name": "hero",
                            "expression": "default",
                            "anchor": "bottom_center",
                            "position": {"x": 0, "y": 0},
                            "scale": 1.0,
                        }
                    ],
                },
                {"text": "次"},
            ],
        }
        line_data_map = {
            "demo_1": {
                "type": "talk",
                "text": "最初",
                "audio_path": audio_path,
                "duration": 1.0,
                "line_config": line_config,
            },
            "demo_2": {
                "type": "talk",
                "text": "次",
                "audio_path": audio_path,
                "duration": 1.0,
                "line_config": line_config,
            },
        }

        cache_manager = _DummyCacheManager(tmp_path / "cache")
        phase = SimpleNamespace(
            config={
                "background": {"default": "assets/bg/sample.png"},
                "subtitle": {},
                "system": {
                    "generate_no_sub_video": False,
                    "cache_scene_base_video": True,
                },
                "video": {},
                "defaults": {"characters_persist": False},
            },
            cache_manager=cache_manager,
            video_renderer=_DummyVideoRenderer(tmp_path),
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
            scene_hash_data={
                "scene": "demo",
                "lines": scene["lines"],
                "subtitle_config": {},
            },
            scene_idx=0,
            total_scenes=1,
            line_data_map=line_data_map,
            timeline=None,
            pbar_scenes=_DummyPbar(),
        )

        await renderer.render_scene()

        sub_get = next(
            call for call in cache_manager.get_calls if call["file_name"] == "scene_demo_sub"
        )
        sub_store = next(
            call for call in cache_manager.cache_calls if call["file_name"] == "scene_demo_sub"
        )
        assert sub_get["key_hash"] == sub_store["key_hash"]

    asyncio.run(_run())


def test_scene_renderer_background_persist_fills_missing_line_backgrounds(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")

    scene = {
        "id": "demo",
        "bg": "assets/bg/first.png",
        "lines": [
            {"text": "最初"},
            {
                "text": "切り替え",
                "background": {"path": "assets/bg/second.png"},
            },
            {"text": "継続"},
        ],
    }
    line_data_map = {
        "demo_1": {
            "type": "talk",
            "text": "最初",
            "audio_path": audio_path,
            "duration": 1.0,
            "line_config": {},
        },
        "demo_2": {
            "type": "talk",
            "text": "切り替え",
            "audio_path": audio_path,
            "duration": 1.0,
            "line_config": {},
        },
        "demo_3": {
            "type": "talk",
            "text": "継続",
            "audio_path": audio_path,
            "duration": 1.0,
            "line_config": {},
        },
    }
    phase = SimpleNamespace(
        config={
            "background": {},
            "subtitle": {},
            "system": {
                "generate_no_sub_video": False,
                "cache_scene_base_video": True,
            },
            "video": {},
            "defaults": {"background_persist": True},
        },
        cache_manager=_DummyCacheManager(tmp_path / "cache"),
        video_renderer=_DummyVideoRenderer(tmp_path),
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
        scene_hash_data={
            "scene": "demo",
            "lines": scene["lines"],
            "subtitle_config": {},
        },
        scene_idx=0,
        total_scenes=1,
        line_data_map=line_data_map,
        timeline=None,
        pbar_scenes=_DummyPbar(),
    )

    asyncio.run(renderer.render_scene())

    assert [line["background"]["path"] for line in scene["lines"]] == [
        "assets/bg/first.png",
        "assets/bg/second.png",
        "assets/bg/second.png",
    ]
    assert [
        line_data_map[f"demo_{idx}"]["line_config"]["background"]["path"]
        for idx in range(1, 4)
    ] == [
        "assets/bg/first.png",
        "assets/bg/second.png",
        "assets/bg/second.png",
    ]


def test_scene_renderer_precaches_unique_face_overlay_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def _run() -> None:
        monkeypatch.chdir(tmp_path)
        face_dir = tmp_path / "assets" / "characters" / "hero" / "default"
        mouth_dir = face_dir / "mouth"
        eyes_dir = face_dir / "eyes"
        mouth_dir.mkdir(parents=True)
        eyes_dir.mkdir(parents=True)
        (mouth_dir / "half.png").write_bytes(b"half")
        (mouth_dir / "open.png").write_bytes(b"open")
        (eyes_dir / "close.png").write_bytes(b"close")

        line_config = {
            "characters": [
                {
                    "name": "hero",
                    "expression": "default",
                    "scale": 0.5,
                    "flip": True,
                }
            ],
        }
        face_anim = {
            "target_name": "hero",
            "mouth": [
                {"state": "half", "start": 0.0, "end": 0.1},
                {"state": "open", "start": 0.1, "end": 0.2},
            ],
            "eyes": [{"start": 0.0, "end": 0.1}],
        }
        scene = {
            "id": "demo",
            "lines": [{"text": "a"}, {"text": "b"}],
        }
        line_data_map = {
            "demo_1": {"line_config": line_config, "face_anim": face_anim},
            "demo_2": {"line_config": line_config, "face_anim": face_anim},
        }
        video_renderer = _DummyVideoRenderer(tmp_path)
        phase = SimpleNamespace(
            config={"video": {"precache_face_overlays": True}},
            cache_manager=_DummyCacheManager(tmp_path / "cache"),
            video_renderer=video_renderer,
            temp_dir=tmp_path,
            hw_kind=None,
            video_params=VideoParams(width=320, height=180, fps=30),
            audio_params=AudioParams(),
            video_extensions={".mp4", ".mov", ".webm", ".avi", ".mkv"},
            _norm_char_entries=lambda _line: {},
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

        await renderer._precache_face_overlays(
            scene_id="demo",
            scene=scene,
            line_data_map=line_data_map,
        )

        assert len(video_renderer.face_cache.calls) == 3
        paths = {Path(call["path"]).name for call in video_renderer.face_cache.calls}
        assert paths == {"half.png", "open.png", "close.png"}
        assert {call["scale"] for call in video_renderer.face_cache.calls} == {0.5}
        assert {call["alpha_threshold"] for call in video_renderer.face_cache.calls} == {128}
        assert {call["horizontal_flip"] for call in video_renderer.face_cache.calls} == {True}

    asyncio.run(_run())
