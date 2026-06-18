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
    ProviderUnreachableError,
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

    def test_complete_forwards_empty_string_model_verbatim(self):
        """Verify that model="" is NOT coerced to default — only None triggers default."""
        client = _fake_openai()
        p = OpenAIProvider(client=client)
        p.complete(messages=[], model="")
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "", "empty string model should be forwarded verbatim"

    def test_parse_forwards_empty_string_model_verbatim(self):
        """Verify that model="" is NOT coerced to default in parse — only None triggers default."""
        client = _fake_openai()
        p = OpenAIProvider(client=client)
        # beta.parse will fail, but we verify the model argument reached it
        client.beta.chat.completions.parse.side_effect = RuntimeError("x")
        comp = MagicMock()
        comp.choices[0].message.content = '{"value": "v"}'
        client.chat.completions.create.return_value = comp
        p.parse(messages=[], schema=_Schema, model="")
        # Check that beta.parse was called with the empty string
        kwargs = client.beta.chat.completions.parse.call_args.kwargs
        assert kwargs["model"] == "", "empty string model should be forwarded verbatim to parse"


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


class TestAvailableModels:
    def test_default_model_property(self):
        p = OpenAIProvider(client=_fake_openai(), default_model="gpt-4o")
        assert p.default_model == "gpt-4o"

    def test_available_models_returns_ids(self):
        client = _fake_openai()
        m1, m2 = MagicMock(), MagicMock()
        m1.id, m2.id = "gpt-4o-mini", "gpt-4o"
        client.models.list.return_value = [m1, m2]
        p = OpenAIProvider(client=client)
        assert p.available_models() == {"gpt-4o-mini", "gpt-4o"}

    def test_available_models_raises_provider_unreachable_on_error(self):
        client = _fake_openai()
        client.models.list.side_effect = RuntimeError("connection refused")
        p = OpenAIProvider(client=client)
        with pytest.raises(ProviderUnreachableError):
            p.available_models()

    def test_ollama_available_models_uses_same_path(self):
        p = OllamaProvider()
        p._client = _fake_openai()  # injecte un client mocké
        m = MagicMock()
        m.id = "qwen3:4b"
        p._client.models.list.return_value = [m]
        assert p.available_models() == {"qwen3:4b"}
