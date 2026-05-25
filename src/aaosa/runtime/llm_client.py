import openai


def create_client(api_key: str | None = None) -> openai.OpenAI:
    """Create and return a new OpenAI client instance.

    Args:
        api_key: Optional API key. If not provided, reads from OPENAI_API_KEY env var.

    Returns:
        A new openai.OpenAI instance.
    """
    if api_key is not None:
        return openai.OpenAI(api_key=api_key)
    else:
        return openai.OpenAI()
