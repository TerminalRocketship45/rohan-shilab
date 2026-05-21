import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock
import pytest
from compiler_agent import CompilerAgent, CompilerDebuggerAgent, CompilerSuccessButExecFailed


def _make_mock_response(content):
    mock = MagicMock()
    mock.choices[0].message.content = content
    return mock


def test_compiler_success_but_exec_failed_is_exception():
    exc = CompilerSuccessButExecFailed("exec blew up")
    assert isinstance(exc, Exception)
    assert "exec blew up" in str(exc)


def test_compiler_agent_returns_error_response():
    agent = CompilerAgent(
        api_key="sk-test", model="gpt-4o-mini", dataset="mimic_iii",
        few_shot_examples="", system_message="sim"
    )
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _make_mock_response(
        "[ERROR]\nwrong column name"
    )
    result = agent.evaluate("some question", "some code")
    assert result.startswith("[ERROR]")
    assert "wrong column name" in result


def test_compiler_agent_returns_success_response():
    agent = CompilerAgent(
        api_key="sk-test", model="gpt-4o-mini", dataset="mimic_iii",
        few_shot_examples="", system_message="sim"
    )
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _make_mock_response("[SUCCESS]\n42")
    result = agent.evaluate("some question", "some code")
    assert result.startswith("[SUCCESS]")


def test_compiler_debugger_agent_error_contains_suggested_fix():
    agent = CompilerDebuggerAgent(
        api_key="sk-test", model="gpt-4o-mini", dataset="mimic_iii",
        few_shot_examples="", system_message="sim"
    )
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _make_mock_response(
        "[ERROR]\nbad column\nSuggested fix: use DRUG instead of DRUG_NAME"
    )
    result = agent.evaluate("some question", "some code")
    assert result.startswith("[ERROR]")
    assert "Suggested fix:" in result


def test_compiler_agent_passes_question_and_code_to_api():
    agent = CompilerAgent(
        api_key="sk-test", model="gpt-4o-mini", dataset="mimic_iii",
        few_shot_examples="examples here", system_message="system msg"
    )
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _make_mock_response("[SUCCESS]\n1")
    agent.evaluate("my question", "my code")
    call_args = agent.client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    assert messages[0]["content"] == "system msg"
    assert "my question" in messages[1]["content"]
    assert "my code" in messages[1]["content"]
