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
        creator_func: Callable[[], Optional[Path]],
    ) -> Optional[Path]:
        cached_path = self.get_cached_path(key_data, file_name, extension)
        if cached_path:
            return cached_path

        new_file_path = creator_func()
        if new_file_path:
            try:
                self.save_to_cache(
                    new_file_path, key_data, file_name, extension
                )  # Use new method
                return new_file_path
            except Exception as e:
                raise CacheError(f"Failed to cache file {file_name}.{extension}: {e}")
        else:
            raise CacheError(
                f"Creator function failed to generate file for {file_name}.{extension}"
            )
