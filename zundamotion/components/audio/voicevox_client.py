import asyncio
import json
from typing import Any, Dict, List

import httpx

from .provider import TTSProviderCapabilities


RETRY_EXCEPTIONS = (httpx.RequestError, asyncio.TimeoutError)
DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS = 30.0


async def _with_retry(
    coro_factory,
    *,
    attempts: int,
    wait_min: float,
    wait_max: float,
):
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await coro_factory()
        except RETRY_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            wait_sec = min(wait_max, max(wait_min, wait_min * (2 ** (attempt - 1))))
            await asyncio.sleep(wait_sec)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("VOICEVOX retry loop exited unexpectedly.")


class VoicevoxTTSProvider:
    """VOICEVOX implementation of the common TTS provider boundary."""

    provider_id = "voicevox"

    def __init__(self, base_url: str = "http://127.0.0.1:50021") -> None:
        self.base_url = str(base_url).rstrip("/")

    @property
    def capabilities(self) -> TTSProviderCapabilities:
        return TTSProviderCapabilities(
            provider_id=self.provider_id,
            languages=("ja",),
            supports_speed=True,
            supports_pitch=True,
            supports_speaker_listing=True,
            supports_engine_version=True,
            supports_word_alignment=False,
        )

    async def list_speakers(
        self,
        *,
        timeout: float = DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS,
        retry_attempts: int = 2,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 2.0,
    ) -> Dict[int, Dict[str, Any]]:
        """Fetch speaker information with a bounded retry budget."""

        async def _fetch() -> Dict[int, Dict[str, Any]]:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{self.base_url}/speakers", timeout=timeout)
                res.raise_for_status()
                speakers_data: List[Dict[str, Any]] = res.json()

                speaker_info = {}
                for speaker_group in speakers_data:
                    for speaker in speaker_group.get("styles", []):
                        speaker_info[speaker["id"]] = {
                            "name": speaker["name"],
                            "speaker_name": speaker_group["name"],
                        }
                return speaker_info

        try:
            return await _with_retry(
                _fetch,
                attempts=retry_attempts,
                wait_min=retry_wait_min,
                wait_max=retry_wait_max,
            )
        except httpx.RequestError as e:
            print(f"Failed to connect to VOICEVOX to get speaker info: {e}")
            print("Please ensure the VOICEVOX engine is running.")
            raise
        except httpx.HTTPStatusError as e:
            print(f"HTTP error occurred during speaker info retrieval: {e}")
            raise
        except asyncio.TimeoutError as e:
            print(f"Timeout occurred during speaker info retrieval: {e}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred during speaker info retrieval: {e}")
            raise

    async def engine_version(
        self,
        *,
        timeout: float = DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS,
        retry_attempts: int = 2,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 2.0,
    ) -> str:
        """Fetch VOICEVOX engine version when the endpoint is available."""

        async def _fetch() -> str:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{self.base_url}/version", timeout=timeout)
                res.raise_for_status()
                content_type = res.headers.get("content-type", "")
                value = res.json() if content_type.startswith("application/json") else res.text
                return str(value).strip().strip('"')

        try:
            return await _with_retry(
                _fetch,
                attempts=retry_attempts,
                wait_min=retry_wait_min,
                wait_max=retry_wait_max,
            )
        except Exception:
            return "unknown"

    async def synthesize(
        self,
        *,
        text: str,
        speaker: int,
        filepath: str,
        speed: float = 1.0,
        pitch: float = 0.0,
        timeout: float = DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS,
        retry_attempts: int = 3,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 3.0,
    ) -> None:
        """Generate a voice file using the VOICEVOX API."""

        async def _generate() -> None:
            async with httpx.AsyncClient() as client:
                query_params = {"text": text, "speaker": speaker}
                res_query = await client.post(
                    f"{self.base_url}/audio_query", params=query_params, timeout=timeout
                )
                res_query.raise_for_status()
                query_data = res_query.json()

                query_data["speedScale"] = speed
                query_data["pitchScale"] = pitch
                synth_params = {"speaker": speaker}
                res_synth = await client.post(
                    f"{self.base_url}/synthesis",
                    params=synth_params,
                    content=json.dumps(query_data),
                    headers={"Content-Type": "application/json"},
                    timeout=timeout,
                )
                res_synth.raise_for_status()

                with open(filepath, "wb") as f:
                    f.write(res_synth.content)

        try:
            await _with_retry(
                _generate,
                attempts=retry_attempts,
                wait_min=retry_wait_min,
                wait_max=retry_wait_max,
            )
        except httpx.RequestError as e:
            print(f"Failed to connect to VOICEVOX: {e}")
            print("Please ensure the VOICEVOX engine is running.")
            raise
        except httpx.HTTPStatusError as e:
            body = ""
            if e.response is not None:
                body_text = e.response.text.strip()
                if body_text:
                    body = f" Response body: {body_text[:500]}"
            print(f"HTTP error occurred during voice generation: {e}.{body}")
            raise
        except asyncio.TimeoutError as e:
            print(f"Timeout occurred during voice generation: {e}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred during voice generation: {e}")
            raise


# Compatibility wrappers. Existing AudioGenerator imports remain valid while the
# provider object becomes the reusable backend boundary for future engines.
async def get_speakers_info(
    voicevox_url: str = "http://127.0.0.1:50021",
    *,
    timeout: float = DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS,
    retry_attempts: int = 2,
    retry_wait_min: float = 1.0,
    retry_wait_max: float = 2.0,
) -> Dict[int, Dict[str, Any]]:
    return await VoicevoxTTSProvider(voicevox_url).list_speakers(
        timeout=timeout,
        retry_attempts=retry_attempts,
        retry_wait_min=retry_wait_min,
        retry_wait_max=retry_wait_max,
    )


async def get_engine_version(
    voicevox_url: str = "http://127.0.0.1:50021",
    *,
    timeout: float = DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS,
    retry_attempts: int = 2,
    retry_wait_min: float = 1.0,
    retry_wait_max: float = 2.0,
) -> str:
    return await VoicevoxTTSProvider(voicevox_url).engine_version(
        timeout=timeout,
        retry_attempts=retry_attempts,
        retry_wait_min=retry_wait_min,
        retry_wait_max=retry_wait_max,
    )


async def generate_voice(
    text: str,
    speaker: int,
    filepath: str,
    speed: float = 1.0,
    pitch: float = 0.0,
    voicevox_url: str = "http://127.0.0.1:50021",
    *,
    timeout: float = DEFAULT_VOICEVOX_REQUEST_TIMEOUT_SECONDS,
    retry_attempts: int = 3,
    retry_wait_min: float = 1.0,
    retry_wait_max: float = 3.0,
):
    await VoicevoxTTSProvider(voicevox_url).synthesize(
        text=text,
        speaker=speaker,
        filepath=filepath,
        speed=speed,
        pitch=pitch,
        timeout=timeout,
        retry_attempts=retry_attempts,
        retry_wait_min=retry_wait_min,
        retry_wait_max=retry_wait_max,
    )
