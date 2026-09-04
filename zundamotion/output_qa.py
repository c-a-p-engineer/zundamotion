"""Post-render media inspection and visual-review artifacts."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
from typing import Any

from PIL import Image, ImageDraw

from . import __version__
from .utils.export_presets import EXPORT_PRESETS
from .utils.ffmpeg_probe import get_media_info
from .utils.ffmpeg_runner import run_ffmpeg_async

OUTPUT_INSPECTION_FORMAT = "zundamotion.output-inspection"
OUTPUT_INSPECTION_FORMAT_VERSION = 1


def expected_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract observable final-media expectations from canonical config."""

    video = config.get("video") or {}
    expected: dict[str, Any] = {}
    mapping = {
        "width": "width",
        "height": "height",
        "fps": "fps",
        "audio_codec": "audio_codec",
        "audio_sample_rate": "audio_sample_rate",
        "audio_channels": "audio_channels",
    }
    for source, target in mapping.items():
        value = video.get(source)
        if value is not None:
            expected[target] = value
    if config.get("export_preset"):
        expected["export_preset"] = str(config["export_preset"])
    return expected


def expected_from_preset(name: str) -> dict[str, Any]:
    """Return observable expectations declared by one export preset."""

    key = str(name).strip().lower()
    preset = EXPORT_PRESETS.get(key)
    if preset is None:
        raise ValueError(
            f"Unknown export preset '{name}'. Available: {', '.join(sorted(EXPORT_PRESETS))}."
        )
    video = preset["video"]
    audio = preset["audio"]
    return {
        "export_preset": key,
        "width": video["width"],
        "height": video["height"],
        "fps": video["fps"],
        "audio_sample_rate": audio["audio_sample_rate"],
        "audio_channels": audio["audio_channels"],
    }


def representative_timestamps(duration: float, count: int = 5) -> list[float]:
    """Choose review timestamps away from exact file boundaries."""

    if duration <= 0:
        raise ValueError("duration must be positive")
    if not 1 <= count <= 12:
        raise ValueError("sample count must be between 1 and 12")
    if count == 1:
        return [duration / 2.0]
    start = 0.05
    end = 0.95
    step = (end - start) / float(count - 1)
    return [min(duration, max(0.0, duration * (start + step * i))) for i in range(count)]


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    *,
    passed: bool,
    actual: Any,
    expected: Any = None,
) -> None:
    item: dict[str, Any] = {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "actual": actual,
    }
    if expected is not None:
        item["expected"] = expected
    checks.append(item)


def _matches_number(actual: Any, expected: Any, *, tolerance: float = 0.01) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


async def inspect_output(
    file_path: str | Path,
    *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Probe a rendered media file and compare observable output properties."""

    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"output media does not exist: {path}")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise ValueError(f"output media is empty: {path}")

    media = await get_media_info(str(path), caller="output_qa.inspect_output")
    video = media.get("video")
    audio = media.get("audio")
    duration = media.get("duration")
    checks: list[dict[str, Any]] = []

    _check(checks, "file_nonempty", passed=size_bytes > 0, actual=size_bytes)
    _check(checks, "video_stream", passed=video is not None, actual=video is not None, expected=True)
    _check(checks, "audio_stream", passed=audio is not None, actual=audio is not None, expected=True)
    _check(
        checks,
        "duration_positive",
        passed=duration is not None and float(duration) > 0.0,
        actual=duration,
        expected="> 0",
    )

    wanted = dict(expected or {})
    if video is not None:
        for key in ("width", "height"):
            if key in wanted:
                _check(
                    checks,
                    key,
                    passed=int(video.get(key) or 0) == int(wanted[key]),
                    actual=video.get(key),
                    expected=wanted[key],
                )
        if "fps" in wanted:
            _check(
                checks,
                "fps",
                passed=_matches_number(video.get("fps"), wanted["fps"]),
                actual=video.get("fps"),
                expected=wanted["fps"],
            )

    if audio is not None:
        if "audio_codec" in wanted:
            actual_codec = str(audio.get("codec_name") or "").lower()
            expected_codec = str(wanted["audio_codec"]).lower()
            _check(
                checks,
                "audio_codec",
                passed=actual_codec == expected_codec,
                actual=actual_codec,
                expected=expected_codec,
            )
        if "audio_sample_rate" in wanted:
            _check(
                checks,
                "audio_sample_rate",
                passed=int(audio.get("sample_rate") or 0) == int(wanted["audio_sample_rate"]),
                actual=audio.get("sample_rate"),
                expected=wanted["audio_sample_rate"],
            )
        if "audio_channels" in wanted:
            _check(
                checks,
                "audio_channels",
                passed=int(audio.get("channels") or 0) == int(wanted["audio_channels"]),
                actual=audio.get("channels"),
                expected=wanted["audio_channels"],
            )

    return {
        "format": OUTPUT_INSPECTION_FORMAT,
        "format_version": OUTPUT_INSPECTION_FORMAT_VERSION,
        "zundamotion_version": __version__,
        "path": str(path),
        "size_bytes": size_bytes,
        "media": media,
        "expected": wanted or None,
        "checks": checks,
        "machine_valid": all(item["status"] == "pass" for item in checks),
        "visual_review": {
            "status": "not_generated",
            "contact_sheet": None,
            "note": "Metadata checks do not replace visual review.",
        },
    }


async def create_contact_sheet(
    file_path: str | Path,
    output_path: str | Path,
    *,
    duration: float,
    samples: int = 5,
    frame_width: int = 480,
) -> dict[str, Any]:
    """Extract representative frames and compose one PNG for visual review."""

    source = Path(file_path)
    output = Path(output_path)
    if output.suffix.lower() != ".png":
        raise ValueError("contact sheet output must use a .png extension")
    if frame_width <= 0:
        raise ValueError("frame_width must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamps = representative_timestamps(float(duration), samples)

    with tempfile.TemporaryDirectory(
        prefix=f".{output.stem}_frames_", dir=str(output.parent)
    ) as temp_dir:
        frame_dir = Path(temp_dir)
        frames: list[Path] = []
        for index, timestamp in enumerate(timestamps):
            frame = frame_dir / f"frame_{index:02d}.png"
            await run_ffmpeg_async(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={int(frame_width)}:-2",
                    "-y",
                    str(frame),
                ],
                context={
                    "phase": "OutputQA",
                    "operation": "review_frame",
                    "path": str(source),
                    "timestamp": timestamp,
                },
            )
            if not frame.is_file() or frame.stat().st_size <= 0:
                raise ValueError(f"failed to extract review frame at {timestamp:.3f}s")
            frames.append(frame)

        images: list[Image.Image] = []
        sheet: Image.Image | None = None
        try:
            for frame in frames:
                with Image.open(frame) as source_image:
                    images.append(source_image.convert("RGB"))
            columns = min(3, len(images))
            rows = int(math.ceil(len(images) / columns))
            label_height = 28
            cell_width = max(image.width for image in images)
            cell_height = max(image.height for image in images) + label_height
            sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "black")
            draw = ImageDraw.Draw(sheet)
            for index, (image, timestamp) in enumerate(zip(images, timestamps)):
                column = index % columns
                row = index // columns
                x = column * cell_width + (cell_width - image.width) // 2
                y = row * cell_height
                sheet.paste(image, (x, y))
                draw.text(
                    (column * cell_width + 8, y + image.height + 6),
                    f"{timestamp:.2f}s",
                    fill="white",
                )
            sheet.save(output, format="PNG")
        finally:
            if sheet is not None:
                sheet.close()
            for image in images:
                image.close()

    return {
        "status": "pending_review",
        "contact_sheet": str(output),
        "timestamps": [round(value, 3) for value in timestamps],
        "note": "Inspect the contact sheet for crop, subtitle, overlay, colour, and transition problems.",
    }
