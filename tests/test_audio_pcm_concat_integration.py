from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from zundamotion.utils.ffmpeg_audio import create_silent_audio, mix_audio_tracks
from zundamotion.utils.ffmpeg_ops import concat_videos_safe
from zundamotion.utils.ffmpeg_params import AudioParams
from zundamotion.utils.ffmpeg_probe import validate_final_media


def _probe_codec(path: Path) -> str:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
def test_pcm_intermediates_and_three_clip_concat_have_monotonic_dts(tmp_path: Path):
    async def _run() -> None:
        params = AudioParams(codec="aac", sample_rate=48000, channels=2, bitrate_kbps=128)
        silent = tmp_path / "silent.wav"
        mixed = tmp_path / "mixed.wav"
        await create_silent_audio(str(silent), 0.4, params)
        await mix_audio_tracks(
            [(str(silent), 0.0, 1.0), (str(silent), 0.05, 0.5)],
            str(mixed),
            total_duration=0.45,
            audio_params=params,
        )
        assert _probe_codec(silent) == "pcm_s16le"
        assert _probe_codec(mixed) == "pcm_s16le"

        clips: list[str] = []
        for index, source in enumerate((silent, mixed, silent)):
            clip = tmp_path / f"line-{index}.mp4"
            command = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=160x90:r=10:d=0.4",
                "-i",
                str(source),
                "-filter_complex",
                "[0:v]setpts=PTS-STARTPTS[v];"
                "[1:a]aresample=48000,asetpts=PTS-STARTPTS,"
                "apad=whole_dur=0.4,atrim=duration=0.4[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                *params.to_ffmpeg_opts(),
                "-t",
                "0.4",
                str(clip),
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            assert "non-monotonic dts" not in result.stderr.lower()
            assert "non monotonically increasing dts" not in result.stderr.lower()
            clips.append(str(clip))

        output = tmp_path / "concat.mp4"
        mode = await concat_videos_safe(clips, str(output), params)
        assert mode == "audio_reencode"
        summary = await validate_final_media(str(output), params)
        assert summary["audio_codec"] == "aac"
        assert summary["duration_delta"] <= 0.1

    asyncio.run(_run())
