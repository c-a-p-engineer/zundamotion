"""Inspect demo MP4s with ffprobe and enforce public media constraints."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from site_lib import load_manifest, run_json, write_json


def inspect(path: Path, demo: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing or empty video: {path}")
    data = run_json(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    streams = data["streams"]
    video = next((item for item in streams if item["codec_type"] == "video"), None)
    audio = next((item for item in streams if item["codec_type"] == "audio"), None)
    if not video or video.get("codec_name") != "h264":
        raise ValueError(f"{path}: H.264 video stream is required")
    if (video.get("width"), video.get("height")) != (demo["width"], demo["height"]):
        raise ValueError(f"{path}: unexpected dimensions")
    duration = float(data["format"].get("duration", 0))
    if not 0 < duration <= demo["max_duration_seconds"] or path.stat().st_size > demo["max_size_bytes"]:
        raise ValueError(f"{path}: duration or size limit exceeded")
    if demo["audio_required"] and (not audio or audio.get("codec_name") != "aac" or audio.get("sample_rate") != "48000" or audio.get("channels") != 2):
        raise ValueError(f"{path}: AAC 48kHz stereo audio is required")
    return {"path": path.name, "duration": duration, "size_bytes": path.stat().st_size, "streams": streams}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("site-work"))
    parser.add_argument("--site-dir", type=Path)
    args = parser.parse_args()
    root = args.site_dir / "assets/videos" if args.site_dir else args.work_dir / "videos"
    metadata = args.work_dir / "metadata"
    for feature in load_manifest()["features"]:
        demo = feature.get("demo")
        if demo:
            write_json(metadata / f"{feature['id']}.json", inspect(root / demo["output"], demo))
    print("site media inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
