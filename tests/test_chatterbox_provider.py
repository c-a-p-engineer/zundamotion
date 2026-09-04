from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType

import pytest

from zundamotion.authoring import validation_document
from zundamotion.components.audio.chatterbox_generator import ChatterboxAudioGenerator
from zundamotion.components.audio.chatterbox_provider import ChatterboxTTSProvider
from zundamotion.components.audio.factory import create_audio_generator, resolve_tts_provider
from zundamotion.components.config.validate_voice import validate_voice_config
from zundamotion.exceptions import ValidationError
from zundamotion.utils.ffmpeg_params import AudioParams

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, **voice_overrides):
    voice = {
        "provider": "chatterbox",
        "language": "en",
        "device": "cpu",
        "model": "v3",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
    }
    voice.update(voice_overrides)
    return {
        "voice": voice,
        "script": {
            "scenes": [
                {
                    "id": "multilingual",
                    "lines": [
                        {"text": "Hello", "language": "en"},
                        {"text": "Hola", "language": "es"},
                        {"text": "こんにちは", "language": "ja"},
                    ],
                }
            ]
        },
    }


def test_resolve_tts_provider_keeps_voicevox_default() -> None:
    assert resolve_tts_provider({"voice": {}}) == "voicevox"
    assert resolve_tts_provider({}) == "voicevox"
    assert resolve_tts_provider({"voice": {"provider": "ChatterBox"}}) == "chatterbox"


def test_audio_factory_selects_chatterbox_without_loading_runtime(tmp_path: Path) -> None:
    generator = create_audio_generator(
        _config(tmp_path),
        tmp_path,
        AudioParams(),
        object(),
    )

    assert isinstance(generator, ChatterboxAudioGenerator)
    assert generator.provider.provider_id == "chatterbox"
    assert generator.provider._model is None


def test_chatterbox_multilingual_config_validates_without_runtime(tmp_path: Path) -> None:
    config = _config(tmp_path)
    validate_voice_config(config)


def test_repository_chatterbox_sample_validates_through_canonical_loader() -> None:
    document = validation_document(str(ROOT / "scripts" / "sample_chatterbox_multilingual.yaml"))

    assert document["valid"] is True, document["errors"]


def test_chatterbox_rejects_unknown_language(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["script"]["scenes"][0]["lines"][0]["language"] = "xx"

    with pytest.raises(ValidationError, match="language"):
        validate_voice_config(config)


def test_chatterbox_rejects_missing_reference_audio(tmp_path: Path) -> None:
    config = _config(tmp_path, reference_audio=str(tmp_path / "missing.wav"))

    with pytest.raises(ValidationError, match="reference_audio"):
        validate_voice_config(config)


def test_chatterbox_accepts_reference_audio(tmp_path: Path) -> None:
    reference = tmp_path / "speaker.wav"
    reference.write_bytes(b"reference")
    config = _config(tmp_path, reference_audio=str(reference))

    validate_voice_config(config)


def test_chatterbox_rejects_invalid_device_and_cfg_weight(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="device"):
        validate_voice_config(_config(tmp_path, device="auto"))
    with pytest.raises(ValidationError, match="cfg_weight"):
        validate_voice_config(_config(tmp_path, cfg_weight=1.5))


def test_chatterbox_rejects_unknown_model(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="model"):
        validate_voice_config(_config(tmp_path, model="unknown"))


def test_chatterbox_017_loads_fixed_multilingual_model_without_model_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    loaded_model = object()

    class FakeMultilingualTTS:
        @classmethod
        def from_pretrained(cls, **kwargs: object) -> object:
            calls.append(kwargs)
            return loaded_model

    chatterbox_module = ModuleType("chatterbox")
    multilingual_module = ModuleType("chatterbox.mtl_tts")
    multilingual_module.ChatterboxMultilingualTTS = FakeMultilingualTTS
    chatterbox_module.mtl_tts = multilingual_module
    monkeypatch.setitem(sys.modules, "chatterbox", chatterbox_module)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", multilingual_module)

    provider = ChatterboxTTSProvider(model="v3", device="cpu")

    assert provider._load_model() is loaded_model
    assert calls == [{"device": "cpu"}]


def test_chatterbox_writes_wav_with_soundfile_without_torchcodec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, object] = {}

    class FakeTensor:
        ndim = 2
        shape = (1, 3)

        def detach(self):
            return self

        def cpu(self):
            return self

        def float(self):
            return self

        def transpose(self, first: int, second: int):
            calls["transpose"] = (first, second)
            return self

        def numpy(self):
            return "samples"

    class FakeModel:
        sr = 24_000

        def generate(self, text: str, **kwargs: object) -> FakeTensor:
            calls["generate"] = {"text": text, **kwargs}
            return FakeTensor()

    def fake_write(
        filepath: str,
        samples: object,
        sample_rate: int,
        *,
        subtype: str,
    ) -> None:
        calls["write"] = (filepath, samples, sample_rate, subtype)

    soundfile_module = ModuleType("soundfile")
    soundfile_module.write = fake_write
    monkeypatch.setitem(sys.modules, "soundfile", soundfile_module)

    provider = ChatterboxTTSProvider(model="v3", device="cpu")
    provider._model = FakeModel()
    output = tmp_path / "nested" / "speech.wav"
    provider._synthesize_sync("Hello", "en", str(output), None, 0.5, 0.5)

    assert calls["generate"] == {
        "text": "Hello",
        "language_id": "en",
        "audio_prompt_path": None,
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
    }
    assert calls["transpose"] == (0, 1)
    assert calls["write"] == (str(output), "samples", 24_000, "PCM_16")
    assert output.parent.is_dir()


def test_chatterbox_rejects_non_neutral_speed_and_pitch(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="speed"):
        validate_voice_config(_config(tmp_path, speed=1.1))
    with pytest.raises(ValidationError, match="pitch"):
        validate_voice_config(_config(tmp_path, pitch=0.1))
