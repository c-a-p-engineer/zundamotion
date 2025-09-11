# -*- coding: utf-8 -*-
"""FFmpeg を用いた音声処理ユーティリティ群。"""

from __future__ import annotations

from typing import List, Optional, Tuple
import subprocess

from .ffmpeg_capabilities import _threading_flags
from .ffmpeg_hw import get_profile_flags
from .ffmpeg_params import AudioParams
from .ffmpeg_probe import get_audio_duration, get_media_duration, get_media_info
from .ffmpeg_runner import run_ffmpeg_async as _run_ffmpeg_async
from .logger import logger


async def has_audio_stream(file_path: str) -> bool:
    """動画に音声ストリームが存在するか判定する。"""
    media_info = await get_media_info(file_path)
    return media_info.get("audio") is not None


async def create_silent_audio(
    output_path: str,
    duration: float,
    audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    """指定秒数の無音WAVを生成する。"""
    cl = "mono" if audio_params.channels == 1 else "stereo"
    cmd = [
        ffmpeg_path,
        "-y",
        *get_profile_flags(),
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={audio_params.sample_rate}:cl={cl}",
        "-t",
        str(duration),
    ]
    cmd.extend(audio_params.to_ffmpeg_opts())
    cmd.append(output_path)
    try:
        await _run_ffmpeg_async(cmd)
        logger.debug(f"Created silent audio: {output_path} ({duration}s)")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error creating silent audio file {output_path}: {e}")
        logger.error(f"STDOUT: {e.stdout}\nSTDERR: {e.stderr}")
        raise


async def add_bgm_to_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    audio_params: AudioParams,
    bgm_volume: float = 0.5,
    bgm_start_time: float = 0.0,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    video_duration: Optional[float] = None,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    """動画にBGMを合成して出力する。"""
    if video_duration is None:
        video_duration = await get_media_duration(video_path)
    bgm_duration = await get_audio_duration(bgm_path)

    cmd = [ffmpeg_path, "-y", *get_profile_flags()]
    cmd.extend(_threading_flags(ffmpeg_path))
    cmd.extend(["-i", video_path, "-i", bgm_path, "-filter_complex"])

    video_has_audio = await has_audio_stream(video_path)

    af = [f"volume={bgm_volume}"]
    if fade_in_duration > 0:
        af.append(f"afade=t=in:st=0:d={fade_in_duration}")
    if fade_out_duration > 0:
        st = max(0.0, bgm_duration - fade_out_duration)
        af.append(f"afade=t=out:st={st}:d={fade_out_duration}")
    bgm_chain = f"[1:a]{','.join(af)}[bgm_filtered]"
    delayed = f"[bgm_filtered]adelay={int(bgm_start_time * 1000)}:all=1[delayed_bgm]"

    audio_opts = audio_params.to_ffmpeg_opts()
    if video_has_audio:
        filter_complex = f"{bgm_chain};{delayed};[0:a][delayed_bgm]amix=inputs=2:duration=shortest[aout]"
        cmd.append(filter_complex)
        cmd.extend([
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
        ])
        cmd.extend(audio_opts)
        cmd.extend(["-shortest", output_path])
    else:
        filter_complex = f"{bgm_chain};{delayed}"
        cmd.append(filter_complex)
        cmd.extend([
            "-map",
            "0:v",
            "-map",
            "[delayed_bgm]",
            "-c:v",
            "copy",
        ])
        cmd.extend(audio_opts)
        cmd.extend(["-shortest", output_path])

    try:
        proc = await _run_ffmpeg_async(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully added BGM to {video_path} -> {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error adding BGM to video: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise


async def mix_audio_tracks(
    audio_tracks: List[Tuple[str, float, float]],
    output_path: str,
    total_duration: float,
    audio_params: AudioParams,
    ffmpeg_path: str = "ffmpeg",
) -> None:
    """複数の音声（パス, 開始秒, 音量）をミックスしてMP3で出力する。"""
    try:
        cmd = [ffmpeg_path, "-y"]
        cmd.extend(_threading_flags(ffmpeg_path))
        for track in audio_tracks:
            cmd.extend(["-i", track[0]])

        parts = []
        for i, (_, start, vol) in enumerate(audio_tracks):
            parts.append(f"[{i}:a]volume={vol},adelay={int(start * 1000)}:all=1[a{i}]")
        mix_in = "".join(f"[a{i}]" for i in range(len(audio_tracks)))
        parts.append(f"{mix_in}amix=inputs={len(audio_tracks)}:dropout_transition=0[aout]")

        cmd.extend(["-filter_complex", ";".join(parts), "-map", "[aout]"])
        cmd.extend([
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{audio_params.bitrate_kbps}k",
            "-ar",
            str(audio_params.sample_rate),
            "-ac",
            str(audio_params.channels),
            "-t",
            str(total_duration),
            output_path,
        ])

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        proc = await _run_ffmpeg_async(cmd)
        logger.debug(f"FFmpeg stdout:\n{proc.stdout}")
        logger.debug(f"FFmpeg stderr:\n{proc.stderr}")
        logger.info(f"Successfully mixed audio tracks to {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error mixing audio tracks: {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        raise
