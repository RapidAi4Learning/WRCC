"""Meta Graph API transport and error taxonomy.

Ported from the proven layer in ``mcc-growth-agent`` (``connect/meta/errors.py``
and ``transport.py``), with the transport rewritten on ``httpx.AsyncClient`` —
the reference drives stdlib ``urllib`` through a thread executor, while this
codebase is httpx-async throughout.

The error codes below are the valuable part: they let a caller tell "your token
died, reconnect" from "you are being throttled, wait" from "this request was
wrong", which is the difference between a useful message and a raw Graph
string in the operator's face.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings


class MetaGraphError(RuntimeError):
    """A Meta Graph API call returned an error payload."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class MetaAuthError(MetaGraphError):
    """Token invalid/expired/insufficient — the connection must be re-authed."""


class MetaRateLimitError(MetaGraphError):
    """Application or user rate limit hit — back off and retry later."""


class MetaTransientError(MetaGraphError):
    """A temporary Graph failure — worth retrying."""


# Graph error codes that mean the token or permission is the problem.
_AUTH_CODES = frozenset({102, 190, 200, 459, 463, 464, 467})
# Codes that mean we are being throttled.
_RATE_LIMIT_CODES = frozenset({4, 17, 32, 613})
# Temporary failures (API Unknown / API Service).
_TRANSIENT_CODES = frozenset({1, 2})


def redact_access_token(text: str) -> str:
    """Blank out any ``access_token`` value so tokens never reach a log line.

    Graph reads carry the token in the query string, and its error messages
    sometimes echo the request back, so this runs on every logged URL and every
    error message.
    """
    return re.sub(r"(access_token=)[^&\s]*", r"\1REDACTED", text)


def raise_for_graph_error(payload: Any) -> None:
    """Raise the appropriate typed error when ``payload`` carries a Graph error."""
    if not isinstance(payload, dict):
        return
    error = payload.get("error")
    if not isinstance(error, dict):
        return
    code = error.get("code")
    code_int = (
        int(code) if isinstance(code, int | str) and str(code).isdigit() else None
    )
    message = redact_access_token(str(error.get("message") or "Meta Graph API error"))
    if code_int in _AUTH_CODES:
        raise MetaAuthError(message, code=code_int)
    if code_int in _RATE_LIMIT_CODES:
        raise MetaRateLimitError(message, code=code_int)
    if code_int in _TRANSIENT_CODES:
        raise MetaTransientError(message, code=code_int)
    raise MetaGraphError(message, code=code_int)


class GraphClient:
    """Thin async Graph client that maps error payloads to typed exceptions.

    ``transport`` is the test seam: unit tests inject an ``httpx.MockTransport``
    and script the Graph conversation without touching the network, following
    the same pattern as ``PoliteFetcher`` in the scraper.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        access_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = settings.graph_base_url
        self._access_token = access_token
        self._timeout = settings.publish_timeout_seconds
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=self._timeout)

    def _with_token(self, params: dict | None) -> dict:
        merged = dict(params or {})
        if self._access_token is not None:
            merged.setdefault("access_token", self._access_token)
        return merged

    async def get(self, path: str, *, params: dict | None = None) -> dict:
        async with self._client() as client:
            response = await client.get(
                f"{self._base}{path}", params=self._with_token(params)
            )
        return self._payload(response)

    async def post(self, path: str, *, data: dict | None = None) -> dict:
        async with self._client() as client:
            response = await client.post(
                f"{self._base}{path}", data=self._with_token(data)
            )
        return self._payload(response)

    async def post_files(self, path: str, *, data: dict, files: dict) -> dict:
        """Multipart POST — used to hand Graph raw image bytes.

        Uploading bytes beats pointing Graph at a URL: it removes the need for
        this backend to be publicly reachable, so Facebook publishing works from
        a laptop. Instagram has no such option and must be given a URL.
        """
        async with self._client() as client:
            response = await client.post(
                f"{self._base}{path}", data=self._with_token(data), files=files
            )
        return self._payload(response)

    def _payload(self, response: httpx.Response) -> dict:
        """Parse the body, mapping Graph errors before HTTP status.

        Graph reports request failures as 4xx whose JSON body carries the real
        reason; raising on status first would throw that away and surface every
        rejection as an opaque HTTP error.
        """
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaTransientError(
                f"Graph returned HTTP {response.status_code} with a non-JSON body."
            ) from exc
        raise_for_graph_error(payload)
        if response.is_error:
            raise MetaTransientError(
                f"Graph returned HTTP {response.status_code} without an error payload."
            )
        if not isinstance(payload, dict):
            raise MetaTransientError("Graph returned an unexpected body.")
        return payload
