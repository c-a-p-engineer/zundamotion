import asyncio
import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from zundamotion.utils.ffmpeg_utils import MediaInfo  # MediaInfo を追加

from .exceptions import CacheError
from .utils.ffmpeg_utils import (
    get_media_info,
    probe_media_params_async,
    run_ffmpeg_async,
)
from .utils.ffmpeg_utils import (
    AudioParams,
    VideoParams,
    normalize_media,
)
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
        # Ephemeral (temporary) directory to use when no_cache=True
        self.ephemeral_dir: Optional[Path] = None
        # In-process de-duplication for no-cache creation
        self._inflight_lock = asyncio.Lock()
        self._inflight_tasks: Dict[str, asyncio.Task] = {}

        try:
            self.cache_dir.mkdir(exist_ok=True)
            logger.info(f"Cache directory initialized: {self.cache_dir.resolve()}")
            # no_cache や cache_refresh のロジックは get_or_create_normalized_video 内で処理するため、ここではディレクトリ削除は行わない
            # if self.no_cache:
            #     logger.info(
            #         "Cache is disabled (--no-cache). All files will be regenerated."
            #     )
            #     if self.cache_dir.exists():
            #         shutil.rmtree(self.cache_dir)
            #         self.cache_dir.mkdir(exist_ok=True)
            # elif self.cache_refresh:
            #     logger.info(
            #         "Cache refresh requested (--cache-refresh). All files will be regenerated and cache updated."
            #     )
            #     if self.cache_dir.exists():
            #         shutil.rmtree(self.cache_dir)
            #         self.cache_dir.mkdir(exist_ok=True)
            # else:
            #     logger.info(
            #         "Using existing cache. Use --no-cache to disable or --cache-refresh to force regeneration."
            #     )

            self._clean_cache()  # キャッシュ初期化時にクリーンアップを実行

        except Exception as e:
            raise CacheError(f"Failed to initialize cache directory: {e}")

    def set_ephemeral_dir(self, temp_dir: Path) -> None:
        """Sets the directory for ephemeral outputs when cache is disabled."""
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Directory may already exist or be a TemporaryDirectory
            pass
        self.ephemeral_dir = temp_dir

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        """Generates a SHA256 hash from a dictionary, handling Path objects."""

        class PathEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, Path):
                    return str(obj)
                return json.JSONEncoder.default(self, obj)

        sorted_data = json.dumps(data, sort_keys=True, cls=PathEncoder).encode("utf-8")
        return hashlib.sha256(sorted_data).hexdigest()

    async def get_or_create_media_info(self, file_path: Path) -> MediaInfo:
        """
        メディアのメタ情報を取得し、キャッシュする。
        """
        key_data = {
            "file_path": str(file_path.resolve()),
            "file_size": file_path.stat().st_size,
            "file_mtime": file_path.stat().st_mtime,
            "operation": "media_info",
        }
        cache_key = self._generate_hash(key_data)
        cached_meta_path = self.cache_dir / f"info_{cache_key}.json"

        if self.no_cache:
            logger.debug(
                f"Cache disabled. Getting media info for {file_path.name} directly."
            )
            return await get_media_info(str(file_path))

        if self.cache_refresh and cached_meta_path.exists():
            logger.info(
                f"Cache refresh requested. Removing existing media info cache: {cached_meta_path.name}"
            )
            cached_meta_path.unlink()

        if cached_meta_path.exists():
            try:
                with open(cached_meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                info = meta["media_info"]
                logger.info(
                    f"Cache HIT for media info of {file_path.name} (key: {cache_key[:8]})"
                )
                return info
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    f"Corrupted media info cache for {file_path.name}: {e}. Regenerating."
                )
                cached_meta_path.unlink(missing_ok=True)

        logger.info(
            f"Cache MISS for media info of {file_path.name} (key: {cache_key[:8]}). Generating..."
        )
        try:
            info = await get_media_info(str(file_path))
            with open(cached_meta_path, "w", encoding="utf-8") as f:
                json.dump({"media_info": info, "created_at": time.time()}, f)
            logger.debug(f"Cached media info for {file_path.name}")
            self._clean_cache()
            return info
        except Exception as e:
            raise CacheError(
                f"Failed to get or cache media info for {file_path.name}: {e}"
            )

    async def get_or_create_media_duration(self, file_path: Path) -> float:
        """
        メディアファイルの長さを取得し、キャッシュする。
        """
        key_data = {
            "file_path": str(file_path.resolve()),
            "file_size": file_path.stat().st_size,
            "file_mtime": file_path.stat().st_mtime,
            "operation": "media_duration",
        }
        cache_key = self._generate_hash(key_data)
        cached_meta_path = self.cache_dir / f"duration_{cache_key}.json"

        if self.no_cache:
            logger.debug(
                f"Cache disabled. Getting duration for {file_path.name} directly."
            )
            # get_media_duration は ffmpeg_utils から削除されたため、直接 ffprobe を呼び出す
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(file_path),
            ]
            result = await run_ffmpeg_async(cmd)
            probe = json.loads(result.stdout)
            duration = float(probe["format"]["duration"])
            return round(duration, 2)

        if self.cache_refresh and cached_meta_path.exists():
            logger.info(
                f"Cache refresh requested. Removing existing duration cache: {cached_meta_path.name}"
            )
            cached_meta_path.unlink()

        if cached_meta_path.exists():
            try:
                with open(cached_meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                duration = meta["duration"]
                logger.info(
                    f"Cache HIT for duration of {file_path.name} (key: {cache_key[:8]}) -> {duration:.2f}s"
                )
                return duration
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    f"Corrupted duration cache for {file_path.name}: {e}. Regenerating."
                )
                cached_meta_path.unlink(missing_ok=True)

        logger.info(
            f"Cache MISS for duration of {file_path.name} (key: {cache_key[:8]}). Generating..."
        )
        try:
            # get_media_info はストリーム情報のみを返すため、duration は別途取得
            # ffmpeg_utils.py から get_media_duration を削除したため、ここで直接 ffprobe を呼び出す
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(file_path),
            ]
            result = await run_ffmpeg_async(cmd)  # _run_ffmpeg_async を直接呼び出す
            probe = json.loads(result.stdout)
            duration = float(probe["format"]["duration"])
            duration = round(duration, 2)

            with open(cached_meta_path, "w", encoding="utf-8") as f:
                json.dump({"duration": duration, "created_at": time.time()}, f)
            logger.debug(f"Cached duration for {file_path.name} -> {duration:.2f}s")
            self._clean_cache()
            return duration
        except Exception as e:
            raise CacheError(
                f"Failed to get or cache media duration for {file_path.name}: {e}"
            )

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
            # 最終アクセス時刻が閾値より新しいものだけ残す
            files = [f for f in files if f[2] > expired_threshold]

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
            # キャッシュ無効時は一時ファイルとして生成し、ephemeral_dir（temp_dir）に保存
            # 同一キーの多重実行を同プロセス内で抑止
            base_dir = self.ephemeral_dir or self.cache_dir
            temp_output_path = base_dir / f"temp_{file_name}_{cache_key}.{extension}"
            # 既に同一キーの一時生成物が存在する場合は再利用
            if temp_output_path.exists():
                logger.info(
                    f"Cache disabled: Reusing existing ephemeral output for key {cache_key[:8]} -> {temp_output_path.name}"
                )
                return temp_output_path
            # タスクの二重生成防止
            async with self._inflight_lock:
                existing = self._inflight_tasks.get(cache_key)
                if existing is None:
                    logger.info(
                        f"Cache disabled. Generating temporary file: (Ephemeral) {temp_output_path}"
                    )

                    async def _create() -> Path:
                        try:
                            generated_path = await creator_func(temp_output_path)
                            if generated_path != temp_output_path:
                                shutil.copy(generated_path, temp_output_path)
                                try:
                                    generated_path.unlink()
                                except Exception:
                                    pass
                            return temp_output_path
                        finally:
                            async with self._inflight_lock:
                                self._inflight_tasks.pop(cache_key, None)

                    task = asyncio.create_task(_create())
                    self._inflight_tasks[cache_key] = task
                else:
                    task = existing
            # ロック外で待機
            return await task

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

    def _hash_for_normalized(self, input_path: Path, target_spec: Dict) -> str:
        p = input_path.resolve()
        st = p.stat()
        signature = {
            "path": str(p),
            "mtime": int(st.st_mtime),
            "size": st.st_size,
            "target": target_spec,
        }
        blob = json.dumps(signature, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _paths_for_hash(self, h: str) -> Dict[str, Path]:
        return {
            "out": self.cache_dir / f"temp_normalized_{h}.mp4",
            "meta": self.cache_dir / f"temp_normalized_{h}.meta.json",
            "lock": self.cache_dir / f"temp_normalized_{h}.lock",
        }

    @contextmanager
    def _file_lock(self, lock_path: Path, timeout_sec: int = 600):
        # 超簡易ロック（プロセス間でファイル存在をロック扱い）
        start = time.time()
        while lock_path.exists():
            if time.time() - start > timeout_sec:
                raise TimeoutError(f"Lock timeout: {lock_path}")
            time.sleep(0.1)
        try:
            lock_path.touch(exist_ok=False)
            yield
        finally:
            if lock_path.exists():
                lock_path.unlink(missing_ok=True)

    async def get_or_create_normalized_video(
        self,
        input_path: Path,
        target_spec: Dict,
        prefer_copy: bool = True,
        force_refresh: bool = False,
        no_cache: bool = False,
    ) -> Path:
        # 既に正規化済みのMP4が入力に来た場合でも、隣接するメタの target_spec が一致すれば再正規化を避ける
        try:
            if input_path.is_file() and input_path.suffix.lower() == ".mp4":
                meta_candidate = input_path.with_name(
                    input_path.stem + ".meta.json"
                )
                if meta_candidate.exists():
                    with open(meta_candidate, "r", encoding="utf-8") as f:
                        meta_obj = json.load(f)
                    cached_spec = meta_obj.get("target_spec")
                    if cached_spec == target_spec and not force_refresh:
                        logger.info(
                            f"[Cache] Normalized reuse: {input_path} (already matches target spec)"
                        )
                        return input_path
        except Exception as e:
            logger.debug(
                f"Skip pre-check for already-normalized input due to error: {e}"
            )

        h = self._hash_for_normalized(input_path, target_spec)
        p = self._paths_for_hash(h)
        out_mp4, meta_json, lock_file = p["out"], p["meta"], p["lock"]

        # no_cache → 常に作り直す（既存ファイルは使わない）
        if (
            not no_cache
            and out_mp4.exists()
            and meta_json.exists()
            and not force_refresh
        ):
            logger.info(f"[Cache] Normalized hit: {input_path} -> {out_mp4}")
            return out_mp4

        # 二重生成防止
        with self._file_lock(lock_file):
            # ロック取得後に再チェック
            if (
                not no_cache
                and out_mp4.exists()
                and meta_json.exists()
                and not force_refresh
            ):
                logger.info(
                    f"[Cache] Normalized hit(after lock): {input_path} -> {out_mp4}"
                )
                return out_mp4

            logger.info(f"[Cache] Normalized miss: {input_path} -> generating...")

            # すでに“正規化済み”の可能性（≒入力がターゲットを満たす）をプローブで判定
            current = await probe_media_params_async(input_path)
            needs_encode, copy_ok = self._judge_need_encode(
                current, target_spec, prefer_copy
            )

            # 新経路: normalize_media を使用し、HW検出とオプションを統一
            # target_spec から VideoParams / AudioParams を構築
            v_spec = target_spec.get("video", {}) if isinstance(target_spec, dict) else {}
            a_spec = target_spec.get("audio", {}) if isinstance(target_spec, dict) else {}

            video_params = VideoParams(
                width=int(v_spec.get("width", 1920)) if v_spec.get("width") else 1920,
                height=int(v_spec.get("height", 1080)) if v_spec.get("height") else 1080,
                fps=int(v_spec.get("fps", 30)) if v_spec.get("fps") else 30,
                pix_fmt=v_spec.get("pix_fmt", "yuv420p"),
                profile=v_spec.get("profile", "high"),
                level=v_spec.get("level", "4.2"),
            )
            audio_params = AudioParams(
                sample_rate=int(a_spec.get("sr", 48000)) if a_spec.get("sr") else 48000,
                channels=int(a_spec.get("ch", 2)) if a_spec.get("ch") else 2,
                codec=a_spec.get("codec", "libmp3lame"),
            )

            # normalize_media はキャッシュマネージャを通じてキャッシュ名で出力する
            try:
                normalized_path = await normalize_media(
                    input_path=input_path,
                    video_params=video_params,
                    audio_params=audio_params,
                    cache_manager=self,
                )
                logger.info(
                    f"Successfully normalized {input_path} to {normalized_path} using normalize_media."
                )
                return normalized_path
            except Exception as e:
                # NVENC 失敗 (exit code 234) などを検知し、libx264 で1回だけ再試行
                msg = str(e)
                should_fallback = (
                    "exit status 234" in msg
                    or "exit code 234" in msg
                    or "h264_nvenc" in msg
                    or "NVENC" in msg
                )
                if should_fallback:
                    logger.warning(
                        "NVENC failed during normalization. Falling back to libx264 and retrying once."
                    )
                    prev = os.environ.get("DISABLE_HWENC")
                    os.environ["DISABLE_HWENC"] = "1"
                    try:
                        normalized_path = await normalize_media(
                            input_path=input_path,
                            video_params=video_params,
                            audio_params=audio_params,
                            cache_manager=self,
                        )
                        logger.info(
                            f"Successfully normalized (fallback CPU) {input_path} -> {normalized_path}"
                        )
                        return normalized_path
                    finally:
                        if prev is None:
                            os.environ.pop("DISABLE_HWENC", None)
                        else:
                            os.environ["DISABLE_HWENC"] = prev
                # フォールバック対象でなければそのまま送出
                raise

    def _judge_need_encode(self, current: Dict, target_spec: Dict, prefer_copy: bool):
        """
        current: probeで得た vwidth, vheight, vfps, vpix_fmt, vcodec, asr, ach, acodec など
        """
        v_tgt = target_spec.get("video") or {}
        a_tgt = target_spec.get("audio") or {}

        # “完全一致”の簡易判定（実用はもう少し緩くてもよい）
        video_match = all(
            [
                (v_tgt.get("width") is None or v_tgt["width"] == current.get("width")),
                (
                    v_tgt.get("height") is None
                    or v_tgt["height"] == current.get("height")
                ),
                (
                    v_tgt.get("fps") is None
                    or int(v_tgt["fps"]) == int(current.get("fps", 0))
                ),
                (
                    v_tgt.get("pix_fmt") is None
                    or v_tgt["pix_fmt"] == current.get("pix_fmt")
                ),
                (v_tgt.get("codec") is None or v_tgt["codec"] == current.get("vcodec")),
            ]
        )
        audio_match = all(
            [
                (a_tgt.get("sr") is None or a_tgt["sr"] == current.get("asr")),
                (a_tgt.get("ch") is None or a_tgt["ch"] == current.get("ach")),
                (a_tgt.get("codec") is None or a_tgt["codec"] == current.get("acodec")),
            ]
        )

        needs_encode = not (video_match and audio_match)
        copy_ok = prefer_copy and (video_match and audio_match)
        return needs_encode, copy_ok
