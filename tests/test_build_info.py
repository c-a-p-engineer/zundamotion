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
        ffmpeg_commit="a" * 40,
        nv_codec_headers="n12.2.72.0",
        cuda_base_image="nvidia/cuda:test",
        command_runner=lambda command: responses[tuple(command)],
    )

    assert payload["ffmpeg"]["version"] == "ffmpeg version N-12345"
    assert payload["ffmpeg"]["encoders"] == {
        "libx264": True,
        "libx265": False,
        "h264_nvenc": True,
        "hevc_nvenc": False,
    }
    assert payload["ffmpeg"]["filters"]["libfreetype"] is True
    assert payload["ffmpeg"]["filters"]["overlay_cuda"] is True
    assert payload["ffmpeg"]["filters"]["scale_opencl"] is True
    assert payload["cuda"] == {
        "base_image": "nvidia/cuda:test",
        "nv_codec_headers": "n12.2.72.0",
    }


def test_write_build_info_writes_utf8_json(tmp_path: Path) -> None:
    output = tmp_path / "metadata" / "build-info.json"
    write_build_info(output, {"profile": "cpu", "label": "ずんだもん"})

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "profile": "cpu",
        "label": "ずんだもん",
    }
