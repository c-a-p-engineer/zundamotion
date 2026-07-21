from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from write_build_info import build_payload, write_build_info


def test_build_payload_uses_runtime_query_results() -> None:
    responses = {
        ("ffmpeg", "-version"): "ffmpeg version N-12345\nextra\n",
        ("ffmpeg", "-buildconf"): "configuration: --enable-gpl --enable-libfreetype\n",
        ("ffmpeg", "-hide_banner", "-encoders"): " V....D libx264\n V....D h264_nvenc\n",
        ("ffmpeg", "-hide_banner", "-filters"): " ... overlay_cuda\n ... scale_opencl\n",
        (sys.executable, "--version"): "Python 3.14.0\n",
    }

    payload = build_payload(
        profile="gpu",
        ffmpeg_source_url="https://example.test/ffmpeg.tar.xz",
        ffmpeg_source_sha256="a" * 64,
        nv_codec_headers="n12.2.72.0",
        cuda_base_image="nvidia/cuda:test",
        command_runner=lambda command: responses[tuple(command)],
        python_base_image="python:test@sha256:" + "b" * 64,
        voicevox_cpu="voicevox:cpu@test",
        voicevox_gpu="voicevox:gpu@test",
        required_font_path="/fonts/ipag.ttf",
    )

    assert payload["ffmpeg_version"] == "ffmpeg version N-12345"
    assert payload["encoders"] == {
        "libx264": True,
        "libx265": False,
        "h264_nvenc": True,
        "hevc_nvenc": False,
        "aac": False,
    }
    assert payload["filters"]["libfreetype"] is True
    assert payload["filters"]["overlay_cuda"] is True
    assert payload["cuda_base_image"] == "nvidia/cuda:test"
    assert payload["nv_codec_headers"] == "n12.2.72.0"
    assert payload["python_base_image"] == "python:test@sha256:" + "b" * 64
    assert payload["voicevox"]["cpu"] == "voicevox:cpu@test"
    assert payload["required_font_path"] == "/fonts/ipag.ttf"


def test_write_build_info_writes_utf8_json(tmp_path: Path) -> None:
    output = tmp_path / "metadata" / "build-info.json"
    write_build_info(output, {"profile": "cpu", "label": "ずんだもん"})

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "profile": "cpu",
        "label": "ずんだもん",
    }
