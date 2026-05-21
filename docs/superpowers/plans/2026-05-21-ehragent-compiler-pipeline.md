# EHRAgent Ethical Compiler Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-mode EHR agent pipeline (baseline, compiler-agent, newdebugger) that optionally routes code through an LLM schema-checker before real execution, ensuring the Coding Agent never receives raw patient data in error feedback.

**Architecture:** A single `pipeline.py` entry point supports three modes via `--compiler_agent` / `--newdebugger` flags. All modes share the same question-loading, output-folder, and result-saving logic. Mode differences live entirely inside `MedAgent.execute_function()`. Real execution via `run_code()` always happens last; any real-exec error in the compiler modes is swallowed silently (never fed back to the AI).

**Tech Stack:** Python 3.9+, openai==1.7.2, autogen==0.7.2, pandas, matplotlib, argparse, unittest.mock (tests)

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `EhrAgent/tools/tabtools.py` | Add `configure(dataset_path, dataset)` and path-aware db/SQL functions |
| Modify | `EhrAgent/ehragent/config.py` | Standard OpenAI config (remove Azure) |
| Modify | `EhrAgent/ehragent/toolset_high.py` | Inline CodeHeader, remove prompts_mimic dep, keep `run_code()` unchanged |
| Create | `EhrAgent/ehragent/compiler_agent.py` | `CompilerAgent`, `CompilerDebuggerAgent`, `CompilerSuccessButExecFailed` |
| Modify | `EhrAgent/ehragent/prompts_mimic.py` | Add compiler system message + few-shot template strings |
| Modify | `EhrAgent/ehragent/prompts_eicu.py` | Same for eICU schema |
| Modify | `EhrAgent/ehragent/medagent.py` | Standard OpenAI client, mode routing in `execute_function()` |
| Create | `EhrAgent/ehragent/pipeline.py` | Entry point: args, question loading, execution loop, output saving |
| Create | `EhrAgent/ehragent/tests/__init__.py` | Empty, marks test package |
| Create | `EhrAgent/ehragent/tests/conftest.py` | sys.path fixture for all tests |
| Create | `EhrAgent/ehragent/tests/test_tabtools.py` | Unit tests for configure + path building |
| Create | `EhrAgent/ehragent/tests/test_config.py` | Unit tests for config format |
| Create | `EhrAgent/ehragent/tests/test_compiler_agent.py` | Unit tests for CompilerAgent parsing (mocked OpenAI) |
| Create | `EhrAgent/ehragent/tests/test_pipeline_utils.py` | Unit tests for judge(), strip_examples(), output dir naming |

---

## Task 1: Test infrastructure + tabtools path configuration

**Files:**
- Create: `EhrAgent/ehragent/tests/__init__.py`
- Create: `EhrAgent/ehragent/tests/conftest.py`
- Create: `EhrAgent/ehragent/tests/test_tabtools.py`
- Modify: `EhrAgent/tools/tabtools.py`

- [ ] **Step 1: Create test package files**

```
# EhrAgent/ehragent/tests/__init__.py
(empty file)
```

```python
# EhrAgent/ehragent/tests/conftest.py
import sys, os
# Add EhrAgent root so 'from tools import tabtools' works in exec() during tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
# Add ehragent dir so pipeline.py, medagent.py etc are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
```

- [ ] **Step 2: Write failing tests for tabtools.configure()**

```python
# EhrAgent/ehragent/tests/test_tabtools.py
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
import tools.tabtools as tabtools

def setup_function():
    # Reset globals before each test
    tabtools._DATASET_PATH = None
    tabtools._DATASET = None

def test_configure_sets_dataset_path():
    tabtools.configure("/data/ehrsql", "mimic_iii")
    assert tabtools._DATASET_PATH == "/data/ehrsql"

def test_configure_sets_dataset():
    tabtools.configure("/data/ehrsql", "eicu")
    assert tabtools._DATASET == "eicu"

def test_db_loader_raises_keyerror_for_unknown_table():
    tabtools.configure("/fake/path", "mimic_iii")
    with pytest.raises(KeyError):
        tabtools.db_loader("nonexistent_table")

def test_db_loader_raises_keyerror_for_eicu_unknown_table():
    tabtools.configure("/fake/path", "eicu")
    with pytest.raises(KeyError):
        tabtools.db_loader("admissions")  # admissions is mimic_iii only
```

- [ ] **Step 3: Run tests to confirm they fail**

From `EhrAgent/ehragent/`:
```
python -m pytest tests/test_tabtools.py -v
```
Expected: FAIL — `configure` function not defined yet.

- [ ] **Step 4: Rewrite `EhrAgent/tools/tabtools.py`**

Replace the entire file content (preserve `data_filter`, `get_value` unchanged, replace `db_loader`, `sql_interpreter`, `date_calculator`, add `configure`):

```python
import pandas as pd
import json
import re
import sqlite3
import Levenshtein

_DATASET_PATH = None
_DATASET = None


def configure(dataset_path, dataset):
    global _DATASET_PATH, _DATASET
    _DATASET_PATH = dataset_path
    _DATASET = dataset


def _mimic_ehr_dict():
    base = os.path.join(_DATASET_PATH, "mimic_iii")
    return {
        "admissions":       os.path.join(base, "ADMISSIONS.csv"),
        "chartevents":      os.path.join(base, "CHARTEVENTS.csv"),
        "cost":             os.path.join(base, "COST.csv"),
        "d_icd_diagnoses":  os.path.join(base, "D_ICD_DIAGNOSES.csv"),
        "d_icd_procedures": os.path.join(base, "D_ICD_PROCEDURES.csv"),
        "d_items":          os.path.join(base, "D_ITEMS.csv"),
        "d_labitems":       os.path.join(base, "D_LABITEMS.csv"),
        "diagnoses_icd":    os.path.join(base, "DIAGNOSES_ICD.csv"),
        "icustays":         os.path.join(base, "ICUSTAYS.csv"),
        "inputevents_cv":   os.path.join(base, "INPUTEVENTS_CV.csv"),
        "labevents":        os.path.join(base, "LABEVENTS.csv"),
        "microbiologyevents": os.path.join(base, "MICROBIOLOGYEVENTS.csv"),
        "outputevents":     os.path.join(base, "OUTPUTEVENTS.csv"),
        "patients":         os.path.join(base, "PATIENTS.csv"),
        "prescriptions":    os.path.join(base, "PRESCRIPTIONS.csv"),
        "procedures_icd":   os.path.join(base, "PROCEDURES_ICD.csv"),
        "transfers":        os.path.join(base, "TRANSFERS.csv"),
    }


def _eicu_ehr_dict():
    base = os.path.join(_DATASET_PATH, "eicu")
    return {
        "allergy":       os.path.join(base, "allergy.csv"),
        "cost":          os.path.join(base, "cost.csv"),
        "diagnosis":     os.path.join(base, "diagnosis.csv"),
        "intakeoutput":  os.path.join(base, "intakeoutput.csv"),
        "lab":           os.path.join(base, "lab.csv"),
        "medication":    os.path.join(base, "medication.csv"),
        "microlab":      os.path.join(base, "microlab.csv"),
        "patient":       os.path.join(base, "patient.csv"),
        "treatment":     os.path.join(base, "treatment.csv"),
        "vitalperiodic": os.path.join(base, "vitalperiodic.csv"),
    }


def db_loader(target_ehr):
    ehr_dict = _mimic_ehr_dict() if _DATASET == "mimic_iii" else _eicu_ehr_dict()
    data = pd.read_csv(ehr_dict[target_ehr])
    return data


def data_filter(data, argument):
    backup_data = data
    commands = argument.split("||")
    for i in range(len(commands)):
        try:
            if ">=" in commands[i]:
                command = commands[i].split(">=")
                column_name, value = command[0], command[1]
                try:
                    value = type(data[column_name][0])(value)
                except:
                    pass
                data = data[data[column_name] >= value]
            elif "<=" in commands[i]:
                command = commands[i].split("<=")
                column_name, value = command[0], command[1]
                try:
                    value = type(data[column_name][0])(value)
                except:
                    pass
                data = data[data[column_name] <= value]
            elif ">" in commands[i]:
                command = commands[i].split(">")
                column_name, value = command[0], command[1]
                try:
                    value = type(data[column_name][0])(value)
                except:
                    pass
                data = data[data[column_name] > value]
            elif "<" in commands[i]:
                command = commands[i].split("<")
                column_name, value = command[0], command[1]
                if value[0] in ("'", '"'):
                    value = value[1:-1]
                try:
                    value = type(data[column_name][0])(value)
                except:
                    pass
                data = data[data[column_name] < value]
            elif "=" in commands[i]:
                command = commands[i].split("=")
                column_name, value = command[0], command[1]
                if value[0] in ("'", '"'):
                    value = value[1:-1]
                try:
                    examplar = backup_data[column_name].tolist()[0]
                    value = type(examplar)(value)
                except:
                    pass
                data = data[data[column_name] == value]
            elif " in " in commands[i]:
                command = commands[i].split(" in ")
                column_name = command[0]
                value = command[1]
                value_list = [s.strip() for s in value.strip("[]").split(",")]
                value_list = [s.strip("'").strip('"') for s in value_list]
                value_list = list(map(type(data[column_name][0]), value_list))
                data = data[data[column_name].isin(value_list)]
            elif "max" in commands[i]:
                column_name = commands[i].split("max(")[1].split(")")[0]
                data = data[data[column_name] == data[column_name].max()]
            elif "min" in commands[i]:
                column_name = commands[i].split("min(")[1].split(")")[0]
                data = data[data[column_name] == data[column_name].min()]
        except:
            if column_name not in data.columns.tolist():
                columns = ", ".join(data.columns.tolist())
                raise Exception(
                    "The filtering query {} is incorrect. Please modify the column name "
                    "or use LoadDB to read another table. The column names in the current "
                    "DB are {}.".format(commands[i], columns)
                )
            if column_name == "" or value == "":
                raise Exception(
                    "The filtering query {} is incorrect. There is syntax error in the "
                    "command. Please modify the condition or use LoadDB to read another "
                    "table.".format(commands[i])
                )
        if len(data) == 0:
            column_values = list(set(backup_data[column_name].tolist()))
            if "=" in commands[i] and value not in column_values and ">=" not in commands[i] and "<=" not in commands[i]:
                levenshtein_dist = {}
                for cv in column_values:
                    levenshtein_dist[cv] = Levenshtein.distance(str(cv), str(value))
                levenshtein_dist = sorted(levenshtein_dist.items(), key=lambda x: x[1])
                column_values = [i[0] for i in levenshtein_dist[:5]]
                column_values = ", ".join([str(i) for i in column_values])
                raise Exception(
                    "The filtering query {} is incorrect. There is no {} value in the "
                    "column. Five example values in the column are {}. Please check if "
                    "you get the correct {} value.".format(commands[i], value, column_values, column_name)
                )
            else:
                return data
    return data


def get_value(data, argument):
    try:
        commands = argument.split(", ")
        if len(commands) == 1:
            column = argument
            while column[0] in ("[", "'"):
                column = column[1:]
            while column[-1] in ("]", "'"):
                column = column[:-1]
            if len(data) == 1:
                return str(data.iloc[0][column])
            else:
                answer_list = list(set(data[column].tolist()))
                return ", ".join([str(i) for i in answer_list])
        else:
            column = commands[0]
            op = commands[-1]
            res_list = data[column].tolist()
            if "mean" in op:
                return sum(float(i) for i in res_list) / len(res_list)
            elif "max" in op:
                try:
                    return max(float(i) for i in res_list)
                except:
                    return max(str(i) for i in res_list)
            elif "min" in op:
                try:
                    return min(float(i) for i in res_list)
                except:
                    return min(str(i) for i in res_list)
            elif "sum" in op:
                return sum(float(i) for i in res_list)
            elif "list" in op:
                return [str(i) for i in res_list]
            else:
                raise Exception("The operation {} contains syntax errors.".format(op))
    except:
        column_values = ", ".join(data.columns.tolist())
        raise Exception(
            "The column name {} is incorrect. Please check the column name and make "
            "necessary changes. The columns in this table include {}.".format(argument, column_values)
        )


def sql_interpreter(command):
    if _DATASET == "mimic_iii":
        db_path = os.path.join(_DATASET_PATH, "mimic_iii", "mimic_iii.db")
    else:
        db_path = os.path.join(_DATASET_PATH, "eicu", "eicu.db")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    results = cur.execute(command).fetchall()
    con.close()
    return results


def date_calculator(argument):
    try:
        if _DATASET == "mimic_iii":
            db_path = os.path.join(_DATASET_PATH, "mimic_iii", "mimic_iii.db")
        else:
            db_path = os.path.join(_DATASET_PATH, "eicu", "eicu.db")
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        results = cur.execute(
            "select datetime(current_time, '{}')".format(argument)
        ).fetchall()[0][0]
        con.close()
    except:
        raise Exception(
            "The date calculator {} is incorrect. Please check the syntax and make "
            "necessary changes. For the current date and time, please call "
            "Calendar('0 year').".format(argument)
        )
    return results
```

Note: add `import os` at the top of the file.

- [ ] **Step 5: Run tests to confirm they pass**

```
python -m pytest tests/test_tabtools.py -v
```
Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```
git add EhrAgent/tools/tabtools.py EhrAgent/ehragent/tests/__init__.py EhrAgent/ehragent/tests/conftest.py EhrAgent/ehragent/tests/test_tabtools.py
git commit -m "feat: make tabtools paths configurable via configure(dataset_path, dataset)"
```

---

## Task 2: Update config.py and toolset_high.py

**Files:**
- Modify: `EhrAgent/ehragent/config.py`
- Modify: `EhrAgent/ehragent/toolset_high.py`
- Create: `EhrAgent/ehragent/tests/test_config.py`

- [ ] **Step 1: Write failing test for config format**

```python
# EhrAgent/ehragent/tests/test_config.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import openai_config, llm_config_list

def test_openai_config_has_required_keys():
    cfg = openai_config("gpt-4o-mini", "sk-test-key")
    assert cfg["model"] == "gpt-4o-mini"
    assert cfg["api_key"] == "sk-test-key"
    assert cfg["api_type"] == "openai"

def test_openai_config_no_azure_keys():
    cfg = openai_config("gpt-4o-mini", "sk-test-key")
    assert "base_url" not in cfg
    assert "api_version" not in cfg

def test_llm_config_list_has_cache_seed():
    cfg = llm_config_list(seed=42, config_list=[{"model": "gpt-4o-mini", "api_key": "sk-x"}])
    assert cfg["cache_seed"] == 42
    assert cfg["temperature"] == 0
    assert cfg["timeout"] == 120
    assert len(cfg["functions"]) == 1
    assert cfg["functions"][0]["name"] == "python"
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_config.py -v
```
Expected: FAIL — config returns Azure keys.

- [ ] **Step 3: Rewrite `EhrAgent/ehragent/config.py`**

```python
# EhrAgent/ehragent/config.py

def openai_config(model, api_key):
    return {
        "model": model,
        "api_key": api_key,
        "api_type": "openai",
    }


def llm_config_list(seed, config_list):
    return {
        "functions": [
            {
                "name": "python",
                "description": "run the entire code and return the execution result. Only generate the code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cell": {
                            "type": "string",
                            "description": "Valid Python code to execute.",
                        }
                    },
                    "required": ["cell"],
                },
            },
        ],
        "config_list": config_list,
        "timeout": 120,
        "cache_seed": seed,
        "temperature": 0,
    }
```

- [ ] **Step 4: Update `EhrAgent/ehragent/toolset_high.py`**

Replace the `from prompts_mimic import CodeHeader` import inside `run_code()` with an inline constant. The rest of the error-parsing logic is unchanged.

```python
# EhrAgent/ehragent/toolset_high.py
import sys
import time
import os
import traceback
from termcolor import colored

# Inlined so run_code() works for both mimic_iii and eicu without importing prompts
_CODE_HEADER = """from tools import tabtools, calculator
Calculate = calculator.WolframAlphaCalculator
LoadDB = tabtools.db_loader
FilterDB = tabtools.data_filter
GetValue = tabtools.get_value
SQLInterpreter = tabtools.sql_interpreter
Calendar = tabtools.date_calculator
"""


def run_code(cell):
    try:
        global_var = {"answer": 0}
        exec(_CODE_HEADER + cell, global_var)
        cell = "\n".join(
            [line for line in cell.split("\n") if line.strip() and not line.strip().startswith("#")]
        )
        if "answer" not in cell.split("\n")[-1]:
            return "Please save the answer to the question in the variable 'answer'."
        return str(global_var["answer"])
    except Exception as e:
        error_info = traceback.format_exc()
        code = _CODE_HEADER + cell
        if "SyntaxError" in str(repr(e)):
            error_line = str(repr(e))
            error_type = error_line.split("(")[0]
            error_message = error_line.split(",")[0].split("(")[1]
            error_line = error_line.split('"')[1]
        elif "KeyError" in str(repr(e)):
            code_lines = code.split("\n")
            key = str(repr(e)).split("'")[1]
            error_type = str(repr(e)).split("(")[0]
            error_line = ""
            for line in code_lines:
                if key in line:
                    error_line = line
            error_message = str(repr(e))
        elif "TypeError" in str(repr(e)):
            error_type = str(repr(e)).split("(")[0]
            error_message = str(e)
            function_mapping_dict = {
                "get_value": "GetValue",
                "data_filter": "FilterDB",
                "db_loader": "LoadDB",
                "sql_interpreter": "SQLInterpreter",
                "date_calculator": "Calendar",
            }
            error_key = ""
            for key in function_mapping_dict:
                if key in error_message:
                    error_message = error_message.replace(key, function_mapping_dict[key])
                    error_key = function_mapping_dict[key]
            code_lines = code.split("\n")
            error_line = ""
            for line in code_lines:
                if error_key in line:
                    error_line = line
        else:
            error_type = ""
            error_message = str(repr(e)).split("('")[-1].split("')")[0]
            error_line = ""

        if error_type and error_line:
            error_info = '{}: {}. The error messages occur in the code line "{}".'.format(
                error_type, error_message, error_line
            )
        else:
            error_info = "Error: {}.".format(error_message)
        error_info += "\nPlease make modifications accordingly and make sure the rest code works well with the modification."
        return error_info
```

- [ ] **Step 5: Run config tests to confirm they pass**

```
python -m pytest tests/test_config.py -v
```
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```
git add EhrAgent/ehragent/config.py EhrAgent/ehragent/toolset_high.py EhrAgent/ehragent/tests/test_config.py
git commit -m "feat: standard OpenAI config, dataset-agnostic run_code()"
```

---

## Task 3: Create compiler_agent.py

**Files:**
- Create: `EhrAgent/ehragent/compiler_agent.py`
- Create: `EhrAgent/ehragent/tests/test_compiler_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# EhrAgent/ehragent/tests/test_compiler_agent.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock, patch
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_compiler_agent.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create `EhrAgent/ehragent/compiler_agent.py`**

```python
# EhrAgent/ehragent/compiler_agent.py
from openai import OpenAI


class CompilerSuccessButExecFailed(Exception):
    """Raised when Compiler Agent says [SUCCESS] but real run_code() fails.
    Caught by pipeline to mark question as INCOMPLETED without feeding error back to AI."""
    pass


_PROMPT_TEMPLATE = """Here are examples of how to evaluate EHR query code:

{few_shot_examples}

Now evaluate the following code written to answer this question:
Question: {question}

Code:
{code}

Respond with [SUCCESS] or [ERROR] followed by the result or error message."""


class CompilerAgent:
    """LLM that checks code against EHR schema before real execution.
    Returns [SUCCESS]\\n<result> or [ERROR]\\n<error message>."""

    def __init__(self, api_key, model, dataset, few_shot_examples, system_message):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dataset = dataset
        self.few_shot_examples = few_shot_examples
        self.system_message = system_message

    def evaluate(self, question, code):
        prompt = _PROMPT_TEMPLATE.format(
            few_shot_examples=self.few_shot_examples,
            question=question,
            code=code,
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()


class CompilerDebuggerAgent:
    """Combined LLM that checks code AND provides a suggested fix in one call.
    Returns [SUCCESS]\\n<result> or [ERROR]\\n<error>\\nSuggested fix: <fix>."""

    def __init__(self, api_key, model, dataset, few_shot_examples, system_message):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dataset = dataset
        self.few_shot_examples = few_shot_examples
        self.system_message = system_message

    def evaluate(self, question, code):
        prompt = _PROMPT_TEMPLATE.format(
            few_shot_examples=self.few_shot_examples,
            question=question,
            code=code,
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=600,
        )
        return response.choices[0].message.content.strip()
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/test_compiler_agent.py -v
```
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```
git add EhrAgent/ehragent/compiler_agent.py EhrAgent/ehragent/tests/test_compiler_agent.py
git commit -m "feat: add CompilerAgent, CompilerDebuggerAgent, CompilerSuccessButExecFailed"
```

---

## Task 4: Add Compiler Agent prompt templates to prompts files

**Files:**
- Modify: `EhrAgent/ehragent/prompts_mimic.py`
- Modify: `EhrAgent/ehragent/prompts_eicu.py`

- [ ] **Step 1: Append to `EhrAgent/ehragent/prompts_mimic.py`**

Add at the bottom of the file (after `EHRAgent_4Shots_Knowledge`):

```python
# ── Compiler Agent prompts (mimic_iii) ──────────────────────────────────────

CompilerAgent_System_Message = """You are a code execution simulator for an EHR query system.
You receive Python code that uses EHR API functions and simulate what would happen if executed.
You know the full table and column schema but have NO access to actual patient data.

Available tables and columns (mimic_iii):
- admissions: ROW_ID, SUBJECT_ID, HADM_ID, ADMITTIME, DISCHTIME, ADMISSION_TYPE, ADMISSION_LOCATION, DISCHARGE_LOCATION, INSURANCE, LANGUAGE, MARITAL_STATUS, ETHNICITY, AGE
- chartevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM
- cost: ROW_ID, SUBJECT_ID, HADM_ID, EVENT_TYPE, EVENT_ID, CHARGETIME, COST
- d_icd_diagnoses: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE
- d_icd_procedures: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE
- d_items: ROW_ID, ITEMID, LABEL, LINKSTO
- d_labitems: ROW_ID, ITEMID, LABEL
- diagnoses_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME
- icustays: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, FIRST_CAREUNIT, LAST_CAREUNIT, FIRST_WARDID, LAST_WARDID, INTIME, OUTTIME
- inputevents_cv: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, AMOUNT
- labevents: ROW_ID, SUBJECT_ID, HADM_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM
- microbiologyevents: ROW_ID, SUBJECT_ID, HADM_ID, CHARTTIME, SPEC_TYPE_DESC, ORG_NAME
- outputevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, VALUE
- patients: ROW_ID, SUBJECT_ID, GENDER, DOB, DOD
- prescriptions: ROW_ID, SUBJECT_ID, HADM_ID, STARTDATE, ENDDATE, DRUG, DOSE_VAL_RX, DOSE_UNIT_RX, ROUTE
- procedures_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME
- transfers: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, EVENTTYPE, CAREUNIT, WARDID, INTIME, OUTTIME

Check for:
- Wrong table names passed to LoadDB()
- Wrong column names passed to FilterDB() or GetValue()
- Wrong argument format for any API function
- SQL syntax or schema errors in SQLInterpreter()
- Any other obvious code errors

Always respond with EXACTLY [SUCCESS] or [ERROR] on the first line, followed by your
simulated result (SUCCESS) or the predicted error message (ERROR)."""

CompilerDebuggerAgent_System_Message = CompilerAgent_System_Message + """

If you find an error, also provide a suggested fix on a new line prefixed with:
"Suggested fix: " """

CompilerAgent_FewShot_Examples = """--- Example 1: Correct API code → SUCCESS ---
Question: had any tpn w/lipids been given to patient 2238 in their last hospital visit?
Code:
patient_db = LoadDB('admissions')
filtered_patient_db = FilterDB(patient_db, 'SUBJECT_ID=2238||min(DISCHTIME)')
hadm_id = GetValue(filtered_patient_db, 'HADM_ID')
d_items_db = LoadDB('d_items')
filtered_d_items_db = FilterDB(d_items_db, 'LABEL=tpn w/lipids')
item_id = GetValue(filtered_d_items_db, 'ITEMID')
icustays_db = LoadDB('icustays')
filtered_icustays_db = FilterDB(icustays_db, 'HADM_ID={}'.format(hadm_id))
icustay_id = GetValue(filtered_icustays_db, 'ICUSTAY_ID')
inputevents_cv_db = LoadDB('inputevents_cv')
filtered_inputevents_cv_db = FilterDB(inputevents_cv_db, 'HADM_ID={}||ICUSTAY_ID={}||ITEMID={}'.format(hadm_id, icustay_id, item_id))
if len(filtered_inputevents_cv_db) > 0:
    answer = 1
else:
    answer = 0

[SUCCESS]
1

--- Example 2: Correct API code → SUCCESS ---
Question: calculate the length of stay of the first stay of patient 27392 in the icu.
Code:
from datetime import datetime
patient_db = LoadDB('admissions')
filtered_patient_db = FilterDB(patient_db, 'SUBJECT_ID=27392||min(ADMITTIME)')
hadm_id = GetValue(filtered_patient_db, 'HADM_ID')
icustays_db = LoadDB('icustays')
filtered_icustays_db = FilterDB(icustays_db, 'HADM_ID={}'.format(hadm_id))
intime = GetValue(filtered_icustays_db, 'INTIME')
outtime = GetValue(filtered_icustays_db, 'OUTTIME')
intime = datetime.strptime(intime, '%Y-%m-%d %H:%M:%S')
outtime = datetime.strptime(outtime, '%Y-%m-%d %H:%M:%S')
length_of_stay = outtime - intime
if length_of_stay.seconds // 3600 > 12:
    answer = length_of_stay.days + 1
else:
    answer = length_of_stay.days

[SUCCESS]
3

--- Example 3: PLACEHOLDER — fill after running Approach 3 baseline ---
--- Copy question, last_code, and last_error from errors.json ---
Question: <paste question here>
Code:
<paste last_code here>

[ERROR]
<paste last_error here>

--- Example 4: PLACEHOLDER — fill after running Approach 3 baseline ---
Question: <paste question here>
Code:
<paste last_code here>

[ERROR]
<paste last_error here>
"""
```

- [ ] **Step 2: Append to `EhrAgent/ehragent/prompts_eicu.py`**

Add at the bottom (after `EHRAgent_4Shots_Knowledge`):

```python
# ── Compiler Agent prompts (eicu) ───────────────────────────────────────────

CompilerAgent_System_Message = """You are a code execution simulator for an EHR query system.
You receive Python code that uses EHR API functions and simulate what would happen if executed.
You know the full table and column schema but have NO access to actual patient data.

Available tables and columns (eicu):
- allergy: allergyid, patientunitstayid, drugname, allergyname, allergytime
- cost: costid, uniquepid, patienthealthsystemstayid, eventtype, eventid, chargetime, cost
- diagnosis: diagnosisid, patientunitstayid, icd9code, diagnosisname, diagnosistime
- intakeoutput: intakeoutputid, patientunitstayid, cellpath, celllabel, cellvaluenumeric, intakeoutputtime
- lab: labid, patientunitstayid, labname, labresult, labresulttime
- medication: medicationid, patientunitstayid, drugname, dosage, routeadmin, drugstarttime, drugstoptime
- microlab: microlabid, patientunitstayid, culturesite, organism, culturetakentime
- patient: patientunitstayid, patienthealthsystemstayid, gender, age, ethnicity, hospitalid, wardid, admissionheight, hospitaladmitsource, hospitaldischargestatus, admissionweight, dischargeweight, uniquepid, hospitaladmittime, unitadmittime, unitdischargetime, hospitaldischargetime
- treatment: treatmentid, patientunitstayid, treatmentname, treatmenttime
- vitalperiodic: vitalperiodicid, patientunitstayid, temperature, sao2, heartrate, respiration, systemicsystolic, systemicdiastolic, systemicmean, observationtime

Check for:
- Wrong table names passed to LoadDB()
- Wrong column names passed to FilterDB() or GetValue()
- Wrong argument format for any API function
- SQL syntax or schema errors in SQLInterpreter()
- Any other obvious code errors

Always respond with EXACTLY [SUCCESS] or [ERROR] on the first line, followed by your
simulated result (SUCCESS) or the predicted error message (ERROR)."""

CompilerDebuggerAgent_System_Message = CompilerAgent_System_Message + """

If you find an error, also provide a suggested fix on a new line prefixed with:
"Suggested fix: " """

CompilerAgent_FewShot_Examples = """--- Example 1: Correct API code → SUCCESS ---
Question: was the fluticasone-salmeterol 250-50 mcg/dose in aepb prescribed to patient 035-2205 on their current hospital encounter?
Code:
patient_db = LoadDB('patient')
filtered_patient_db = FilterDB(patient_db, 'uniquepid=035-2205||hospitaldischargetime=null')
patientunitstayid = GetValue(filtered_patient_db, 'patientunitstayid')
medication_db = LoadDB('medication')
filtered_medication_db = FilterDB(medication_db, 'patientunitstayid={}||drugname=fluticasone-salmeterol 250-50 mcg/dose in aepb'.format(patientunitstayid))
if len(filtered_medication_db) > 0:
    answer = 1
else:
    answer = 0

[SUCCESS]
1

--- Example 2: Correct API code → SUCCESS ---
Question: what is the minimum hospital cost for a drug with a name called albumin 5% since 6 years ago?
Code:
date = Calendar('-6 year')
medication_db = LoadDB('medication')
filtered_medication_db = FilterDB(medication_db, 'drugname=albumin 5%')
patientunitstayid_list = GetValue(filtered_medication_db, 'patientunitstayid, list')
patient_db = LoadDB('patient')
filtered_patient_db = FilterDB(patient_db, 'patientunitstayid in {}'.format(patientunitstayid_list))
patienthealthsystemstayid_list = GetValue(filtered_patient_db, 'patienthealthsystemstayid, list')
cost_db = LoadDB('cost')
min_cost = 1e9
for patienthealthsystemstayid in patienthealthsystemstayid_list:
    filtered_cost_db = FilterDB(cost_db, 'patienthealthsystemstayid={}||chargetime>{}'.format(patienthealthsystemstayid, date))
    cost = GetValue(filtered_cost_db, 'cost, sum')
    if cost < min_cost:
        min_cost = cost
answer = min_cost

[SUCCESS]
245.89

--- Example 3: PLACEHOLDER — fill after running Approach 3 baseline ---
Question: <paste question here>
Code:
<paste last_code here>

[ERROR]
<paste last_error here>

--- Example 4: PLACEHOLDER — fill after running Approach 3 baseline ---
Question: <paste question here>
Code:
<paste last_code here>

[ERROR]
<paste last_error here>
"""
```

- [ ] **Step 3: Verify imports work**

```
python -c "from prompts_mimic import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples; print('OK')"
python -c "from prompts_eicu import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples; print('OK')"
```
Expected: `OK` for both.

- [ ] **Step 4: Commit**

```
git add EhrAgent/ehragent/prompts_mimic.py EhrAgent/ehragent/prompts_eicu.py
git commit -m "feat: add CompilerAgent system messages and few-shot templates to prompts files"
```

---

## Task 5: Update medagent.py (standard OpenAI + mode routing)

**Files:**
- Modify: `EhrAgent/ehragent/medagent.py`

- [ ] **Step 1: Replace `EhrAgent/ehragent/medagent.py` in full**

```python
# EhrAgent/ehragent/medagent.py
import time
from typing import Dict, List, Optional, Union, Callable, Literal
import logging
import json
from openai import OpenAI
from autogen.agentchat import Agent, UserProxyAgent, ConversableAgent
from termcolor import colored
import Levenshtein
from toolset_high import run_code
from compiler_agent import CompilerSuccessButExecFailed

logger = logging.getLogger(__name__)


class MedAgent(UserProxyAgent):
    def __init__(
        self,
        name: str,
        api_key: str,
        model: str,
        is_termination_msg=None,
        max_consecutive_auto_reply=None,
        human_input_mode="ALWAYS",
        function_map=None,
        code_execution_config=None,
        default_auto_reply="",
        llm_config=False,
        system_message="",
    ):
        super().__init__(
            name=name,
            system_message=system_message,
            is_termination_msg=is_termination_msg,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode=human_input_mode,
            function_map=function_map,
            code_execution_config=code_execution_config,
            llm_config=llm_config,
            default_auto_reply=default_auto_reply,
        )
        self._openai_client = OpenAI(api_key=api_key)
        self._model = model
        self.question = ""
        self.code = ""
        self.knowledge = ""
        self.mode = "baseline"         # "baseline" | "compiler_agent" | "newdebugger"
        self.compiler_agent = None
        self.compiler_debugger_agent = None

    def set_mode(self, mode, compiler_agent=None, compiler_debugger_agent=None):
        self.mode = mode
        self.compiler_agent = compiler_agent
        self.compiler_debugger_agent = compiler_debugger_agent

    def retrieve_knowledge(self, query):
        if self.dataset == "mimic_iii":
            from prompts_mimic import RetrKnowledge
        else:
            from prompts_eicu import RetrKnowledge
        query_message = RetrKnowledge.format(question=query)
        messages = [
            {"role": "system", "content": "You are an AI assistant that helps people find information."},
            {"role": "user", "content": query_message},
        ]
        patience = 2
        while patience > 0:
            patience -= 1
            try:
                response = self._openai_client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0,
                    max_tokens=800,
                )
                prediction = response.choices[0].message.content.strip()
                if prediction:
                    return prediction
            except Exception as e:
                print(e)
                time.sleep(30)
        return "Fail to retrieve related knowledge, please try again later."

    def retrieve_examples(self, query):
        levenshtein_dist = {}
        for i in range(len(self.memory)):
            question = self.memory[i]["question"]
            levenshtein_dist[i] = Levenshtein.distance(query, question)
        levenshtein_dist = sorted(levenshtein_dist.items(), key=lambda x: x[1])
        selected_indexes = [levenshtein_dist[i][0] for i in range(min(self.num_shots, len(levenshtein_dist)))]
        examples = []
        for i in selected_indexes:
            template = "Question: {}\nKnowledge:\n{}\nSolution:\n{}\n".format(
                self.memory[i]["question"], self.memory[i]["knowledge"], self.memory[i]["code"]
            )
            examples.append(template)
        return "\n".join(examples)

    def generate_init_message(self, **context):
        if self.dataset == "mimic_iii":
            from prompts_mimic import EHRAgent_Message_Prompt
        else:
            from prompts_eicu import EHRAgent_Message_Prompt
        self.question = context["message"]
        knowledge = self.retrieve_knowledge(context["message"])
        self.knowledge = knowledge
        examples = self.retrieve_examples(context["message"])
        return EHRAgent_Message_Prompt.format(
            examples=examples, knowledge=knowledge, question=context["message"]
        )

    def send(self, message, recipient, request_reply=None, silent=False):
        valid = self._append_oai_message(message, "assistant", recipient)
        if valid:
            recipient.receive(message, self, request_reply, silent)
        else:
            raise ValueError("Message can't be converted into a valid ChatCompletion message.")

    def initiate_chat(self, recipient, clear_history=True, silent=False, **context):
        self._prepare_chat(recipient, clear_history)
        self.send(self.generate_init_message(**context), recipient, silent=silent)

    def receive(self, message, sender, request_reply=None, silent=False):
        self._process_received_message(message, sender, silent)
        if request_reply is False or (request_reply is None and self.reply_at_receive[sender] is False):
            return
        reply = self.generate_reply(messages=self.chat_messages[sender], sender=sender)
        if reply is not None:
            self.send(reply, sender, silent=silent)

    def error_debugger(self, code, error_info):
        if self.dataset == "mimic_iii":
            from prompts_mimic import CodeDebugger
        else:
            from prompts_eicu import CodeDebugger
        query_message = CodeDebugger.format(
            question=self.question, code=code, error_info=error_info
        )
        messages = [
            {"role": "system", "content": "You are an AI assistant that helps people debug their code. Only list one most possible reason to the errors."},
            {"role": "user", "content": query_message},
        ]
        patience = 2
        while patience > 0:
            patience -= 1
            try:
                response = self._openai_client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0,
                    max_tokens=800,
                )
                prediction = response.choices[0].message.content.strip()
                if prediction:
                    return prediction
            except Exception as e:
                print(e)
                time.sleep(30)
        return "Fail to diagnose the reasons to the errors."

    def execute_function(self, func_call):
        func_name = func_call.get("name", "")
        func = self._function_map.get(func_name, None)
        is_exec_success = False

        if func is not None:
            input_string = self._format_json_str(func_call.get("arguments", "{}"))
            try:
                arguments = json.loads(input_string)
            except json.JSONDecodeError as e:
                arguments_string = func_call["arguments"].split(': "')[-1].split('", ')[0]
                arguments = {"cell": arguments_string}
                content = f"Error: {e}\n There might be compilation errors in the code. Please check the code and try again."

            if arguments is not None:
                print(colored(f"\n>>>>>>>> EXECUTING FUNCTION {func_name}...", "magenta"), flush=True)
                self.code = arguments["cell"]

                if self.mode == "compiler_agent":
                    try:
                        compiler_response = self.compiler_agent.evaluate(self.question, self.code)
                        if compiler_response.startswith("[ERROR]"):
                            error_msg = compiler_response[len("[ERROR]"):].strip()
                            reasons = self.error_debugger(self.code, error_msg)
                            content = error_msg + "\nPotential Reasons: " + reasons
                        else:
                            content = run_code(self.code)
                            if "error" in content.lower():
                                raise CompilerSuccessButExecFailed(content)
                            is_exec_success = True
                    except CompilerSuccessButExecFailed:
                        raise
                    except Exception as e:
                        content = f"Error: {e}"

                elif self.mode == "newdebugger":
                    try:
                        compiler_response = self.compiler_debugger_agent.evaluate(self.question, self.code)
                        if compiler_response.startswith("[ERROR]"):
                            content = compiler_response[len("[ERROR]"):].strip()
                        else:
                            content = run_code(self.code)
                            if "error" in content.lower():
                                raise CompilerSuccessButExecFailed(content)
                            is_exec_success = True
                    except CompilerSuccessButExecFailed:
                        raise
                    except Exception as e:
                        content = f"Error: {e}"

                else:  # baseline
                    try:
                        content = func(**arguments)
                        is_exec_success = True
                    except Exception as e:
                        content = f"Error: {e}"
                    if "error" in content or "Error" in content:
                        reasons = self.error_debugger(self.code, content)
                        content = content + "\nPotential Reasons: " + reasons
        else:
            content = f"Error: Function {func_name} not found."

        return is_exec_success, {
            "name": func_name,
            "role": "function",
            "content": str(content),
        }

    def update_memory(self, num_shots, memory):
        self.num_shots = num_shots
        self.memory = memory

    def register_dataset(self, dataset):
        self.dataset = dataset
```

- [ ] **Step 2: Verify the import chain works**

```
python -c "import sys; sys.path.insert(0,'EhrAgent'); from ehragent.medagent import MedAgent; print('OK')"
```

Or from inside `EhrAgent/ehragent/`:
```
python -c "from medagent import MedAgent; print('OK')"
```
Expected: `OK` (no import errors).

- [ ] **Step 3: Commit**

```
git add EhrAgent/ehragent/medagent.py
git commit -m "feat: MedAgent uses standard OpenAI client, supports compiler_agent/newdebugger/baseline modes"
```

---

## Task 6: Create pipeline.py — core infrastructure

**Files:**
- Create: `EhrAgent/ehragent/pipeline.py`
- Create: `EhrAgent/ehragent/tests/test_pipeline_utils.py`

- [ ] **Step 1: Write failing tests for utility functions**

```python
# EhrAgent/ehragent/tests/test_pipeline_utils.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest

# ── judge() tests ────────────────────────────────────────────────────────────

from pipeline import judge

def test_judge_exact_match():
    assert judge("the answer is tp", "tp") is True

def test_judge_true_false_normalization():
    assert judge("answer = True", "1") is True
    assert judge("answer = False", "0") is True

def test_judge_yes_no_normalization():
    assert judge("the answer is yes", "1") is True
    assert judge("answer: no", "0") is True

def test_judge_list_answer_all_present():
    assert judge("po, oral, PO", "po, oral") is True

def test_judge_wrong_answer():
    assert judge("the answer is 42", "tp") is False

def test_judge_trailing_zero():
    assert judge("answer: 3", "3.0") is True

# ── strip_examples() tests ───────────────────────────────────────────────────

from pipeline import strip_examples

def test_strip_examples_removes_everything_before_marker():
    msg = "LOTS OF EXAMPLES HERE\n(END OF EXAMPLES)\nQuestion: foo\nSolution: bar"
    result = strip_examples(msg)
    assert "LOTS OF EXAMPLES" not in result
    assert "Question: foo" in result

def test_strip_examples_no_marker_returns_unchanged():
    msg = "No examples section here"
    assert strip_examples(msg) == msg

def test_strip_examples_empty_string():
    assert strip_examples("") == ""

# ── make_output_dir() name format ────────────────────────────────────────────

from pipeline import _output_dir_name

def test_output_dir_name_baseline():
    name = _output_dir_name("mimic_iii", "baseline", 30, 42)
    assert "mimic_iii" in name
    assert "baseline" in name
    assert "n30" in name
    assert "seed42" in name

def test_output_dir_name_compiler_agent():
    name = _output_dir_name("eicu", "compiler_agent", 10, 99)
    assert "compiler_agent" in name
    assert "n10" in name
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_pipeline_utils.py -v
```
Expected: FAIL — `pipeline` module not found yet.

- [ ] **Step 3: Create `EhrAgent/ehragent/pipeline.py` with core utilities only**

```python
# EhrAgent/ehragent/pipeline.py
import os
import sys
import json
import random
import argparse
import time
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# EhrAgent root on path so exec'd CodeHeader can 'from tools import tabtools'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import autogen
from medagent import MedAgent
from config import openai_config, llm_config_list
from compiler_agent import CompilerAgent, CompilerDebuggerAgent, CompilerSuccessButExecFailed
import tools.tabtools as tabtools

DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "ehrsql-ehragent", "ehrsql-ehragent"
)
OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


# ── Utility functions (also imported by tests) ───────────────────────────────

def judge(pred, ans):
    old_flag = ans in pred
    if "True" in pred:
        pred = pred.replace("True", "1")
    else:
        pred = pred.replace("False", "0")
    if ans in ("False", "false"):
        ans = "0"
    if ans in ("True", "true"):
        ans = "1"
    if ans in ("No", "no"):
        ans = "0"
    if ans in ("Yes", "yes"):
        ans = "1"
    if ans in ("None", "none"):
        ans = "0"
    if ", " in ans:
        ans = ans.split(", ")
    if not isinstance(ans, list) and ans.endswith(".0"):
        ans = ans[:-2]
    if not isinstance(ans, list):
        ans = [ans]
    new_flag = all(a in pred for a in ans)
    return old_flag or new_flag


def strip_examples(message):
    marker = "(END OF EXAMPLES)"
    if marker in message:
        return message[message.index(marker) + len(marker):]
    return message


def _output_dir_name(dataset, mode, n, seed):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"run_{ts}_{dataset}_{mode}_n{n}_seed{seed}"


def parse_args():
    parser = argparse.ArgumentParser(description="EHRAgent pipeline")
    parser.add_argument("--dataset", required=True, choices=["mimic_iii", "eicu"])
    parser.add_argument("--dataset_path", default=None,
                        help="Path to ehrsql-ehragent folder (default: bundled dataset)")
    parser.add_argument("--n", type=int, default=30,
                        help="Number of questions to run (-1 = all)")
    parser.add_argument("--compiler_agent", action="store_true",
                        help="Approach 1: three-agent pipeline")
    parser.add_argument("--newdebugger", action="store_true",
                        help="Approach 2: combined compiler+debugger")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num_shots", type=int, default=4)
    args = parser.parse_args()
    if args.compiler_agent and args.newdebugger:
        parser.error("--compiler_agent and --newdebugger are mutually exclusive")
    if args.dataset_path is None:
        args.dataset_path = DEFAULT_DATASET_PATH
    return args


def get_api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set.\n"
            "Set it with: $env:OPENAI_API_KEY = 'sk-...'"
        )
    return key


if __name__ == "__main__":
    pass  # execution loop added in Task 7
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/test_pipeline_utils.py -v
```
Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add EhrAgent/ehragent/pipeline.py EhrAgent/ehragent/tests/test_pipeline_utils.py
git commit -m "feat: pipeline.py core utilities — judge(), strip_examples(), arg parsing, output dir naming"
```

---

## Task 7: Add Approach 3 baseline execution loop to pipeline.py

**Files:**
- Modify: `EhrAgent/ehragent/pipeline.py`

- [ ] **Step 1: Add question loading and baseline execution loop**

Replace the `if __name__ == "__main__": pass` block at the bottom of `pipeline.py` with the full implementation below. Add the helper functions above it:

```python
# ── Question loading ──────────────────────────────────────────────────────────

def load_questions(dataset_path, dataset, n, seed):
    data_file = os.path.join(dataset_path, dataset, "valid_preprocessed.json")
    with open(data_file) as f:
        contents = json.load(f)
    random.seed(seed)
    random.shuffle(contents)
    if n != -1:
        contents = contents[:n]
    return contents


# ── Per-question execution ────────────────────────────────────────────────────

def run_question(user_proxy, chatbot, item, long_term_memory, num_shots):
    question = item["template"]
    answer = item["answer"]
    gt_answer = answer if isinstance(answer, str) else ", ".join(answer)

    result = {
        "id": item.get("id", ""),
        "question": question,
        "ground_truth": gt_answer,
        "predicted_answer": "",
        "is_correct": False,
        "status": "incompleted",
        "num_tries": 0,
        "last_code": "",
        "last_error": "",
        "agent_trace": [],
    }

    try:
        user_proxy.update_memory(num_shots, long_term_memory)
        user_proxy.initiate_chat(chatbot, message=question)

        logs = user_proxy._oai_messages
        trace = []
        num_tries = 0
        last_code = ""
        last_error = ""

        for agent in list(logs.keys()):
            for msg in logs[agent]:
                if msg.get("content") is not None:
                    cleaned = strip_examples(str(msg["content"]))
                    trace.append(cleaned)
                    if "error" in cleaned.lower() or "Error" in cleaned:
                        last_error = cleaned
                elif msg.get("function_call"):
                    argums = msg["function_call"]["arguments"]
                    if isinstance(argums, dict) and "cell" in argums:
                        trace.append(argums["cell"])
                        last_code = argums["cell"]
                        num_tries += 1
                    else:
                        trace.append(str(argums))
                        last_code = str(argums)
                        num_tries += 1

        result["agent_trace"] = trace
        result["num_tries"] = max(num_tries, 1)
        result["last_code"] = last_code
        result["last_error"] = last_error

        # Extract predicted answer from trace
        logs_string = "\n".join(trace)
        term_idx = logs_string.rfind("TERMINATE")
        prediction_block = logs_string[:term_idx] if term_idx != -1 else logs_string

        is_correct = judge(prediction_block, gt_answer)
        result["predicted_answer"] = prediction_block.strip().split("\n")[-1]
        result["is_correct"] = is_correct
        result["status"] = "correct" if is_correct else "wrong"

    except CompilerSuccessButExecFailed as e:
        result["status"] = "incompleted"
        result["last_error"] = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: compiler said SUCCESS but real exec failed]")
    except Exception as e:
        result["status"] = "incompleted"
        result["last_error"] = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: exception] {e}")

    return result


# ── Output saving ─────────────────────────────────────────────────────────────

def save_outputs(output_dir, results):
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    errors = [r for r in results if r["status"] in ("wrong", "incompleted")]
    with open(os.path.join(output_dir, "errors.json"), "w") as f:
        json.dump(errors, f, indent=2)

    correct = sum(1 for r in results if r["status"] == "correct")
    wrong = sum(1 for r in results if r["status"] == "wrong")
    incompleted = sum(1 for r in results if r["status"] == "incompleted")
    total_tries = sum(r["num_tries"] for r in results)

    labels = ["Correct", "Wrong", "Incompleted", "Total Tries"]
    values = [correct, wrong, incompleted, total_tries]
    colors = ["#4CAF50", "#F44336", "#FF9800", "#2196F3"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.barh(labels, values, color=colors)
    ax.bar_label(bars, padding=3)
    ax.set_xlabel("Count")
    ax.set_title("EHRAgent Pipeline Results")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "summary_plot.png"), dpi=120)
    plt.close()

    print(f"\nResults saved to: {output_dir}")
    print(f"  Correct:     {correct}/{len(results)}")
    print(f"  Wrong:       {wrong}/{len(results)}")
    print(f"  Incompleted: {incompleted}/{len(results)}")
    print(f"  Total tries: {total_tries}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    api_key = get_api_key()

    # Configure tabtools paths for this dataset
    tabtools.configure(args.dataset_path, args.dataset)

    # Determine mode name for output folder
    if args.compiler_agent:
        mode = "compiler_agent"
    elif args.newdebugger:
        mode = "newdebugger"
    else:
        mode = "baseline"

    output_dir = os.path.join(OUTPUT_BASE, _output_dir_name(args.dataset, mode, args.n, args.seed))

    # Load questions deterministically
    questions = load_questions(args.dataset_path, args.dataset, args.n, args.seed)
    print(f"Running {len(questions)} questions | dataset={args.dataset} | mode={mode} | model={args.model}")

    # Build initial long-term memory from 4-shot examples
    if args.dataset == "mimic_iii":
        from prompts_mimic import EHRAgent_4Shots_Knowledge
    else:
        from prompts_eicu import EHRAgent_4Shots_Knowledge

    long_term_memory = []
    for item in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        item = item.split("Question:")[-1]
        question_part = item.split("\nKnowledge:\n")[0]
        rest = item.split("\nKnowledge:\n")[-1]
        knowledge_part = rest.split("\nSolution:")[0]
        code_part = rest.split("\nSolution:")[-1]
        long_term_memory.append({
            "question": question_part,
            "knowledge": knowledge_part,
            "code": code_part,
        })

    # Build autogen config
    cfg = openai_config(args.model, api_key)
    config_list = [cfg]
    llm_cfg = llm_config_list(args.seed, config_list)

    # Build chatbot (Coding Agent) — unchanged from original
    chatbot = autogen.agentchat.AssistantAgent(
        name="chatbot",
        system_message=(
            "For coding tasks, only use the functions you have been provided with. "
            "Reply TERMINATE when the task is done. Save the answers to the questions "
            "in the variable 'answer'. Please only generate the code."
        ),
        llm_config=llm_cfg,
    )

    # Build MedAgent (executor/proxy)
    user_proxy = MedAgent(
        name="user_proxy",
        api_key=api_key,
        model=args.model,
        is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={"work_dir": "coding"},
    )
    user_proxy.register_function(function_map={"python": run_code})
    user_proxy.register_dataset(args.dataset)

    # Attach compiler agents if needed
    if args.compiler_agent:
        from prompts_mimic import (
            CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        ) if args.dataset == "mimic_iii" else (
            None, None
        )
        if args.dataset == "mimic_iii":
            from prompts_mimic import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        else:
            from prompts_eicu import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples

        ca = CompilerAgent(
            api_key=api_key, model=args.model, dataset=args.dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerAgent_System_Message,
        )
        user_proxy.set_mode("compiler_agent", compiler_agent=ca)

    elif args.newdebugger:
        if args.dataset == "mimic_iii":
            from prompts_mimic import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples
        else:
            from prompts_eicu import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples

        cda = CompilerDebuggerAgent(
            api_key=api_key, model=args.model, dataset=args.dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerDebuggerAgent_System_Message,
        )
        user_proxy.set_mode("newdebugger", compiler_debugger_agent=cda)
    # else: mode stays "baseline"

    # Run all questions
    results = []
    start_time = time.time()

    for i, item in enumerate(questions):
        print(f"\n[{i+1}/{len(questions)}] {item['template'][:80]}...")
        result = run_question(user_proxy, chatbot, item, long_term_memory, args.num_shots)
        result["id"] = item.get("id", str(i))
        results.append(result)

        # Update long-term memory on correct answers (same as original)
        if result["status"] == "correct" and result["last_code"]:
            long_term_memory.append({
                "question": item["template"],
                "knowledge": user_proxy.knowledge,
                "code": result["last_code"],
            })

        print(f"  → {result['status'].upper()} | tries={result['num_tries']}")

    elapsed = time.time() - start_time
    print(f"\nTotal time: {elapsed:.1f}s")
    save_outputs(output_dir, results)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Fix the clunky conditional import block**

The compiler_agent import block in `main()` has a redundant pattern. Replace just that block with:

```python
    if args.compiler_agent:
        if args.dataset == "mimic_iii":
            from prompts_mimic import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        else:
            from prompts_eicu import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        ca = CompilerAgent(
            api_key=api_key, model=args.model, dataset=args.dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerAgent_System_Message,
        )
        user_proxy.set_mode("compiler_agent", compiler_agent=ca)
    elif args.newdebugger:
        if args.dataset == "mimic_iii":
            from prompts_mimic import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples
        else:
            from prompts_eicu import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples
        cda = CompilerDebuggerAgent(
            api_key=api_key, model=args.model, dataset=args.dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerDebuggerAgent_System_Message,
        )
        user_proxy.set_mode("newdebugger", compiler_debugger_agent=cda)
```

- [ ] **Step 3: Run all tests to confirm nothing broke**

```
python -m pytest tests/ -v
```
Expected: all previous tests PASS.

- [ ] **Step 4: Verify the pipeline can be imported without errors**

```
python -c "from pipeline import main, load_questions, run_question, save_outputs; print('OK')"
```
Expected: `OK`.

- [ ] **Step 5: Create the outputs directory**

```
mkdir -p EhrAgent/ehragent/outputs
```

- [ ] **Step 6: Commit**

```
git add EhrAgent/ehragent/pipeline.py
git commit -m "feat: complete pipeline.py — baseline execution loop, output saving, bar chart"
```

---

## Task 8: Smoke test the baseline pipeline end-to-end

This task verifies the whole system works before adding API costs of Approaches 1 & 2.

- [ ] **Step 1: Set your API key**

In PowerShell:
```powershell
$env:OPENAI_API_KEY = "sk-..."
```

- [ ] **Step 2: Run baseline on 2 questions to verify it works**

From `EhrAgent/ehragent/`:
```
python pipeline.py --dataset mimic_iii --n 2 --seed 42
```

Expected output:
```
Running 2 questions | dataset=mimic_iii | mode=baseline | model=gpt-4o-mini
[1/2] <question text>...
  → CORRECT/WRONG/INCOMPLETED | tries=N
[2/2] <question text>...
  → CORRECT/WRONG/INCOMPLETED | tries=N
Total time: Xs
Results saved to: outputs/run_<timestamp>_mimic_iii_baseline_n2_seed42
  Correct:     N/2
  ...
```

- [ ] **Step 3: Verify output files exist and have correct structure**

Open `outputs/run_.../results.json` — confirm each entry has: `id`, `question`, `ground_truth`, `predicted_answer`, `status`, `num_tries`, `last_code`, `last_error`, `agent_trace`.

Open `outputs/run_.../errors.json` — confirm it only contains `wrong` or `incompleted` entries with `last_code` and `last_error` populated.

Open `outputs/run_.../summary_plot.png` — confirm the bar chart renders with 4 bars.

- [ ] **Step 4: Verify agent_trace has no examples section**

In `results.json`, look at `agent_trace[0]` — confirm it starts with `Knowledge:` or similar, not with `Question: What is the maximum total...` (the first few-shot example). The `(END OF EXAMPLES)` marker and everything before it must be stripped.

- [ ] **Step 5: Run baseline on 30 questions (full comparison set)**

```
python pipeline.py --dataset mimic_iii --n 30 --seed 42
```

This is your Approach 3 baseline run. Keep the output folder — you will compare against it.

- [ ] **Step 6: Inspect errors.json and identify 2 error examples for the compiler prompt**

Open `outputs/run_.../errors.json`. Find 2 entries where:
- `last_code` is non-empty
- `last_error` contains a clear schema error (wrong column name, wrong table, bad argument)
- The error message is concise (under 3 lines)

Copy each entry's `question`, `last_code`, and `last_error` into the PLACEHOLDER sections in `prompts_mimic.py`'s `CompilerAgent_FewShot_Examples` (Examples 3 and 4).

- [ ] **Step 7: Commit baseline results and updated prompts**

```
git add EhrAgent/ehragent/prompts_mimic.py
git commit -m "feat: fill in real ERROR few-shot examples in CompilerAgent prompt from baseline run"
```

---

## Task 9: Verify Approach 1 (--compiler_agent) and Approach 2 (--newdebugger)

- [ ] **Step 1: Run Approach 1 on the same 30 questions**

```
python pipeline.py --dataset mimic_iii --n 30 --seed 42 --compiler_agent
```

Same seed → same 30 questions as baseline. Compare `summary_plot.png` between this run and the baseline.

- [ ] **Step 2: Run Approach 2 on the same 30 questions**

```
python pipeline.py --dataset mimic_iii --n 30 --seed 42 --newdebugger
```

- [ ] **Step 3: Verify ethical property holds in Approaches 1 & 2**

Open `results.json` for any INCOMPLETED entry from Approaches 1 or 2. Confirm `agent_trace` does NOT contain any real patient data values or Python tracebacks from `run_code()` — it should end with `[INCOMPLETED: compiler said SUCCESS but real exec failed]` or similar.

- [ ] **Step 4: Run eicu dataset as sanity check**

```
python pipeline.py --dataset eicu --n 5 --seed 42
```

Expected: runs without errors, creates `outputs/run_..._eicu_baseline_n5_seed42/`.

- [ ] **Step 5: Commit**

```
git add .
git commit -m "feat: verified Approaches 1, 2, 3 run end-to-end on mimic_iii and eicu"
```

---

## Self-Review Against Spec

**Spec Section 3 (Three Approaches):** Tasks 6–9 implement all three modes. `execute_function()` in Task 5 routes correctly. ✓

**Spec Section 5 (Pipeline Args):** `parse_args()` in Task 6 has all flags. `get_api_key()` reads `OPENAI_API_KEY`. `DEFAULT_DATASET_PATH` set. `--n` defaults to 30. Mutual exclusion enforced. ✓

**Spec Section 6 (OpenAI Config):** Task 2 replaces Azure config. Task 5 removes dead v0.x assignments, uses single `OpenAI(api_key=...)` client. `cache_seed` preserved. ✓

**Spec Section 7 (TabTools):** Task 1 adds `configure()`, both mimic and eicu dicts, `sql_interpreter` and `date_calculator` use dynamic db path. ✓

**Spec Section 8 (Compiler Prompt):** Task 4 adds system messages and few-shot templates to both prompt files. ERROR placeholders filled in Task 8. ✓

**Spec Section 9 (MedAgent):** Task 5 implements full mode routing including `CompilerSuccessButExecFailed` raise. ✓

**Spec Section 10 (Output):** Task 7 implements `results.json` (with `last_code`, `last_error`), `errors.json` (wrong+incompleted only), `summary_plot.png` (4 bars). `strip_examples()` applied to agent_trace. ✓

**Spec Section 11 (Build Order):** Tasks proceed in order: tabtools → config/toolset → compiler → prompts → medagent → pipeline core → baseline loop → smoke test → approaches 1&2. ✓

**Spec Section 12 (run_code() unchanged):** `run_code()` in `toolset_high.py` signature and logic unchanged — only removed the `prompts_mimic` import. ✓
