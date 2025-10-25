from zundamotion.components.video.clip.face import _resolve_face_asset


def test_resolve_face_asset_prefers_expression(tmp_path):
    base_dir = tmp_path / "characters" / "hero"
    expr_dir = base_dir / "smile" / "mouth"
    expr_dir.mkdir(parents=True)
    default_dir = base_dir / "default" / "mouth"
    default_dir.mkdir(parents=True)

    smile_path = expr_dir / "open.png"
    smile_path.write_bytes(b"")
    default_path = default_dir / "open.png"
    default_path.write_bytes(b"")

    resolved = _resolve_face_asset(base_dir, "smile", "mouth", "open.png")
    assert resolved == smile_path


def test_resolve_face_asset_falls_back_to_default(tmp_path):
    base_dir = tmp_path / "characters" / "heroine"
    default_dir = base_dir / "default" / "mouth"
    default_dir.mkdir(parents=True)
    default_path = default_dir / "half.png"
    default_path.write_bytes(b"")

    resolved = _resolve_face_asset(base_dir, "wink", "mouth", "half.png")
    assert resolved == default_path
