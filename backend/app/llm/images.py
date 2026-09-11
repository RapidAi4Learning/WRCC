"""Image client protocol + mock and live (OpenAI gpt-image-1) implementations.

Mirrors the text-LLM pattern: services depend on the ``ImageClient`` protocol,
``MockImageClient`` is deterministic and offline (LLM_MOCK=true), and the live
client is only constructed when the provider supports image generation.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib
from typing import Protocol

from app.config import ImageQuality, Settings
from app.llm.client import generate_with_retries


class ImageGenerationError(RuntimeError):
    """Raised when an image cannot be produced (provider or config).

    Its message reaches the browser as the error detail, so it is written for
    the person using the app, not for a log.
    """


IMAGE_UNAVAILABLE_MESSAGE = (
    "The image could not be generated right now. Please try again in a minute."
)


class ImageClient(Protocol):
    async def generate_image(
        self, prompt: str, *, quality: ImageQuality | None = None
    ) -> bytes:
        """Return the finished image as PNG bytes.

        ``quality`` trades time and cost for detail; None keeps IMAGE_QUALITY.
        """
        ...


# Matches the live gpt-image-1 default. Not cosmetic: Instagram rejects images
# under 320px, so a smaller mock would make the Instagram publish path
# unreachable in mock mode. A solid-colour PNG this size still compresses to a
# few KB.
_MOCK_IMAGE_SIZE = 1024


def _solid_png(rgb: tuple[int, int, int], size: int = _MOCK_IMAGE_SIZE) -> bytes:
    """Build a valid single-colour PNG without any imaging dependency."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class MockImageClient:
    """Deterministic offline image client: prompt → solid-colour PNG."""

    async def generate_image(
        self, prompt: str, *, quality: ImageQuality | None = None
    ) -> bytes:
        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        return _solid_png((digest[0], digest[1], digest[2]))


class OpenAIImageClient:
    """Live OpenAI image client (LLM_MOCK=false and LLM_PROVIDER=openai)."""

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        # Bounded, and with the SDK's own retries off: an image takes tens of
        # seconds, so anything beyond one bounded attempt would run past the
        # host's ~120 s request limit and surface as a 502.
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.image_timeout_seconds,
            max_retries=0,
        )
        self._model = settings.image_model
        self._size = settings.image_size
        self._quality = settings.image_quality

    async def generate_image(
        self, prompt: str, *, quality: ImageQuality | None = None
    ) -> bytes:
        chosen_quality = quality or self._quality

        async def attempt_once() -> bytes:
            response = await self._client.images.generate(
                model=self._model,
                prompt=prompt,
                size=self._size,  # type: ignore[arg-type]
                quality=chosen_quality,
                n=1,
            )
            payload = response.data[0].b64_json if response.data else None
            if not payload:
                raise ImageGenerationError("Provider returned an empty image payload.")
            return base64.b64decode(payload)

        try:
            return await generate_with_retries("OpenAI image", attempt_once, attempts=1)
        except ImageGenerationError:
            raise
        except Exception as exc:
            raise ImageGenerationError(IMAGE_UNAVAILABLE_MESSAGE) from exc


def get_image_client(settings: Settings) -> ImageClient:
    """Mock in mock mode; OpenAI when the provider supports images.

    Gemini image models are intentionally not wired up — raising here surfaces
    a clear configuration message instead of a provider error mid-request.
    """
    if settings.llm_mock:
        return MockImageClient()
    if settings.llm_provider == "openai":
        return OpenAIImageClient(settings)
    raise ImageGenerationError(
        "Image generation requires LLM_PROVIDER=openai (or LLM_MOCK=true)."
    )
