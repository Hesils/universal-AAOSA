# tests/runtime/test_providers.py
from unittest.mock import MagicMock

import pytest
from openai import OpenAI
from pydantic import BaseModel

from aaosa.runtime.providers import (
    DEFAULT_MODEL,
    LLMProvider,
    OllamaProvider,
    OpenAIProvider,
)


class _Schema(BaseModel):
    value: str


def _fake_openai():
    client = MagicMock(spec=OpenAI)
    return client


class TestOpenAIProvider:
    def test_is_llmprovider(self):
        assert isinstance(OpenAIProvider(client=_fake_openai()), LLMProvider)

    def test_complete_uses_default_model(self):
        client = _fake_openai()
        p = OpenAIProvider(client=client)
        p.complete(messages=[{"role": "user", "content": "hi"}])
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert "tools" not in kwargs  # tools=None omis

    def test_complete_overrides_model_and_passes_tools_and_kwargs(self):
        client = _fake_openai()
        p = OpenAIProvider(client=client)
        p.complete(messages=[], model="gpt-4o", tools=[{"x": 1}], temperature=0.0)
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["tools"] == [{"x": 1}]
        assert kwargs["temperature"] == 0.0

    def test_parse_returns_parsed_object(self):
        client = _fake_openai()
        resp = MagicMock()
        resp.choices[0].message.parsed = _Schema(value="ok")
        client.beta.chat.completions.parse.return_value = resp
        p = OpenAIProvider(client=client)
        out = p.parse(messages=[], schema=_Schema)
        assert out == _Schema(value="ok")

    def test_parse_falls_back_to_json_completion(self):
        client = _fake_openai()
        client.beta.chat.completions.parse.side_effect = RuntimeError("unsupported")
        comp = MagicMock()
        comp.choices[0].message.content = '{"value": "from_json"}'
        client.chat.completions.create.return_value = comp
        p = OpenAIProvider(client=client)
        out = p.parse(messages=[], schema=_Schema)
        assert out == _Schema(value="from_json")

    def test_parse_returns_none_when_everything_fails(self):
        client = _fake_openai()
        client.beta.chat.completions.parse.side_effect = RuntimeError("x")
        comp = MagicMock()
        comp.choices[0].message.content = "not json"
        client.chat.completions.create.return_value = comp
        p = OpenAIProvider(client=client)
        assert p.parse(messages=[], schema=_Schema) is None

    def test_client_accessor_returns_underlying(self):
        client = _fake_openai()
        assert OpenAIProvider(client=client).client is client


class TestOllamaProvider:
    def test_is_llmprovider(self):
        assert isinstance(OllamaProvider(), LLMProvider)

    def test_uses_ollama_base_url(self):
        p = OllamaProvider(base_url="http://localhost:11434/v1")
        assert p.client.base_url.host == "localhost"

    def test_parse_validates_json_content(self):
        p = OllamaProvider()
        comp = MagicMock()
        comp.choices[0].message.content = '{"value": "v"}'
        p._client = MagicMock(spec=OpenAI)
        p._client.chat.completions.create.return_value = comp
        assert p.parse(messages=[], schema=_Schema) == _Schema(value="v")

    def test_parse_returns_none_on_bad_json(self):
        p = OllamaProvider()
        comp = MagicMock()
        comp.choices[0].message.content = "nope"
        p._client = MagicMock(spec=OpenAI)
        p._client.chat.completions.create.return_value = comp
        assert p.parse(messages=[], schema=_Schema) is None
