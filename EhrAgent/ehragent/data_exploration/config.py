import os


def get_provider():
    """Return 'anthropic' if only ANTHROPIC_API_KEY is set, else 'openai'."""
    if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        return "anthropic"
    return "openai"


def get_openai_key():
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise EnvironmentError(
            "No API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
        )
    return key


def get_anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return key
