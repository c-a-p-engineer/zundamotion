from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from zundamotion.cache import CacheManager
from zundamotion.components.pipeline_phases.video_phase.scene_renderer import SceneRenderer
from zundamotion.components.video import VideoRenderer
from zundamotion.utils.ffmpeg_audio import create_silent_audio, mix_audio_tracks
from zundamotion.utils import perf_stats
from zundamotion.utils.ffmpeg_ops import apply_transition_local, concat_videos_safe
from zundamotion.utils.ffmpeg_params import AudioParams, VideoParams
from zundamotion.utils.ffmpeg_probe import validate_final_media




def _frame_md5(path: Path, at: float) -> str:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "md5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _sample_rgb(path: Path, at: float) -> tuple[int, int, int]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-vf",
            "scale=1:1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    assert len(result.stdout) >= 3
    return tuple(result.stdout[:3])


def _first_silence_end(path: Path) -> float:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-40dB:d=0.05",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"silence_end:\s*([0-9.]+)", result.stderr)
    assert match is not None, result.stderr
    return float(match.group(1))


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
        first_summary = await validate_final_media(str(first), audio)
        assert first_summary["duration"] == pytest.approx(1.5, abs=0.15)
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
        assert summary["duration"] == pytest.approx(2.3, abs=0.2)

    asyncio.run(_run())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")
def test_j_cut_pre_padding_is_characterized_through_subtitle_and_transition_render(
    tmp_path: Path,
):
    async def _run() -> None:
        font_path = Path("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf")
        if not font_path.exists():
            pytest.skip("locked CI subtitle font is required for this integration test")

        audio = AudioParams(
            codec="aac", sample_rate=48000, channels=2, bitrate_kbps=128
        )
        video = VideoParams(width=160, height=90, fps=10, pix_fmt="yuv420p")
        cache = CacheManager(tmp_path / "cache", no_cache=True)
        cache.set_ephemeral_dir(tmp_path / "ephemeral")
        config = {
            "video": {
                "width": video.width,
                "height": video.height,
                "apply_fps_filter": True,
            },
            "subtitle": {
                "render_mode": "ass",
                "font_path": str(font_path),
                "font_size": 18,
                "font_color": "white",
                "stroke_color": "black",
                "stroke_width": 1,
                "max_chars_per_line": 20,
                "wrap_mode": "chars",
                "max_pixel_width": 140,
                "x": "(w-text_w)/2",
                "y": "h-10-text_h/2",
            },
        }
        renderer = VideoRenderer(
            config,
            tmp_path,
            cache,
            jobs="1",
            hw_kind=None,
            video_params=video,
            audio_params=audio,
            has_cuda_filters=False,
            clip_workers=1,
        )

        previous_bg = tmp_path / "previous.png"
        next_bg = tmp_path / "next.png"
        Image.new("RGB", (160, 90), (20, 40, 220)).save(previous_bg)
        Image.new("RGB", (160, 90), (220, 40, 20)).save(next_bg)

        previous_audio = tmp_path / "previous.wav"
        next_audio = tmp_path / "next.wav"
        for path, frequency in ((previous_audio, 440), (next_audio, 880)):
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={frequency}:sample_rate=48000:duration=0.8",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

        scene = {
            "id": "next",
            "lines": [
                {
                    "id": "jcut",
                    "text": "J-cut characterization",
                    "j_cut": {"duration": 0.3},
                }
            ],
        }
        line_data_map = {
            "next_1": {
                "type": "talk",
                "text": "J-cut characterization",
                "duration": 0.8,
                "line_config": {},
            }
        }
        timing_renderer = object.__new__(SceneRenderer)
        timing_renderer.scene = scene
        timing_renderer.line_data_map = line_data_map
        timing_renderer.cache_manager = cache
        timing = timing_renderer._build_scene_timing_plan(
            scene=scene,
            scene_hash_data={"scene": "next", "subtitle_config": config["subtitle"]},
            scene_base_hash_data={"scene": "next", "scene_cache_layer": "base"},
        )

        assert line_data_map["next_1"]["pre_duration"] == pytest.approx(0.3)
        assert line_data_map["next_1"]["duration"] == pytest.approx(1.1)
        assert timing.subtitle_entries[0]["start"] == pytest.approx(0.0)
        assert timing.subtitle_entries[0]["duration"] == pytest.approx(1.1)

        stats = perf_stats.start_perf_stats()
        previous_clip = await renderer.render_clip(
            audio_path=previous_audio,
            duration=0.8,
            background_config={"type": "image", "path": str(previous_bg)},
            characters_config=[],
            output_filename="previous_scene",
        )
        assert previous_clip is not None
        previous_sub = await renderer.apply_subtitle_overlays(
            Path(previous_clip),
            [
                {
                    "text": "previous scene",
                    "start": 0.0,
                    "duration": 0.8,
                    "line_config": {},
                }
            ],
            scene_id="previous",
        )

        next_clip = await renderer.render_clip(
            audio_path=next_audio,
            duration=float(line_data_map["next_1"]["duration"]),
            background_config={"type": "image", "path": str(next_bg)},
            characters_config=[],
            output_filename="next_scene",
            audio_delay=float(line_data_map["next_1"]["pre_duration"]),
        )
        assert next_clip is not None
        next_sub = await renderer.apply_subtitle_overlays(
            Path(next_clip),
            timing.subtitle_entries,
            scene_id="next",
        )

        # Current compatibility behavior is now explicit: j_cut.duration becomes
        # a same-line pre-roll/audio delay. The subtitle is already visible in
        # that pre-roll, while speech begins after the configured delay.
        assert _first_silence_end(next_sub) == pytest.approx(0.3, abs=0.06)
        assert _frame_md5(Path(next_clip), 0.1) != _frame_md5(next_sub, 0.1)

        final = tmp_path / "jcut-transition.mp4"
        await apply_transition_local(
            str(previous_sub),
            str(next_sub),
            str(final),
            "fade",
            0.2,
            0.6,
            video,
            audio,
            wait_padding=0.1,
            hw_encoder="cpu",
            consume_next_head=True,
            context={"from_scene": "previous", "to_scene": "next"},
        )

        summary = await validate_final_media(str(final), audio)
        perf = stats.to_dict()
        assert perf["av_warnings_total"] == 0
        assert abs(summary["video_start"] - summary["audio_start"]) <= 0.1
        assert summary["duration_delta"] <= 0.1
        assert summary["duration"] == pytest.approx(2.0, abs=0.2)

        early = _sample_rgb(final, 0.2)
        late = _sample_rgb(final, 1.7)
        assert early[2] > early[0]
        assert late[0] > late[2]

    asyncio.run(_run())
