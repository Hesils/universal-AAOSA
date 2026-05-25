import pytest
import openai
from aaosa.runtime.llm_client import create_client


def test_create_client_returns_openai_instance():
    """Test that create_client returns an instance of openai.OpenAI."""
    client = create_client(api_key="sk-test-123")
    assert isinstance(client, openai.OpenAI)


def test_create_client_uses_provided_api_key():
    """Test that the provided api_key is set on the returned client."""
    api_key = "sk-test-123"
    client = create_client(api_key=api_key)
    assert client.api_key == api_key


def test_create_client_no_global_state():
    """Test that each call to create_client returns a new instance."""
    client_a = create_client(api_key="sk-key-a")
    client_b = create_client(api_key="sk-key-b")
    assert client_a is not client_b


def test_create_client_without_api_key(monkeypatch):
    """Test that create_client() reads OPENAI_API_KEY from environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-env-key")
    client = create_client()
    assert isinstance(client, openai.OpenAI)


def test_create_client_signature():
    """Test that create_client is importable and callable."""
    assert callable(create_client)
