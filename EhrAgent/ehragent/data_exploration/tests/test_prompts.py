# EhrAgent/ehragent/data_exploration/tests/test_prompts.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from prompts.mimic_iii import (
    get_coding_agent_prompt,
    get_compiler_system_message,
    get_compiler_debugger_system_message,
    DATASET_SCHEMA_COLUMNS,
    DATASET_SCHEMA_NARRATIVE,
    CompilerAgent_FewShot_Examples,
)


def test_coding_prompt_with_schema_contains_schema():
    prompt = get_coding_agent_prompt(
        schema_str=DATASET_SCHEMA_NARRATIVE,
        examples="EXAMPLE",
        knowledge="KNOWLEDGE",
        question="What is 2+2?",
    )
    assert "Assume you have knowledge" in prompt
    assert "EXAMPLE" in prompt
    assert "KNOWLEDGE" in prompt
    assert "What is 2+2?" in prompt


def test_coding_prompt_no_schema_omits_assume():
    prompt = get_coding_agent_prompt(
        schema_str="",
        examples="EX",
        knowledge="KN",
        question="Q?",
    )
    assert "Assume you have knowledge" not in prompt
    assert "Write a python code" in prompt


def test_compiler_system_message_with_schema():
    msg = get_compiler_system_message(DATASET_SCHEMA_COLUMNS)
    assert "admissions" in msg
    assert "SUBJECT_ID" in msg
    assert "SUCCESS" in msg


def test_compiler_system_message_no_schema():
    msg = get_compiler_system_message("")
    assert "No schema provided" in msg
    assert "API syntax" in msg


def test_debugger_system_message_adds_fix_prefix():
    msg = get_compiler_debugger_system_message("")
    assert "Suggested fix:" in msg


def test_few_shot_examples_not_empty():
    assert len(CompilerAgent_FewShot_Examples) > 100


def test_loaddb_table_list_present_in_prompt():
    prompt = get_coding_agent_prompt(schema_str="", examples="", knowledge="", question="Q?")
    assert "admissions" in prompt
    assert "LoadDB" in prompt
