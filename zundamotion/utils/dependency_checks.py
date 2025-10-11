"""環境依存ツールの健全性チェックを提供するユーティリティ。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from ..exceptions import DependencyError
from .ffmpeg_capabilities import get_ffmpeg_version
from .ffmpeg_runner import run_ffmpeg_async
from .logger import KVLogger

_VERSION_PATTERN = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass(frozen=True)
class VersionRequirement:
    """バージョン互換性チェックに利用する正規化済みバージョン情報。"""

    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, version_str: str) -> "VersionRequirement":
        """任意形式のバージョン文字列から数値のみを抽出して正規化する。"""

        match = _VERSION_PATTERN.search(version_str)
        if not match:
            raise ValueError(f"Unsupported version string: '{version_str}'")
        major = int(match.group(1))
        minor = int(match.group(2) or 0)
        patch = int(match.group(3) or 0)
        return cls(major=major, minor=minor, patch=patch)

    def satisfies(self, minimum: "VersionRequirement") -> bool:
        """自身が要求バージョン以上であるかを判定する。"""

        return (self.major, self.minor, self.patch) >= (
            minimum.major,
            minimum.minor,
            minimum.patch,
        )


async def _get_ffprobe_version(ffprobe_path: str = "ffprobe") -> Optional[str]:
    """ffprobe のバージョン文字列を取得する。失敗時は None を返す。"""

    try:
        result = await run_ffmpeg_async([ffprobe_path, "-version"], error_log_level=logging.DEBUG)
        match = _VERSION_PATTERN.search(result.stdout)
        return match.group(0) if match else None
    except FileNotFoundError:
        return None
    except Exception:
        logging.getLogger("zundamotion").debug("Failed to read ffprobe version.", exc_info=True)
        return None


async def ensure_ffmpeg_dependencies(
    logger: KVLogger,
    *,
    min_ffmpeg_version: str = "7.0",
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
) -> Tuple[str, str]:
    """FFmpeg/ffprobe の実行可否と最低バージョンを検証する。"""

    minimum_version = VersionRequirement.parse(min_ffmpeg_version)

    ffmpeg_version_raw = await get_ffmpeg_version(ffmpeg_path)
    if not ffmpeg_version_raw:
        kv = {
            "Event": "DependencyCheck",
            "Tool": "ffmpeg",
            "Status": "NotDetected",
            "MinimumVersion": min_ffmpeg_version,
        }
        logger.kv_error(
            "ffmpeg が見つからないかバージョン検出に失敗しました。7.x 以降へアップグレードしてください。",
            kv_pairs=kv,
        )
        raise DependencyError("FFmpeg is missing or its version could not be determined.")

    try:
        ffmpeg_version = VersionRequirement.parse(ffmpeg_version_raw)
    except ValueError:
        kv = {
            "Event": "DependencyCheck",
            "Tool": "ffmpeg",
            "Status": "UnparsableVersion",
            "ReportedVersion": ffmpeg_version_raw,
            "MinimumVersion": min_ffmpeg_version,
        }
        logger.kv_error(
            "ffmpeg のバージョン文字列を解析できませんでした。最新の公式ビルドへ更新してください。",
            kv_pairs=kv,
        )
        raise DependencyError("Unable to parse FFmpeg version string.")

    if not ffmpeg_version.satisfies(minimum_version):
        kv = {
            "Event": "DependencyCheck",
            "Tool": "ffmpeg",
            "Status": "VersionTooOld",
            "ReportedVersion": ffmpeg_version_raw,
            "MinimumVersion": min_ffmpeg_version,
        }
        logger.kv_error(
            "ffmpeg のバージョンが古いため実行を中止します。7.x 以降へアップグレードしてください。",
            kv_pairs=kv,
        )
        raise DependencyError(
            f"FFmpeg {min_ffmpeg_version}+ is required, but {ffmpeg_version_raw} is installed."
        )

    ffprobe_version_raw = await _get_ffprobe_version(ffprobe_path)
    if not ffprobe_version_raw:
        kv = {
            "Event": "DependencyCheck",
            "Tool": "ffprobe",
            "Status": "NotDetected",
            "MinimumVersion": min_ffmpeg_version,
        }
        logger.kv_error(
            "ffprobe が見つからないかバージョン検出に失敗しました。FFmpeg 7.x 以降の同梱バイナリを導入してください。",
            kv_pairs=kv,
        )
        raise DependencyError("ffprobe is missing or its version could not be determined.")

    try:
        ffprobe_version = VersionRequirement.parse(ffprobe_version_raw)
    except ValueError:
        kv = {
            "Event": "DependencyCheck",
            "Tool": "ffprobe",
            "Status": "UnparsableVersion",
            "ReportedVersion": ffprobe_version_raw,
            "MinimumVersion": min_ffmpeg_version,
        }
        logger.kv_error(
            "ffprobe のバージョン文字列を解析できませんでした。最新の公式ビルドへ更新してください。",
            kv_pairs=kv,
        )
        raise DependencyError("Unable to parse ffprobe version string.")

    if not ffprobe_version.satisfies(minimum_version):
        kv = {
            "Event": "DependencyCheck",
            "Tool": "ffprobe",
            "Status": "VersionTooOld",
            "ReportedVersion": ffprobe_version_raw,
            "MinimumVersion": min_ffmpeg_version,
        }
        logger.kv_error(
            "ffprobe のバージョンが古いため実行を中止します。FFmpeg 7.x 以降をインストールしてください。",
            kv_pairs=kv,
        )
        raise DependencyError(
            f"ffprobe {min_ffmpeg_version}+ is required, but {ffprobe_version_raw} is installed."
        )

    kv_success = {
        "Event": "DependencyCheck",
        "Tool": "ffmpeg+ffprobe",
        "Status": "OK",
        "FFmpegVersion": ffmpeg_version_raw,
        "FFprobeVersion": ffprobe_version_raw,
        "MinimumVersion": min_ffmpeg_version,
    }
    logger.kv_info("FFmpeg/ffprobe の環境要件を満たしています。", kv_pairs=kv_success)

    return ffmpeg_version_raw, ffprobe_version_raw

