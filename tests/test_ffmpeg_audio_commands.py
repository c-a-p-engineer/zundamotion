from __future__ import annotations

import asyncio
from types import SimpleNamespace

from zundamotion.utils.ffmpeg_audio import create_silent_audio, mix_audio_tracks
from zundamotion.utils.ffmpeg_params import AudioParams


def test_silent_and_mix_commands_encode_pcm_wav(monkeypatch, tmp_path):
    commands = []

    async def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setitem(create_silent_audio.__globals__, "_run_ffmpeg_async", fake_run)
    params = AudioParams(codec="aac", sample_rate=48000, channels=2)

    asyncio.run(create_silent_audio(str(tmp_path / "silent.wav"), 0.1, params))
    asyncio.run(
        mix_audio_tracks(
            [("voice.wav", 0.0, 1.0)],
            str(tmp_path / "mixed.wav"),
            total_duration=0.1,
            audio_params=params,
        )
    )

    for command in commands:
        assert command[command.index("-c:a") + 1] == "pcm_s16le"
        assert "-b:a" not in command
