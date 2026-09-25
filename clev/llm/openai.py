"""OpenAI adapter for LLMClient (Responses API with structured outputs)."""

from __future__ import annotations

import time
from typing import TypeVar

from openai import AsyncOpenAI, BadRequestError, OpenAIError
from pydantic import BaseModel

from clev.core.errors import LLMError
from clev.core.interfaces import LLMResult
from clev.llm.pricing import cost_usd

T = TypeVar("T", bound=BaseModel)


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        reasoning_effort: str = "low",
        timeout_s: float = 60.0,
        max_retries: int = 2,
    ):
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_s, max_retries=max_retries)
        self.reasoning_effort = reasoning_effort
        self._no_reasoning: set[str] = set()  # models that rejected the reasoning parameter

    async def complete(
        self, *, model: str, system: str, user: str, schema: type[T], max_output_tokens: int = 1000
    ) -> LLMResult[T]:
        kwargs = {
            "model": model,
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "text_format": schema,
            "max_output_tokens": max_output_tokens,
        }
        if self.reasoning_effort and model not in self._no_reasoning:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        start = time.perf_counter()
        try:
            try:
                response = await self._client.responses.parse(**kwargs)
            except BadRequestError as e:
                if "reasoning" not in str(e).lower() or "reasoning" not in kwargs:
                    raise
                # Non-reasoning model: remember and retry without the parameter.
                self._no_reasoning.add(model)
                kwargs.pop("reasoning")
                response = await self._client.responses.parse(**kwargs)
        except OpenAIError as e:
            raise LLMError(f"OpenAI call failed: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000

        parsed = response.output_parsed
        if parsed is None:
            raise LLMError(f"OpenAI returned no parsable output (status {response.status})")
        usage = response.usage
        tokens_in = usage.input_tokens if usage else 0
        tokens_out = usage.output_tokens if usage else 0
        return LLMResult[schema](
            parsed=parsed,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd(model, tokens_in, tokens_out),
        )
