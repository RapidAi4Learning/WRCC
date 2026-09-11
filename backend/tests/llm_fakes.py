"""Test doubles for the LLMClient protocol."""

from __future__ import annotations

import asyncio

from app.llm.client import LLMError, MockLLMClient, SocialPostDraft


class SlowLLM:
    """An LLM that takes ``delay`` seconds per call and records concurrency.

    Delegates the actual copy to ``MockLLMClient`` so drafts stay valid and
    deterministic. ``fail_style`` makes that one variant raise ``LLMError``
    after ``fail_delay`` — the shape of a provider giving up after retries.
    """

    def __init__(
        self,
        delay: float = 0.3,
        *,
        fail_style: str | None = None,
        fail_delay: float = 0.05,
    ) -> None:
        self.delay = delay
        self.fail_style = fail_style
        self.fail_delay = fail_delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.started = 0
        self.completed = 0
        # Every effort a generation asked for, in order.
        self.efforts: list[str | None] = []
        self._mock = MockLLMClient()

    def with_reasoning_effort(self, effort: str | None) -> SlowLLM:
        self.efforts.append(effort)
        return self

    async def generate_social_post(self, context: dict) -> SocialPostDraft:
        self.started += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if context.get("variant_style") == self.fail_style:
                await asyncio.sleep(self.fail_delay)
                raise LLMError("AI generation failed after retries.")
            await asyncio.sleep(self.delay)
            post = await self._mock.generate_social_post(context)
            self.completed += 1
            return post
        finally:
            self.in_flight -= 1

    async def suggest_image_prompts(self, context: dict) -> list[str]:
        return await self._mock.suggest_image_prompts(context)
