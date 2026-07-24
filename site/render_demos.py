"""Render feature demos, reusing only videos whose content signature matches."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from site_lib import ROOT, feature_input_hash, load_manifest, write_json


def cache_hit(feature: dict, work: Path, input_hash: str | None = None) -> bool:
    demo = feature["demo"]
    video = work / "videos" / demo["output"]
    poster = work / "posters" / demo["poster"]
    metadata = work / "metadata" / f"{feature['id']}.input.json"
    if not all(path.is_file() and path.stat().st_size > 0 for path in (video, poster)):
        return False
    try:
        recorded = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return recorded.get("input_hash") == (input_hash or feature_input_hash(feature))


def cache_status(
    features: list[dict], work: Path, skip_voice: bool = False
) -> dict[str, bool]:
    pending = []
    for feature in features:
        demo = feature.get("demo")
        if not demo or (skip_voice and demo["audio_required"]):
            continue
        input_hash = feature_input_hash(feature)
        if not cache_hit(feature, work, input_hash):
            pending.append(feature)
    return {
        "complete": not pending,
        "voice_required": any(
            feature["demo"]["audio_required"] for feature in pending
        ),
    }


def render(feature: dict, work: Path, no_voice: bool) -> None:
    demo = feature["demo"]
    if no_voice and demo["audio_required"]:
        return
    input_hash = feature_input_hash(feature)
    if cache_hit(feature, work, input_hash):
        print(f"media cache hit: {feature['id']}")
        return

    videos, logs, resolved = (work / "videos", work / "logs", work / "resolved")
    for directory in (videos, logs, resolved):
        directory.mkdir(parents=True, exist_ok=True)
    output = videos / demo["output"]
    command = [
        sys.executable,
        "-m",
        "zundamotion.main",
        str(ROOT / demo["script"]),
        "--project-root",
        str(ROOT),
        "-o",
        str(output.resolve()),
        "--hw-encoder",
        "cpu",
        "--quality",
        "speed",
        "--no-cache",
        "--dump-resolved",
        str((resolved / f"{feature['id']}.yaml").resolve()),
    ]
    if not demo["audio_required"]:
        command.append("--no-voice")
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    (logs / f"{feature['id']}.stdout.log").write_text(
        result.stdout, encoding="utf-8"
    )
    (logs / f"{feature['id']}.stderr.log").write_text(
        result.stderr, encoding="utf-8"
    )
    if result.returncode:
        raise RuntimeError(f"render failed: {feature['id']}; see {logs}")
    poster = work / "posters" / demo["poster"]
    poster.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(demo.get("poster_time_seconds", 1)),
            "-i",
            str(output),
            "-frames:v",
            "1",
            str(poster),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    write_json(
        work / "metadata" / f"{feature['id']}.input.json",
        {"input_hash": input_hash},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("site-work"))
    parser.add_argument(
        "--skip-voice",
        action="store_true",
        help="skip the required VOICEVOX demo only for local development",
    )
    parser.add_argument(
        "--from-feature",
        help="render this manifest feature and every following feature",
    )
    parser.add_argument(
        "--cache-status",
        action="store_true",
        help="print GitHub Actions output lines describing the restored media cache",
    )
    args = parser.parse_args()
    failures: list[str] = []
    features = load_manifest()["features"]
    if args.from_feature:
        start = next(
            (
                index
                for index, feature in enumerate(features)
                if feature["id"] == args.from_feature
            ),
            None,
        )
        if start is None:
            parser.error(f"unknown feature id: {args.from_feature}")
        features = features[start:]

    if args.cache_status:
        status = cache_status(features, args.output, args.skip_voice)
        print(f"complete={str(status['complete']).lower()}")
        print(f"voice_required={str(status['voice_required']).lower()}")
        return 0

    for feature in features:
        if feature.get("demo"):
            try:
                render(feature, args.output, args.skip_voice)
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
    if failures:
        raise RuntimeError("Demo render failures:\n" + "\n".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
