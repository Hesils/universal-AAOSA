# src/aaosa/runtime/providers.py
"""Abstraction provider LLM — seam unique de tous les appels LLM du runtime.

LLMProvider expose deux opérations couvrant les deux familles d'appels du
runtime : complete() (complétion brute) et parse() (sortie structurée Pydantic).
parse() encapsule la divergence des providers : OpenAI via beta.parse, Ollama
via émulation JSON ; les deux retombent sur une validation JSON du contenu.
"""

from abc import ABC, abstractmethod

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

DEFAULT_MODEL = "gpt-4o-mini"


class LLMProvider(ABC):
    """Interface agnostique au provider. Les sous-classes wrappent un SDK concret."""

    _client: OpenAI
    _default_model: str

    @property
    def client(self) -> OpenAI:
        """Accessor transitoire vers le SDK sous-jacent (forme OpenAI-compatible).

        Utilisé pendant la migration par les call-sites pas encore portés sur
        complete()/parse(). À terme, plus aucun appel direct ne devrait subsister.
        """
        return self._client

    @abstractmethod
    def complete(
        self, *, messages: list, model: str | None = None,
        tools: list | None = None, **kwargs,
    ) -> ChatCompletion:
        """Complétion brute. model=None → modèle par défaut du provider."""

    @abstractmethod
    def parse(
        self, *, messages: list, schema: type[BaseModel],
        model: str | None = None, **kwargs,
    ) -> BaseModel | None:
        """Sortie structurée → instance de `schema`, ou None si parse impossible."""

    def _complete(self, *, messages, model, tools, **kwargs) -> ChatCompletion:
        call_kwargs = {"model": model if model is not None else self._default_model, "messages": messages, **kwargs}
        if tools is not None:
            call_kwargs["tools"] = tools
        return self._client.chat.completions.create(**call_kwargs)

    def _parse_via_json(self, *, messages, schema, model, **kwargs) -> BaseModel | None:
        """Fallback commun : completion brute + validation JSON du contenu."""
        try:
            resp = self._complete(messages=messages, model=model, tools=None, **kwargs)
            raw = resp.choices[0].message.content or ""
            return schema.model_validate_json(raw)
        except Exception:
            return None


class OpenAIProvider(LLMProvider):
    def __init__(self, client: OpenAI | None = None, default_model: str = DEFAULT_MODEL) -> None:
        self._client = client if client is not None else OpenAI()
        self._default_model = default_model

    def complete(self, *, messages, model=None, tools=None, **kwargs) -> ChatCompletion:
        return self._complete(messages=messages, model=model, tools=tools, **kwargs)

    def parse(self, *, messages, schema, model=None, **kwargs) -> BaseModel | None:
        try:
            resp = self._client.beta.chat.completions.parse(
                model=model if model is not None else self._default_model,
                messages=messages,
                response_format=schema,
                **kwargs,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is not None:
                return parsed
        except Exception:
            pass  # structured output indisponible — fallback JSON
        return self._parse_via_json(messages=messages, schema=schema, model=model, **kwargs)


class OllamaProvider(LLMProvider):
    DEFAULT_OLLAMA_MODEL = "llama3.1"

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        default_model: str = DEFAULT_OLLAMA_MODEL,
        api_key: str = "ollama",
    ) -> None:
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._default_model = default_model

    def complete(self, *, messages, model=None, tools=None, **kwargs) -> ChatCompletion:
        return self._complete(messages=messages, model=model, tools=tools, **kwargs)

    def parse(self, *, messages, schema, model=None, **kwargs) -> BaseModel | None:
        # beta.parse non fiable sur Ollama — émulation directe via JSON.
        kwargs.setdefault("response_format", {"type": "json_object"})
        return self._parse_via_json(messages=messages, schema=schema, model=model, **kwargs)
