import os


def get_openai_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Run: export OPENAI_API_KEY=sk-..."
        )
    return key


def get_anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return key
