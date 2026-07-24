import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "site"))

import render_demos


def _feature(identifier: str, *, audio_required: bool = True) -> dict:
    return {
        "id": identifier,
        "demo": {
            "script": f"site/demos/{identifier}.yaml",
            "output": f"{identifier}.mp4",
            "poster": f"{identifier}.webp",
            "audio_required": audio_required,
        },
    }


def _write_cached_media(work: Path, feature: dict, input_hash: str) -> None:
    demo = feature["demo"]
    video = work / "videos" / demo["output"]
    poster = work / "posters" / demo["poster"]
    metadata = work / "metadata" / f"{feature['id']}.input.json"
    for path in (video, poster, metadata):
        path.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    poster.write_bytes(b"poster")
    metadata.write_text(
        json.dumps({"input_hash": input_hash}),
        encoding="utf-8",
    )


def test_cache_hit_requires_matching_nonempty_media(tmp_path: Path) -> None:
    feature = _feature("cached")
    _write_cached_media(tmp_path, feature, "sha256:expected")

    assert render_demos.cache_hit(feature, tmp_path, "sha256:expected")
    assert not render_demos.cache_hit(feature, tmp_path, "sha256:changed")

    (tmp_path / "videos/cached.mp4").write_bytes(b"")
    assert not render_demos.cache_hit(feature, tmp_path, "sha256:expected")


def test_cache_status_only_requests_voicevox_for_pending_voice_media(
    tmp_path: Path, monkeypatch
) -> None:
    cached_voice = _feature("cached-voice")
    pending_silent = _feature("pending-silent", audio_required=False)
    pending_voice = _feature("pending-voice")
    monkeypatch.setattr(
        render_demos,
        "feature_input_hash",
        lambda feature: f"sha256:{feature['id']}",
    )
    _write_cached_media(tmp_path, cached_voice, "sha256:cached-voice")

    silent_status = render_demos.cache_status(
        [cached_voice, pending_silent],
        tmp_path,
    )
    assert silent_status == {"complete": False, "voice_required": False}

    voice_status = render_demos.cache_status(
        [cached_voice, pending_voice],
        tmp_path,
    )
    assert voice_status == {"complete": False, "voice_required": True}


def test_render_skips_subprocesses_on_cache_hit(tmp_path: Path, monkeypatch) -> None:
    feature = _feature("cached")
    monkeypatch.setattr(
        render_demos,
        "feature_input_hash",
        lambda _feature: "sha256:expected",
    )
    _write_cached_media(tmp_path, feature, "sha256:expected")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("subprocess must not run for a media cache hit")

    monkeypatch.setattr(render_demos.subprocess, "run", fail_if_called)

    render_demos.render(feature, tmp_path, no_voice=False)
