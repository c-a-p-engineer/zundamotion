import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .exceptions import CacheError
from .utils.logger import logger


class CacheManager:
    def __init__(
        self,
        cache_dir: Path,
        no_cache: bool = False,
        cache_refresh: bool = False,
    ):
        self.cache_dir = cache_dir
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh

        try:
            self.cache_dir.mkdir(exist_ok=True)
            logger.info(f"Cache directory initialized: {self.cache_dir.resolve()}")
            if self.no_cache:
                logger.info(
                    "Cache is disabled (--no-cache). All files will be regenerated."
                )
                if self.cache_dir.exists():
                    shutil.rmtree(self.cache_dir)
                    self.cache_dir.mkdir(exist_ok=True)
            elif self.cache_refresh:
                logger.info(
                    "Cache refresh requested (--cache-refresh). All files will be regenerated and cache updated."
                )
                if self.cache_dir.exists():
                    shutil.rmtree(self.cache_dir)
                    self.cache_dir.mkdir(exist_ok=True)
            else:
                logger.info(
                    "Using existing cache. Use --no-cache to disable or --cache-refresh to force regeneration."
                )
        except Exception as e:
            raise CacheError(f"Failed to initialize cache directory: {e}")

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        """Generates a SHA256 hash from a dictionary, handling Path objects."""

        class PathEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, Path):
                    return str(obj)
                return json.JSONEncoder.default(self, obj)

        sorted_data = json.dumps(data, sort_keys=True, cls=PathEncoder).encode("utf-8")
        return hashlib.sha256(sorted_data).hexdigest()

    def get_cached_path(
        self, key_data: Dict[str, Any], file_name: str, extension: str
    ) -> Optional[Path]:
        if self.no_cache:
            return None
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        if cached_path.exists():
            logger.debug(f"Using cached file -> {cached_path.name}")
            return cached_path
        return None

    def cache_file(
        self,
        source_path: Path,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
    ) -> Path:
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        shutil.copy(source_path, cached_path)
        logger.debug(f"Cached file -> {cached_path.name}")
        return cached_path

    def save_to_cache(
        self,
        source_path: Path,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
    ) -> Path:
        """Saves a file to the cache."""
        return self.cache_file(source_path, key_data, file_name, extension)

    def get_cache_path(
        self, key_data: Dict[str, Any], file_name: str, extension: str
    ) -> Path:
        """Returns the expected path of a cached file, without checking existence."""
        cache_key = self._generate_hash(key_data)
        return self.cache_dir / f"{file_name}_{cache_key}.{extension}"

    def get_or_create(
        self,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
        creator_func: Callable[
            [Path], Path
        ],  # creator_func は出力パスを受け取り、生成されたファイルのパスを返す
    ) -> Path:
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        logger.debug(
            f"Attempting to get_or_create for key: {cache_key}, expected path: {cached_path.name}"
        )

        if self.no_cache:
            # キャッシュ無効時は一時ファイルとして生成し、キャッシュディレクトリには保存しない
            temp_output_path = (
                self.cache_dir / f"temp_{file_name}_{cache_key}.{extension}"
            )
            logger.debug(
                f"Cache disabled. Generating temporary file: {temp_output_path.name}"
            )
            return creator_func(temp_output_path)

        if self.cache_refresh and cached_path.exists():
            logger.debug(
                f"Cache refresh requested. Removing existing cache: {cached_path.name}"
            )
            cached_path.unlink()  # 既存のキャッシュを削除

        if cached_path.exists():
            logger.debug(f"Using cached file -> {cached_path.name}")
            return cached_path

        logger.debug(
            f"Cache miss. Calling creator_func to generate file to cache: {cached_path.name}"
        )
        try:
            # creator_func にキャッシュパスを直接渡し、そこにファイルを生成させる
            generated_path = creator_func(cached_path)
            if generated_path != cached_path:
                # creator_func が別のパスに生成した場合、キャッシュパスにコピー
                shutil.copy(generated_path, cached_path)
                generated_path.unlink()  # 元の一時ファイルを削除
            logger.debug(f"Generated and cached file -> {cached_path.name}")
            return cached_path
        except Exception as e:
            raise CacheError(
                f"Failed to generate or cache file {file_name}.{extension}: {e}"
            )
