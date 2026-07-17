from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from zundamotion.utils.ffmpeg_audio import create_silent_audio, mix_audio_tracks
from zundamotion.utils import perf_stats
from zundamotion.utils.ffmpeg_ops import apply_transition_local, concat_videos_safe
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams
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


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
def test_safe_concat_adds_silence_for_audio_less_transition_part(tmp_path: Path):
    async def _run() -> None:
        params = AudioParams(codec="aac", sample_rate=48000, channels=2, bitrate_kbps=128)
        paths: list[str] = []
        for index in range(3):
            path = tmp_path / f"part-{index}.mp4"
            command = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=160x90:r=10:d=0.4",
            ]
            if index != 1:
                command.extend(
                    [
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=48000:cl=stereo",
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        *params.to_ffmpeg_opts(),
                        "-shortest",
                    ]
                )
            command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "0.4", str(path)])
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            assert "non-monotonic dts" not in result.stderr.lower()
            paths.append(str(path))

        output = tmp_path / "mixed-audio-presence.mp4"
        mode = await concat_videos_safe(paths, str(output), params)
        assert mode == "audio_reencode"
        summary = await validate_final_media(str(output), params)
        assert summary["audio_codec"] == "aac"
        assert summary["duration_delta"] <= 0.1

    asyncio.run(_run())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
def test_opening_ending_and_multiple_transitions_have_no_dts_warning(tmp_path: Path):
    async def _run() -> None:
        audio = AudioParams(codec="aac", sample_rate=48000, channels=2, bitrate_kbps=128)
        video = VideoParams(width=160, height=90, fps=10, pix_fmt="yuv420p")
        sources: list[Path] = []
        for name, frequency in (("opening", 440), ("main", 550), ("ending", 660)):
            path = tmp_path / f"{name}.mp4"
            command = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s=160x90:r=10:d=0.7",
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration=0.7",
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                *audio.to_ffmpeg_opts(), "-shortest", str(path),
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            assert "non-monotonic dts" not in result.stderr.lower()
            sources.append(path)

        stats = perf_stats.start_perf_stats()
        first = tmp_path / "opening-main.mp4"
        await apply_transition_local(
            str(sources[0]), str(sources[1]), str(first), "fade", 0.2, 0.5,
            video, audio, wait_padding=0.1, hw_encoder="cpu", consume_next_head=True,
            context={"from_scene": "opening", "to_scene": "main"},
        )
        final = tmp_path / "opening-main-ending.mp4"
        await apply_transition_local(
            str(first), str(sources[2]), str(final), "fade", 0.2, 1.0,
            video, audio, wait_padding=0.1, hw_encoder="cpu", consume_next_head=True,
            context={"from_scene": "main", "to_scene": "ending"},
        )

        summary = await validate_final_media(str(final), audio)
        perf = stats.to_dict()
        assert perf["av_warnings_total"] == 0
        assert summary["audio_codec"] == "aac"
        assert summary["sample_rate"] == 48000
        assert summary["channels"] == 2
        assert abs(summary["video_start"] - summary["audio_start"]) <= 0.1
        assert summary["duration_delta"] <= 0.1

    asyncio.run(_run())
