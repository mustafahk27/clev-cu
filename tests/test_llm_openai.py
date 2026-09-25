"""OpenAI adapter logic with the SDK call stubbed out (no network)."""

from types import SimpleNamespace

import httpx2 as httpx  # the HTTP library openai 3.x uses
import pytest
from openai import BadRequestError
from pydantic import BaseModel

from clev.core.errors import LLMError
from clev.llm.openai import OpenAIClient
from clev.llm.pricing import cost_usd


class Out(BaseModel):
    answer: str


def response(parsed, tokens_in=1000, tokens_out=100):
    return SimpleNamespace(
        output_parsed=parsed,
        status="completed",
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
    )


def bad_request(msg):
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


def stub(client, *results):
    calls = []
    results = list(results)

    async def parse(**kwargs):
        calls.append(kwargs)
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    client._client.responses.parse = parse
    return calls


async def test_complete_returns_parsed_output_usage_and_cost():
    client = OpenAIClient("sk-test", reasoning_effort="low")
    calls = stub(client, response(Out(answer="yes")))
    result = await client.complete(model="gpt-6-luna", system="s", user="u", schema=Out)
    assert result.parsed.answer == "yes"
    assert (result.input_tokens, result.output_tokens) == (1000, 100)
    assert result.cost_usd == pytest.approx(cost_usd("gpt-6-luna", 1000, 100))
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert calls[0]["text_format"] is Out
    assert calls[0]["input"][0] == {"role": "system", "content": "s"}


async def test_reasoning_parameter_dropped_for_models_that_reject_it():
    client = OpenAIClient("sk-test", reasoning_effort="low")
    calls = stub(
        client,
        bad_request("Unsupported parameter: 'reasoning.effort'"),
        response(Out(answer="a")),
        response(Out(answer="b")),
    )
    await client.complete(model="old-model", system="s", user="u", schema=Out)
    await client.complete(model="old-model", system="s", user="u", schema=Out)
    assert "reasoning" in calls[0] and "reasoning" not in calls[1] and "reasoning" not in calls[2]


async def test_other_errors_and_empty_output_raise_llm_error():
    client = OpenAIClient("sk-test")
    stub(client, bad_request("Invalid schema"))
    with pytest.raises(LLMError):
        await client.complete(model="m", system="s", user="u", schema=Out)
    stub(client, response(None))
    with pytest.raises(LLMError):
        await client.complete(model="m", system="s", user="u", schema=Out)


def test_pricing():
    assert cost_usd("gpt-6-luna", 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert cost_usd("unknown-model", 10, 10) == 0.0
