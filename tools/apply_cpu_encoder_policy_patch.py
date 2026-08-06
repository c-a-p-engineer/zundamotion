#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    ffmpeg_ops = ROOT / "zundamotion/utils/ffmpeg_ops.py"
    main_py = ROOT / "zundamotion/components/pipeline_phases/video_phase/main.py"

    replace_once(
        ffmpeg_ops,
        'DEFAULT_BACKGROUND_FILL_COLOR = "#000000"\n\n\nclass TimestampWarningError',
        '''DEFAULT_BACKGROUND_FILL_COLOR = "#000000"\n\n\ndef _resolve_hw_encoder_policy(\n    cache_manager: Any,\n    hw_encoder: Optional[str],\n) -> str:\n    """Resolve the caller's encoder request without probing hardware.\n\n    ``DISABLE_HWENC=1`` is authoritative. Otherwise an explicit request wins,\n    followed by the policy propagated to the shared CacheManager by VideoPhase.\n    """\n    if os.getenv("DISABLE_HWENC", "0") == "1":\n        return "cpu"\n    candidate = hw_encoder\n    if candidate is None:\n        candidate = getattr(cache_manager, "hw_encoder", "auto")\n    normalized = str(candidate or "auto").strip().lower()\n    return normalized if normalized in {"auto", "cpu", "gpu"} else "auto"\n\n\nclass TimestampWarningError''',
    )
    replace_once(
        ffmpeg_ops,
        '''    ffmpeg_path: str = "ffmpeg",\n    *,\n    fit_mode: str = BACKGROUND_FIT_STRETCH,''',
        '''    ffmpeg_path: str = "ffmpeg",\n    *,\n    hw_encoder: Optional[str] = None,\n    fit_mode: str = BACKGROUND_FIT_STRETCH,''',
    )
    replace_once(
        ffmpeg_ops,
        '''    キャッシュがHITすれば、変換処理をスキップしてキャッシュパスを返す。\n    """\n    pos_dict_raw = position or {}''',
        '''    キャッシュがHITすれば、変換処理をスキップしてキャッシュパスを返す。\n    """\n    hw_encoder_policy = _resolve_hw_encoder_policy(cache_manager, hw_encoder)\n    pos_dict_raw = position or {}''',
    )
    old_call = '''                    hw_kind_local = await get_hw_encoder_kind_for_video_params(\n                        ffmpeg_path\n                    )'''
    new_call = '''                    hw_kind_local = await get_hw_encoder_kind_for_video_params(\n                        ffmpeg_path,\n                        hw_encoder=hw_encoder_policy,\n                    )'''
    text = ffmpeg_ops.read_text(encoding="utf-8")
    count = text.count(old_call)
    if count != 2:
        raise RuntimeError(f"Expected two normalize encoder calls, found {count}")
    ffmpeg_ops.write_text(text.replace(old_call, new_call), encoding="utf-8")

    replace_once(
        main_py,
        '''    ):\n        hw_kind = await get_hw_encoder_kind_for_video_params(\n            hw_encoder=hw_encoder\n        )''',
        '''    ):\n        # Propagate the user's encoder contract to normalization paths that only\n        # receive the shared CacheManager. This prevents CPU-fixed renders from\n        # re-entering NVENC/QSV smoke tests while normalizing media.\n        setattr(cache_manager, "hw_encoder", str(hw_encoder or "auto").lower())\n        hw_kind = await get_hw_encoder_kind_for_video_params(\n            hw_encoder=hw_encoder\n        )''',
    )

    test_path = ROOT / "tests/test_cpu_encoder_policy.py"
    test_path.write_text(
        '''from __future__ import annotations\n\nimport asyncio\nfrom types import SimpleNamespace\n\nfrom zundamotion.components.pipeline_phases.video_phase import main as video_phase_main\nfrom zundamotion.utils import ffmpeg_ops\nfrom zundamotion.utils.ffmpeg_params import AudioParams, VideoParams\n\n\ndef test_resolve_hw_encoder_policy_prefers_explicit_request(monkeypatch) -> None:\n    monkeypatch.delenv("DISABLE_HWENC", raising=False)\n    manager = SimpleNamespace(hw_encoder="gpu")\n\n    assert ffmpeg_ops._resolve_hw_encoder_policy(manager, "cpu") == "cpu"\n    assert ffmpeg_ops._resolve_hw_encoder_policy(manager, None) == "gpu"\n\n\ndef test_disable_hwenc_is_authoritative(monkeypatch) -> None:\n    monkeypatch.setenv("DISABLE_HWENC", "1")\n    manager = SimpleNamespace(hw_encoder="gpu")\n\n    assert ffmpeg_ops._resolve_hw_encoder_policy(manager, "gpu") == "cpu"\n\n\ndef test_video_phase_create_propagates_encoder_policy(monkeypatch, tmp_path) -> None:\n    async def fake_get_hw_encoder_kind_for_video_params(*args, **kwargs):\n        return None\n\n    async def fake_renderer_create(*args, **kwargs):\n        return SimpleNamespace(clip_workers=1)\n\n    monkeypatch.setattr(\n        video_phase_main,\n        "get_hw_encoder_kind_for_video_params",\n        fake_get_hw_encoder_kind_for_video_params,\n    )\n    monkeypatch.setattr(\n        video_phase_main.VideoRenderer,\n        "create",\n        fake_renderer_create,\n    )\n\n    cache_manager = SimpleNamespace(cache_dir=tmp_path)\n    phase = asyncio.run(\n        video_phase_main.VideoPhase.create(\n            {},\n            tmp_path,\n            cache_manager,\n            "1",\n            hw_encoder="cpu",\n            video_params=VideoParams(),\n            audio_params=AudioParams(),\n        )\n    )\n\n    assert cache_manager.hw_encoder == "cpu"\n    assert phase.hw_kind is None\n''',
        encoding="utf-8",
    )

    (ROOT / "tools/apply_cpu_encoder_policy_patch.py").unlink()
    (ROOT / ".github/workflows/apply-cpu-encoder-policy.yml").unlink()


if __name__ == "__main__":
    main()
