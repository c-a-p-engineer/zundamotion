"""Deterministic project-level render lock and provenance helpers."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import __version__
from .authoring import compiled_document

RENDER_LOCK_FORMAT = "zundamotion.render-lock"
RENDER_LOCK_FORMAT_VERSION = 1
LOCK_VERIFICATION_FORMAT = "zundamotion.lock-verification"
LOCK_VERIFICATION_FORMAT_VERSION = 1


def create_render_lock(script_path: str, *, project_root: Path | None = None) -> dict[str, Any]:
    """Create deterministic provenance for one resolved/validated script."""

    root = (project_root or Path.cwd()).resolve()
    script = Path(script_path).expanduser()
    script_file = script if script.is_absolute() else root / script
    script_file = script_file.resolve()

    # The script loader intentionally resolves relative asset/include paths from
    # the working directory.  Mirror CLI --project-root semantics for callers of
    # this library helper and restore the caller's cwd immediately afterwards.
    with _working_directory(root):
        compiled = compiled_document(str(script_file))
    compiled_bytes = _canonical_json_bytes(compiled)
    assets = _collect_existing_files(compiled["config"], root=root)

    runtime_lock = _runtime_lock_entry(root)
    return {
        "format": RENDER_LOCK_FORMAT,
        "format_version": RENDER_LOCK_FORMAT_VERSION,
        "zundamotion_version": __version__,
        "source": {
            "script": _path_label(script_file, root),
            "sha256": _sha256_file(script_file),
        },
        "compiled_config_sha256": hashlib.sha256(compiled_bytes).hexdigest(),
        "assets": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(assets.items())
        ],
        "runtime_lock": runtime_lock,
    }


def verify_render_lock(
    script_path: str,
    lock_document: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Recompute provenance and report stable, localized differences."""

    actual = create_render_lock(script_path, project_root=project_root)
    differences: list[dict[str, Any]] = []

    if lock_document.get("format") != RENDER_LOCK_FORMAT:
        differences.append(
            {
                "code": "ZDM-L1000",
                "subject": "format",
                "expected": RENDER_LOCK_FORMAT,
                "actual": lock_document.get("format"),
            }
        )
    if lock_document.get("format_version") != RENDER_LOCK_FORMAT_VERSION:
        differences.append(
            {
                "code": "ZDM-L1001",
                "subject": "format_version",
                "expected": RENDER_LOCK_FORMAT_VERSION,
                "actual": lock_document.get("format_version"),
            }
        )

    _compare_scalar(
        differences,
        "ZDM-L1100",
        "zundamotion_version",
        lock_document.get("zundamotion_version"),
        actual["zundamotion_version"],
    )
    _compare_scalar(
        differences,
        "ZDM-L1101",
        "source.sha256",
        (lock_document.get("source") or {}).get("sha256"),
        actual["source"]["sha256"],
    )
    _compare_scalar(
        differences,
        "ZDM-L1102",
        "compiled_config_sha256",
        lock_document.get("compiled_config_sha256"),
        actual["compiled_config_sha256"],
    )
    _compare_scalar(
        differences,
        "ZDM-L1103",
        "runtime_lock",
        lock_document.get("runtime_lock"),
        actual["runtime_lock"],
    )

    expected_assets = _asset_map(lock_document.get("assets"))
    actual_assets = _asset_map(actual["assets"])
    for path in sorted(set(expected_assets) | set(actual_assets)):
        expected_hash = expected_assets.get(path)
        actual_hash = actual_assets.get(path)
        if expected_hash == actual_hash:
            continue
        code = "ZDM-L1200"
        if expected_hash is None:
            code = "ZDM-L1201"
        elif actual_hash is None:
            code = "ZDM-L1202"
        differences.append(
            {
                "code": code,
                "subject": f"assets:{path}",
                "expected": expected_hash,
                "actual": actual_hash,
            }
        )

    return {
        "format": LOCK_VERIFICATION_FORMAT,
        "format_version": LOCK_VERIFICATION_FORMAT_VERSION,
        "valid": not differences,
        "differences": differences,
    }


def load_render_lock(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Render lock root must be a JSON object.")
    return data


def render_lock_json(document: dict[str, Any], *, pretty: bool = True) -> str:
    if pretty:
        return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _collect_existing_files(value: Any, *, root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for text in _iter_strings(value):
        if not text or text.startswith(("http://", "https://")):
            continue
        try:
            raw = Path(text).expanduser()
            candidate = raw if raw.is_absolute() else root / raw
            candidate = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        label = _path_label(candidate, root)
        found[label] = _sha256_file(candidate)
    return found


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def _runtime_lock_entry(project_root: Path) -> dict[str, str] | None:
    candidates = [
        project_root / ".devcontainer" / "runtime.lock.json",
        Path(__file__).resolve().parent.parent / ".devcontainer" / "runtime.lock.json",
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return {
                "path": _path_label(resolved, project_root),
                "sha256": _sha256_file(resolved),
            }
    return None


def _asset_map(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            result[path] = digest
    return result


def _compare_scalar(
    differences: list[dict[str, Any]],
    code: str,
    subject: str,
    expected: Any,
    actual: Any,
) -> None:
    if expected != actual:
        differences.append(
            {"code": code, "subject": subject, "expected": expected, "actual": actual}
        )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
