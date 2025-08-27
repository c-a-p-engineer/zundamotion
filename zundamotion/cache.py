import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional  # Awaitableを追加

from .exceptions import CacheError
from .utils.logger import logger


class CacheManager:
    def __init__(
        self,
        cache_dir: Path,
        no_cache: bool = False,
        cache_refresh: bool = False,
        max_size_mb: Optional[int] = None,  # キャッシュの最大サイズ (MB)
        ttl_hours: Optional[int] = None,  # キャッシュの有効期限 (時間)
    ):
        self.cache_dir = cache_dir
        self.no_cache = no_cache
        self.cache_refresh = cache_refresh
        self.max_size_mb = max_size_mb
        self.ttl_hours = ttl_hours

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

            self._clean_cache()  # キャッシュ初期化時にクリーンアップを実行

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

    def _clean_cache(self):
        """
        キャッシュディレクトリをクリーンアップし、最大サイズと有効期限に基づいてファイルを削除します。
        """
        if not self.cache_dir.exists():
            return

        files = []
        for f in self.cache_dir.iterdir():
            if f.is_file():
                stat = f.stat()
                files.append(
                    (f, stat.st_size, stat.st_atime)
                )  # パス, サイズ, 最終アクセス時刻

        # 有効期限切れのファイルを削除
        if self.ttl_hours is not None:
            current_time = time.time()
            expired_threshold = current_time - (self.ttl_hours * 3600)  # 秒

            initial_count = len(files)
            files = [
                f for f in files if f[2] > expired_threshold
            ]  # 最終アクセス時刻が閾値より新しいものだけ残す

            deleted_count = initial_count - len(files)
            if deleted_count > 0:
                logger.info(
                    f"Deleted {deleted_count} expired cache files (TTL: {self.ttl_hours} hours)."
                )

        # サイズ超過のファイルを削除 (最も古いものから)
        if self.max_size_mb is not None:
            max_bytes = self.max_size_mb * 1024 * 1024
            current_size = sum(f[1] for f in files)  # 現在の合計サイズ

            if current_size > max_bytes:
                # 最も古いファイル (最終アクセス時刻が最も古いもの) から削除
                files.sort(key=lambda x: x[2])  # 最終アクセス時刻でソート

                deleted_size = 0
                deleted_count = 0
                for f, size, _ in files:
                    if current_size <= max_bytes:
                        break
                    try:
                        f.unlink()
                        current_size -= size
                        deleted_size += size
                        deleted_count += 1
                    except OSError as e:
                        logger.warning(f"Failed to delete cache file {f.name}: {e}")

                if deleted_count > 0:
                    logger.info(
                        f"Deleted {deleted_count} cache files ({deleted_size / (1024*1024):.2f} MB) "
                        f"to stay within max size limit ({self.max_size_mb} MB)."
                    )

        if self.max_size_mb is None and self.ttl_hours is None:
            logger.debug(
                "Cache cleanup skipped: max_size_mb and ttl_hours are not set."
            )

    def get_cached_path(
        self, key_data: Dict[str, Any], file_name: str, extension: str
    ) -> Optional[Path]:
        if self.no_cache:
            return None
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        if cached_path.exists():
            logger.info(
                f"Cache HIT for {file_name}.{extension} (key: {cache_key[:8]}) -> {cached_path.name}"
            )
            return cached_path
        logger.info(f"Cache MISS for {file_name}.{extension} (key: {cache_key[:8]})")
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
        self._clean_cache()  # ファイル追加後にクリーンアップを実行
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

    async def get_or_create(
        self,
        key_data: Dict[str, Any],
        file_name: str,
        extension: str,
        creator_func: Callable[
            [Path], Awaitable[Path]
        ],  # creator_func は出力パスを受け取り、生成されたファイルのパスを返す (非同期対応のためAwaitable[Path])
    ) -> Path:
        cache_key = self._generate_hash(key_data)
        cached_path = self.cache_dir / f"{file_name}_{cache_key}.{extension}"
        logger.debug(
            f"Attempting to get_or_create for key: {cache_key[:8]}, expected path: {cached_path.name}"
        )

        if self.no_cache:
            # キャッシュ無効時は一時ファイルとして生成し、キャッシュディレクトリには保存しない
            temp_output_path = (
                self.cache_dir / f"temp_{file_name}_{cache_key}.{extension}"
            )
            logger.info(
                f"Cache disabled. Generating temporary file: {temp_output_path.name}"
            )
            return await creator_func(temp_output_path)

        if self.cache_refresh and cached_path.exists():
            logger.info(
                f"Cache refresh requested. Removing existing cache: {cached_path.name}"
            )
            cached_path.unlink()  # 既存のキャッシュを削除

        if cached_path.exists():
            logger.info(
                f"Cache HIT for {file_name}.{extension} (key: {cache_key[:8]}) -> {cached_path.name}"
            )
            return cached_path

        logger.info(
            f"Cache MISS. Calling creator_func to generate file for {file_name}.{extension} (key: {cache_key[:8]}) to cache: {cached_path.name}"
        )
        try:
            # creator_func にキャッシュパスを直接渡し、そこにファイルを生成させる
            generated_path = await creator_func(cached_path)
            if generated_path != cached_path:
                # creator_func が別のパスに生成した場合、キャッシュパスにコピー
                shutil.copy(generated_path, cached_path)
                generated_path.unlink()  # 元の一時ファイルを削除
            logger.debug(f"Generated and cached file -> {cached_path.name}")
            self._clean_cache()  # ファイル生成後にクリーンアップを実行
            return cached_path
        except Exception as e:
            raise CacheError(
                f"Failed to generate or cache file {file_name}.{extension}: {e}"
            )
