import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from zundamotion.components.pipeline_phases.audio_phase import AudioPhase
from zundamotion.utils.ffmpeg_params import AudioParams


class StubCacheManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._saved: Dict[str, Path] = {}
        self._generated: Dict[str, Path] = {}

    def _key(self, key_data: Dict[str, Any], file_name: str, extension: str) -> str:
        return json.dumps(key_data, sort_keys=True) + f":{file_name}.{extension}"

    def save_to_cache(
        self,
        *,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
        source_path: Path,
    ) -> None:
        self._saved[self._key(key_data, file_name, extension)] = Path(source_path)

    def get_cache_path(
        self, *, key_data: Dict[str, Any], file_name: str, extension: str
    ) -> Path:
        return self._saved.get(
            self._key(key_data, file_name, extension),
            self.base_dir / f"{file_name}.{extension}",
        )

    async def get_or_create_media_duration(self, _path: Path) -> float:
        return 0.8

    async def get_or_create(
        self,
        *,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
        creator_func,
    ) -> Path:
        cache_key = self._key(key_data, file_name, extension)
        if cache_key in self._generated:
            return self._generated[cache_key]
        out_path = self.base_dir / f"{file_name}_{len(self._generated)}.{extension}"
        result_path = await creator_func(out_path)
        self._generated[cache_key] = Path(result_path)
        return self._generated[cache_key]


class StubTimeline:
    def __init__(self) -> None:
        self.events: List[Tuple[str, float, Any]] = []

    def add_scene_change(self, *_args, **_kwargs) -> None:
        return None

    def add_event(self, description, duration, text=None) -> None:
        self.events.append((description, duration, text))


def test_voice_layers_generate_per_character_face_anim(monkeypatch, tmp_path):
    async def _run() -> None:
        config = {
            "video": {
                "fps": 30,
                "face_anim": {
                    "mouth_fps": 15,
                    "mouth_thr_half": 0.2,
                    "mouth_thr_open": 0.5,
                    "blink_min_interval": 2.0,
                    "blink_max_interval": 5.0,
                    "blink_close_frames": 2,
                },
            },
            "voice": {},
            "system": {"video_extensions": [".mp4"]},
        }

        audio_params = AudioParams()
        cache_manager = StubCacheManager(tmp_path)
        audio_phase = AudioPhase(config, tmp_path, cache_manager, audio_params)

        mixed_audio = tmp_path / "layered_mixed.wav"
        mixed_audio.write_bytes(b"00")
        copetan_audio = tmp_path / "copetan.wav"
        copetan_audio.write_bytes(b"copetan")
        engy_audio = tmp_path / "engy.wav"
        engy_audio.write_bytes(b"engy")

        async def fake_generate_audio(
            text: str, line_config: Dict[str, Any], output_filename: str
        ) -> Tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
            return (
                mixed_audio,
                [(3, text), (8, text)],
                [
                    {
                        "audio_path": copetan_audio,
                        "start_time": 0.0,
                        "duration": 0.6,
                        "layer_origin": 0,
                        "speaker_name": "copetan",
                    },
                    {
                        "audio_path": engy_audio,
                        "start_time": 0.12,
                        "duration": 0.7,
                        "layer_origin": 1,
                        "speaker_name": "engy",
                    },
                ],
            )

        audio_phase.audio_gen.generate_audio = fake_generate_audio  # type: ignore[assignment]

        def fake_compute_mouth_timeline(audio_path: Path, **_kwargs) -> List[Dict[str, Any]]:
            name = Path(audio_path).name
            if name == "copetan.wav":
                return [
                    {"start": 0.0, "end": 0.25, "state": "open"},
                    {"start": 0.25, "end": 0.5, "state": "half"},
                ]
            if name == "engy.wav":
                return [
                    {"start": 0.05, "end": 0.2, "state": "half"},
                    {"start": 0.2, "end": 0.45, "state": "open"},
                ]
            return []

        monkeypatch.setattr(
            "zundamotion.components.pipeline_phases.audio_phase.compute_mouth_timeline",
            fake_compute_mouth_timeline,
        )

        timeline = StubTimeline()
        scenes = [
            {
                "id": "layered_voice_demo",
                "lines": [
                    {
                        "text": "二人揃って、ご挨拶なのだ！",
                        "speaker_name": "copetan & engy",
                        "voice_layers": [
                            {"speaker_name": "copetan", "text": "foo"},
                            {"speaker_name": "engy", "text": "bar", "start_time": 0.12},
                        ],
                        "characters": [
                            {"name": "copetan", "expression": "smile", "visible": True},
                            {"name": "engy", "expression": "wink", "visible": True},
                        ],
                    }
                ],
            }
        ]

        line_data_map, _voice_usage = await audio_phase.run(scenes, timeline)
        line_key = "layered_voice_demo_1"
        face_anim = line_data_map[line_key]["face_anim"]

        assert isinstance(face_anim, list)
        assert {entry["target_name"] for entry in face_anim} == {"copetan", "engy"}

        copetan_anim = next(entry for entry in face_anim if entry["target_name"] == "copetan")
        engy_anim = next(entry for entry in face_anim if entry["target_name"] == "engy")

        assert copetan_anim["mouth"][0]["start"] == pytest.approx(0.0, abs=1e-3)
        assert copetan_anim["mouth"][1]["start"] == pytest.approx(0.25, abs=1e-3)
        assert engy_anim["mouth"][0]["start"] == pytest.approx(0.17, abs=1e-3)
        assert engy_anim["mouth"][1]["start"] == pytest.approx(0.32, abs=1e-3)

    asyncio.run(_run())


def test_audio_phase_prefetches_audio_generation_concurrently(tmp_path):
    async def _run() -> None:
        config = {
            "video": {"fps": 30, "face_anim": {}},
            "voice": {"parallel_workers": 2},
            "system": {"video_extensions": [".mp4"]},
        }

        audio_phase = AudioPhase(config, tmp_path, StubCacheManager(tmp_path), AudioParams())
        timeline = StubTimeline()

        current = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_generate_audio(
            text: str, line_config: Dict[str, Any], output_filename: str
        ) -> Tuple[Path, List[Tuple[int, str]], List[Dict[str, Any]]]:
            nonlocal current, max_in_flight
            async with lock:
                current += 1
                max_in_flight = max(max_in_flight, current)
            await asyncio.sleep(0.05)
            out_path = tmp_path / f"{output_filename}.wav"
            out_path.write_bytes(b"wav")
            async with lock:
                current -= 1
            return out_path, [(3, text)], []

        audio_phase.audio_gen.generate_audio = fake_generate_audio  # type: ignore[assignment]

        scenes = [
            {
                "id": "parallel_audio",
                "lines": [
                    {"text": "一行目", "speaker_name": "copetan"},
                    {"text": "二行目", "speaker_name": "copetan"},
                ],
            }
        ]

        line_data_map, voice_usage = await audio_phase.run(scenes, timeline)

        assert max_in_flight >= 2
        assert list(line_data_map.keys()) == ["parallel_audio_1", "parallel_audio_2"]
        assert voice_usage == [(3, "一行目"), (3, "二行目")]
        assert [event[0] for event in timeline.events] == [
            'copetan: "一行目"',
            'copetan: "二行目"',
        ]

    asyncio.run(_run())
