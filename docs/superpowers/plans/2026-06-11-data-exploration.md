# Data Exploration — ReFoRCE Schema Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `EhrAgent/ehragent/data_exploration/` — a self-contained 6-condition benchmark (2 pipelines × 3 schema variants) with a ReFoRCE-inspired schema explorer that probes a SQLite EHR database and auto-generates schema strings, plus comparison graphs across all conditions.

**Architecture:** A `SchemaAwareMedAgent` subclass overrides only `generate_init_message` to inject a parameterized schema string, leaving all autogen/MedAgent logic untouched. Parameterized prompt templates in `prompts/` swap schema in/out of both the coding agent's initial message and the compiler agent's system message. The `SchemaExplorer` calls `claude-haiku-4-5-20251001` to cluster tables, probe columns iteratively via SQLite, and synthesize a schema string in the dataset format.

**Tech Stack:** Python 3.10+, anthropic SDK, openai SDK, pyautogen, matplotlib, sqlite3 (stdlib), unittest.mock (stdlib)

**HARD CONSTRAINTS:**
- Do NOT modify any file outside `data_exploration/`
- No API keys hardcoded — all from `os.environ`
- Do NOT modify the coding agent (autogen AssistantAgent) behavior

---

## File Map

| File | Responsibility |
|------|----------------|
| `data_exploration/config.py` | Read API keys from env; raise immediately if missing |
| `data_exploration/pipeline/judge.py` | `judge(pred, ans)` — verbatim copy from `run_pipeline.py` |
| `data_exploration/schema_explorer/sql_executor.py` | `SQLExecutor(db_path).execute(sql)` — returns `(result_dict, error_str)` |
| `data_exploration/schema_explorer/prompts.py` | All LLM prompts used by the explorer |
| `data_exploration/schema_explorer/explorer.py` | `SchemaExplorer(db_path, api_key)` — 3-stage table discovery, column probing, compression |
| `data_exploration/prompts/mimic_iii.py` | `get_coding_agent_prompt(schema_str, ...)` and `get_compiler_system_message(schema_str)` |
| `data_exploration/prompts/eicu.py` | Same interface, eICU-specific content |
| `data_exploration/pipeline/agents.py` | `SchemaAwareMedAgent`, `build_agents(pipeline_type, schema_str, ...)` |
| `data_exploration/pipeline/runner.py` | `run_question(user_proxy, chatbot, item, memory)` — returns result dict |
| `data_exploration/run_exploration.py` | CLI entry point: 6-condition loop, trace writing, graphs, summary |
| `data_exploration/tests/test_judge.py` | Unit tests for judge() |
| `data_exploration/tests/test_sql_executor.py` | Unit tests for SQLExecutor with in-memory SQLite |
| `data_exploration/tests/test_explorer.py` | Unit tests for SchemaExplorer with mocked Anthropic client |
| `data_exploration/tests/test_prompts.py` | Unit tests for parameterized prompt builders |

**Sys-path note:** `agents.py` adds two paths at import time:
- `EhrAgent/` (for `tools.tabtools`)
- `EhrAgent/ehragent/` (for `medagent`, `compiler_agent`, `toolset_high`, `prompts_mimic`, `prompts_eicu`)

All imports within `data_exploration/` use paths relative to `data_exploration/` (which Python adds automatically when running `run_exploration.py`).

---

## Task 1: Scaffold folder structure + `config.py`

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/config.py`
- Create: `EhrAgent/ehragent/data_exploration/outputs/.gitkeep`
- Create: `EhrAgent/ehragent/data_exploration/__init__.py` (empty)
- Create: `EhrAgent/ehragent/data_exploration/pipeline/__init__.py` (empty)
- Create: `EhrAgent/ehragent/data_exploration/schema_explorer/__init__.py` (empty)
- Create: `EhrAgent/ehragent/data_exploration/prompts/__init__.py` (empty)
- Create: `EhrAgent/ehragent/data_exploration/tests/__init__.py` (empty)

- [ ] **Step 1: Create the directory tree**

```bash
cd EhrAgent/ehragent
mkdir -p data_exploration/pipeline
mkdir -p data_exploration/schema_explorer
mkdir -p data_exploration/prompts
mkdir -p data_exploration/tests
mkdir -p data_exploration/outputs
touch data_exploration/__init__.py
touch data_exploration/pipeline/__init__.py
touch data_exploration/schema_explorer/__init__.py
touch data_exploration/prompts/__init__.py
touch data_exploration/tests/__init__.py
touch data_exploration/outputs/.gitkeep
```

- [ ] **Step 2: Write `config.py`**

```python
# EhrAgent/ehragent/data_exploration/config.py
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
```

- [ ] **Step 3: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/
git commit -m "feat(data_exploration): scaffold folder structure and config"
```

---

## Task 2: `pipeline/judge.py` + tests

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/pipeline/judge.py`
- Create: `EhrAgent/ehragent/data_exploration/tests/test_judge.py`

- [ ] **Step 1: Write the failing test**

```python
# EhrAgent/ehragent/data_exploration/tests/test_judge.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pipeline.judge import judge


def test_exact_match():
    assert judge("The answer is 42", "42") is True


def test_boolean_true():
    assert judge("True", "1") is True


def test_boolean_false():
    assert judge("False", "0") is True


def test_yes_no():
    assert judge("yes", "1") is True
    assert judge("no", "0") is True


def test_none_answer():
    assert judge("0", "None") is True


def test_list_answer():
    assert judge("penicillin, amoxicillin", "penicillin, amoxicillin") is True


def test_trailing_zero():
    assert judge("3.0", "3") is True


def test_no_match():
    assert judge("The answer is 5", "42") is False
```

- [ ] **Step 2: Run test — expect ImportError (module not created yet)**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_judge.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'judge' from 'pipeline.judge'`

- [ ] **Step 3: Write `judge.py`** (verbatim copy from `run_pipeline.py:86-108`)

```python
# EhrAgent/ehragent/data_exploration/pipeline/judge.py


def judge(pred, ans):
    old_flag = ans in pred
    if "True" in pred:
        pred = pred.replace("True", "1")
    else:
        pred = pred.replace("False", "0")
    if "yes" in pred.lower():
        pred = pred.lower().replace("yes", "1")
    if "no" in pred.lower() and "1" not in pred:
        pred = pred.lower().replace("no", "0")
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
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_judge.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/pipeline/judge.py EhrAgent/ehragent/data_exploration/tests/test_judge.py
git commit -m "feat(data_exploration): add judge function and tests"
```

---

## Task 3: `schema_explorer/sql_executor.py` + tests

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/schema_explorer/sql_executor.py`
- Create: `EhrAgent/ehragent/data_exploration/tests/test_sql_executor.py`

- [ ] **Step 1: Write the failing test**

```python
# EhrAgent/ehragent/data_exploration/tests/test_sql_executor.py
import sys, os, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from schema_explorer.sql_executor import SQLExecutor


def _make_db():
    """Create a temp SQLite db with one table for testing."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(f.name)
    conn.execute("CREATE TABLE patients (id INTEGER, name TEXT, age INTEGER)")
    conn.execute("INSERT INTO patients VALUES (1, 'Alice', 30)")
    conn.execute("INSERT INTO patients VALUES (2, 'Bob', 25)")
    conn.commit()
    conn.close()
    return f.name


def test_successful_query():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT * FROM patients")
    assert error is None
    assert result["columns"] == ["id", "name", "age"]
    assert len(result["rows"]) == 2
    assert result["rows"][0] == [1, "Alice", 30]


def test_pragma_query():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("PRAGMA table_info(patients)")
    assert error is None
    assert result["columns"] == ["cid", "name", "type", "notnull", "dflt_value", "pk"]
    assert any(row[1] == "id" for row in result["rows"])


def test_list_tables():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT name FROM sqlite_master WHERE type='table'")
    assert error is None
    table_names = [row[0] for row in result["rows"]]
    assert "patients" in table_names


def test_bad_sql_returns_error():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT * FROM nonexistent_table")
    assert result is None
    assert error is not None
    assert "nonexistent_table" in error.lower() or "no such table" in error.lower()


def test_row_limit():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT * FROM patients", row_limit=1)
    assert error is None
    assert len(result["rows"]) == 1
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_sql_executor.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'SQLExecutor'`

- [ ] **Step 3: Write `sql_executor.py`**

```python
# EhrAgent/ehragent/data_exploration/schema_explorer/sql_executor.py
import sqlite3


class SQLExecutor:
    def __init__(self, db_path):
        self.db_path = db_path

    def execute(self, sql, row_limit=20):
        """Execute SQL against the SQLite db.

        Returns (result_dict, None) on success or (None, error_str) on failure.
        result_dict = {"columns": [...], "rows": [[...], ...]}
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchmany(row_limit)
            col_names = (
                [desc[0] for desc in cursor.description]
                if cursor.description
                else []
            )
            conn.close()
            return {"columns": col_names, "rows": [list(r) for r in rows]}, None
        except Exception as e:
            return None, str(e)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_sql_executor.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/schema_explorer/sql_executor.py EhrAgent/ehragent/data_exploration/tests/test_sql_executor.py
git commit -m "feat(data_exploration): add SQLExecutor with tests"
```

---

## Task 4: `schema_explorer/prompts.py`

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/schema_explorer/prompts.py`

No tests — these are static strings verified by the explorer tests in Task 5.

- [ ] **Step 1: Write `prompts.py`**

```python
# EhrAgent/ehragent/data_exploration/schema_explorer/prompts.py

CLUSTER_TABLES = """You are analyzing an EHR (Electronic Health Record) SQLite database.
Given these table names, identify clusters of tables that share the same schema structure
(e.g., partitioned by year, region, or category). Tables in the same cluster can be
represented by a single schema exploration.

Table names: {table_list}

Return ONLY valid JSON with no markdown fences:
{{
  "clusters": {{
    "cluster_label": {{
      "members": ["table_a", "table_b"],
      "representative": "table_a"
    }}
  }},
  "singletons": ["table_c", "table_d"]
}}

Rules:
- If no tables form natural clusters, put all in "singletons"
- Each table must appear exactly once across clusters and singletons
- Pick the first alphabetically as representative when tables are similar"""

DECIDE_FOLLOWUP = """You are exploring the schema of a SQLite EHR database table to understand
what it contains, without access to real patient data.

Table: {table}

PRAGMA table_info result (columns and declared types):
{pragma_result}

Sample rows (SELECT * LIMIT 3):
{sample_result}

Do any columns need a follow-up query to understand their values or relationships?
Examples of columns that need follow-up: coded IDs that reference other tables (ITEMID, ICD9_CODE),
columns with unclear ranges, or columns with complex values.

Return ONLY valid JSON, no markdown fences:
{{
  "needs_followup": true,
  "followup_queries": [
    {{"purpose": "short description", "sql": "SELECT ..."}}
  ]
}}

Limit to at most 2 follow-up queries. If nothing needs follow-up:
{{
  "needs_followup": false,
  "followup_queries": []
}}"""

REWRITE_QUERY = """A SQLite query for exploring an EHR database schema failed.

Failed SQL: {sql}
Error message: {error}

This is SQLite — use PRAGMA syntax, not INFORMATION_SCHEMA. Rewrite the query to fix the error.
Return ONLY the corrected SQL query, nothing else."""

SYNTHESIZE_SCHEMA = """You are generating a database schema description for an EHR coding agent.
The agent uses this description to write Python code that queries the database.

Below is the raw exploration data from probing the SQLite database.

Fully explored tables (PRAGMA + sample data):
{exploration_json}

Tables NOT fully explored (cluster members; share schema with their representative):
{skipped_tables}

Generate a schema description in EXACTLY this format — one line per table, columns in parentheses,
plus a one-sentence description on the next line:

Available tables and columns:
- table_name: COL1 (TYPE), COL2 (TYPE), COL3 (TYPE)
  Description: This table contains [what it stores, inferred from column names and sample data].

Rules:
- Use UPPERCASE for column names (as they appear in the data)
- Use the SQLite declared type in parentheses; use TEXT if unknown
- List all columns from PRAGMA for fully explored tables
- For skipped tables, include a line: - table_name: (see representative TABLE_X for schema)
- Do not invent columns; only use what the PRAGMA showed
- Keep each description to one sentence"""
```

- [ ] **Step 2: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/schema_explorer/prompts.py
git commit -m "feat(data_exploration): add schema explorer LLM prompts"
```

---

## Task 5: `schema_explorer/explorer.py` + tests

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/schema_explorer/explorer.py`
- Create: `EhrAgent/ehragent/data_exploration/tests/test_explorer.py`

- [ ] **Step 1: Write the failing tests**

```python
# EhrAgent/ehragent/data_exploration/tests/test_explorer.py
import sys, os, sqlite3, tempfile, json
from unittest.mock import MagicMock, patch, call
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from schema_explorer.explorer import SchemaExplorer


def _make_ehr_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(f.name)
    conn.execute("CREATE TABLE patients (SUBJECT_ID INTEGER, GENDER TEXT, DOB TEXT)")
    conn.execute("CREATE TABLE admissions (HADM_ID INTEGER, SUBJECT_ID INTEGER, ADMITTIME TEXT)")
    conn.execute("INSERT INTO patients VALUES (1, 'M', '1980-01-01')")
    conn.execute("INSERT INTO admissions VALUES (100, 1, '2020-05-01')")
    conn.commit()
    conn.close()
    return f.name


def _make_mock_anthropic(responses):
    """responses: list of strings, returned in order from client.messages.create."""
    mock_client = MagicMock()
    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    call_count = [0]

    def create_side_effect(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        text = responses[idx % len(responses)]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=text)]
        mock_response.usage = mock_usage
        return mock_response

    mock_client.messages.create.side_effect = create_side_effect
    return mock_client


def test_stage1_discovers_tables():
    db_path = _make_ehr_db()
    cluster_response = json.dumps({
        "clusters": {},
        "singletons": ["patients", "admissions"]
    })
    followup_response = json.dumps({"needs_followup": False, "followup_queries": []})
    schema_response = "Available tables and columns:\n- patients: SUBJECT_ID (INTEGER), GENDER (TEXT), DOB (TEXT)\n  Description: Stores patient demographics."

    mock_client = _make_mock_anthropic([cluster_response, followup_response, followup_response, schema_response])

    explorer = SchemaExplorer(db_path=db_path, api_key="fake")
    explorer.client = mock_client

    schema_str, trace = explorer.explore()

    assert "patients" in trace["stage_1"]["all_tables"]
    assert "admissions" in trace["stage_1"]["all_tables"]


def test_stage3_returns_schema_string():
    db_path = _make_ehr_db()
    cluster_response = json.dumps({
        "clusters": {},
        "singletons": ["patients", "admissions"]
    })
    followup_response = json.dumps({"needs_followup": False, "followup_queries": []})
    schema_response = "Available tables and columns:\n- patients: SUBJECT_ID (INTEGER)\n  Description: Patient table."

    mock_client = _make_mock_anthropic([cluster_response, followup_response, followup_response, schema_response])

    explorer = SchemaExplorer(db_path=db_path, api_key="fake")
    explorer.client = mock_client

    schema_str, trace = explorer.explore()

    assert "patients" in schema_str
    assert "stage_3" in trace
    assert trace["tokens_used"] > 0
    assert trace["api_calls"] > 0


def test_bad_query_retried():
    db_path = _make_ehr_db()
    cluster_response = json.dumps({
        "clusters": {},
        "singletons": ["patients"]
    })
    followup_response = json.dumps({"needs_followup": False, "followup_queries": []})
    schema_response = "Available tables and columns:\n- patients: SUBJECT_ID (INTEGER)\n  Description: Patients."

    mock_client = _make_mock_anthropic([
        cluster_response,
        "SELECT * FROM patients LIMIT 3",  # rewrite response
        followup_response,
        schema_response,
    ])

    explorer = SchemaExplorer(db_path=db_path, api_key="fake")
    explorer.client = mock_client

    # Patch execute to fail on first LIMIT call, succeed on retry
    original_execute = explorer.executor.execute
    call_count = [0]

    def patched_execute(sql, row_limit=20):
        call_count[0] += 1
        if "LIMIT 3" in sql and call_count[0] == 2:
            return None, "no such table: bad_table"
        return original_execute(sql, row_limit)

    explorer.executor.execute = patched_execute
    schema_str, trace = explorer.explore()
    # Should complete without raising
    assert trace is not None
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_explorer.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'SchemaExplorer'`

- [ ] **Step 3: Write `explorer.py`**

```python
# EhrAgent/ehragent/data_exploration/schema_explorer/explorer.py
import json
import anthropic

from .sql_executor import SQLExecutor
from . import prompts as P

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_RETRIES = 3


class SchemaExplorer:
    """Probes a SQLite EHR database and synthesizes a schema string using claude-haiku."""

    def __init__(self, db_path, api_key, model=HAIKU_MODEL):
        self.executor = SQLExecutor(db_path)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.tokens_used = 0
        self.api_calls = 0

    def explore(self):
        """Run all 3 stages. Returns (schema_str, trace_dict)."""
        self.tokens_used = 0
        self.api_calls = 0
        trace = {}

        all_tables, clusters, representatives = self._stage1(trace)
        column_data = self._stage2(representatives, trace)
        schema_str = self._stage3(clusters, column_data, trace)

        trace["tokens_used"] = self.tokens_used
        trace["api_calls"] = self.api_calls
        return schema_str, trace

    # ── LLM helper ────────────────────────────────────────────────────────────

    def _llm(self, prompt):
        self.api_calls += 1
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        self.tokens_used += response.usage.input_tokens + response.usage.output_tokens
        return response.content[0].text

    # ── Stage 1: Table discovery + clustering ──────────────────────────────────

    def _stage1(self, trace):
        result, error = self.executor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        if error or result is None:
            raise RuntimeError(f"Cannot list tables: {error}")

        all_tables = [row[0] for row in result["rows"]]

        prompt = P.CLUSTER_TABLES.format(table_list=", ".join(all_tables))
        response_text = self._llm(prompt)

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            parsed = {"clusters": {}, "singletons": all_tables}

        clusters = {}
        representatives = {}

        for label, info in parsed.get("clusters", {}).items():
            members = info.get("members", [])
            rep = info.get("representative") or (members[0] if members else None)
            if rep:
                clusters[label] = members
                representatives[label] = rep

        for singleton in parsed.get("singletons", []):
            clusters[singleton] = [singleton]
            representatives[singleton] = singleton

        trace["stage_1"] = {
            "all_tables": all_tables,
            "clusters": clusters,
            "representative_tables": list(representatives.values()),
            "llm_prompt": prompt,
            "llm_response": response_text,
        }
        return all_tables, clusters, representatives

    # ── Stage 2: Column probing ────────────────────────────────────────────────

    def _stage2(self, representatives, trace):
        column_data = {}
        trace["stage_2"] = []

        for cluster_label, rep_table in representatives.items():
            table_trace = {"table": rep_table, "cluster": cluster_label, "queries": []}

            pragma_result, _ = self._probe(f"PRAGMA table_info({rep_table})", table_trace)
            sample_result, _ = self._probe(f"SELECT * FROM {rep_table} LIMIT 3", table_trace)

            followup_queries = self._decide_followup(rep_table, pragma_result, sample_result, table_trace)

            followup_results = []
            for fq in followup_queries:
                fq_result, fq_error = self._probe(fq["sql"], table_trace)
                followup_results.append({
                    "purpose": fq["purpose"],
                    "result": fq_result,
                    "error": fq_error,
                })

            column_data[rep_table] = {
                "pragma": pragma_result,
                "sample": sample_result,
                "followups": followup_results,
            }
            trace["stage_2"].append(table_trace)

        return column_data

    def _probe(self, sql, table_trace):
        """Execute SQL, retrying with LLM rewrite on error. Returns (result, error)."""
        current_sql = sql
        for attempt in range(MAX_RETRIES):
            result, error = self.executor.execute(current_sql)
            entry = {
                "attempt": attempt + 1,
                "sql": current_sql,
                "result": result,
                "error": error,
            }
            table_trace["queries"].append(entry)

            if result is not None:
                return result, None

            if attempt < MAX_RETRIES - 1:
                rewrite_prompt = P.REWRITE_QUERY.format(sql=current_sql, error=error)
                rewritten = self._llm(rewrite_prompt).strip()
                entry["rewrite_prompt"] = rewrite_prompt
                entry["rewritten_to"] = rewritten
                current_sql = rewritten

        return None, error

    def _decide_followup(self, table, pragma_result, sample_result, table_trace):
        pragma_str = json.dumps(pragma_result, default=str) if pragma_result else "unavailable"
        sample_str = json.dumps(sample_result, default=str) if sample_result else "unavailable"

        prompt = P.DECIDE_FOLLOWUP.format(
            table=table,
            pragma_result=pragma_str,
            sample_result=sample_str,
        )
        response_text = self._llm(prompt)
        table_trace["followup_decision"] = {"prompt": prompt, "response": response_text}

        try:
            parsed = json.loads(response_text)
            if parsed.get("needs_followup"):
                return parsed.get("followup_queries", [])[:2]
        except json.JSONDecodeError:
            pass
        return []

    # ── Stage 3: Schema synthesis ──────────────────────────────────────────────

    def _stage3(self, clusters, column_data, trace):
        explored = set(column_data.keys())
        skipped = []
        for label, members in clusters.items():
            for m in members:
                if m not in explored:
                    skipped.append(m)

        exploration_json = json.dumps(column_data, indent=2, default=str)
        skipped_str = ", ".join(skipped) if skipped else "(none)"

        prompt = P.SYNTHESIZE_SCHEMA.format(
            exploration_json=exploration_json,
            skipped_tables=skipped_str,
        )
        schema_str = self._llm(prompt)

        trace["stage_3"] = {
            "prompt": prompt,
            "schema_output": schema_str,
            "skipped_tables": skipped,
        }
        return schema_str
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_explorer.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/schema_explorer/explorer.py EhrAgent/ehragent/data_exploration/tests/test_explorer.py
git commit -m "feat(data_exploration): add SchemaExplorer with 3-stage pipeline"
```

---

## Task 6: `prompts/mimic_iii.py` + tests

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/prompts/mimic_iii.py`
- Create: `EhrAgent/ehragent/data_exploration/tests/test_prompts.py`

- [ ] **Step 1: Write failing tests**

```python
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
    assert "[SUCCESS]" in msg or "SUCCESS" in msg


def test_compiler_system_message_no_schema():
    msg = get_compiler_system_message("")
    assert "No schema provided" in msg
    assert "API syntax only" in msg


def test_debugger_system_message_adds_fix_prefix():
    msg = get_compiler_debugger_system_message("")
    assert "Suggested fix:" in msg


def test_few_shot_examples_not_empty():
    assert len(CompilerAgent_FewShot_Examples) > 100


def test_loaddb_table_list_present_in_prompt():
    prompt = get_coding_agent_prompt(schema_str="", examples="", knowledge="", question="Q?")
    assert "admissions" in prompt
    assert "LoadDB" in prompt
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_prompts.py -v 2>&1 | head -10
```

- [ ] **Step 3: Write `prompts/mimic_iii.py`**

```python
# EhrAgent/ehragent/data_exploration/prompts/mimic_iii.py
"""
Schema-parameterized prompt templates for MIMIC-III.

All builder functions accept schema_str:
  ""                    → no schema (conditions A/D)
  DATASET_SCHEMA_*      → dataset schema (conditions B/E)
  <explorer output>     → ReFoRCE schema (conditions C/F)
"""

DATASET_SCHEMA_NARRATIVE = (
    "(1) Tables are linked by identifiers which usually have the suffix 'ID'. "
    "For example, SUBJECT_ID refers to a unique patient, HADM_ID refers to a unique "
    "admission to the hospital, and ICUSTAY_ID refers to a unique admission to an "
    "intensive care unit.\n"
    "(2) Charted events such as notes, laboratory tests, and fluid balance are stored "
    "in a series of 'events' tables. For example the outputevents table contains all "
    "measurements related to output for a given patient, while the labevents table "
    "contains laboratory test results for a patient.\n"
    "(3) Tables prefixed with 'd_' are dictionary tables and provide definitions for "
    "identifiers. For example, every row of chartevents is associated with a single "
    "ITEMID which represents the concept measured, but it does not contain the actual "
    "name of the measurement. By joining chartevents and d_items on ITEMID, it is "
    "possible to identify the concept represented by a given ITEMID.\n"
    "(4) For the databases, four of them are used to define and track patient stays: "
    "admissions, patients, icustays, and transfers. Another four tables are dictionaries "
    "for cross-referencing codes against their respective definitions: d_icd_diagnoses, "
    "d_icd_procedures, d_items, and d_labitems. The remaining tables, including "
    "chartevents, cost, inputevents_cv, labevents, microbiologyevents, outputevents, "
    "prescriptions, procedures_icd, contain data associated with patient care, such as "
    "physiological measurements, caregiver observations, and billing information."
)

DATASET_SCHEMA_COLUMNS = (
    "- admissions: ROW_ID, SUBJECT_ID, HADM_ID, ADMITTIME, DISCHTIME, ADMISSION_TYPE, "
    "ADMISSION_LOCATION, DISCHARGE_LOCATION, INSURANCE, LANGUAGE, MARITAL_STATUS, ETHNICITY, AGE\n"
    "- chartevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM\n"
    "- cost: ROW_ID, SUBJECT_ID, HADM_ID, EVENT_TYPE, EVENT_ID, CHARGETIME, COST\n"
    "- d_icd_diagnoses: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE\n"
    "- d_icd_procedures: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE\n"
    "- d_items: ROW_ID, ITEMID, LABEL, LINKSTO\n"
    "- d_labitems: ROW_ID, ITEMID, LABEL\n"
    "- diagnoses_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME\n"
    "- icustays: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, FIRST_CAREUNIT, LAST_CAREUNIT, "
    "FIRST_WARDID, LAST_WARDID, INTIME, OUTTIME\n"
    "- inputevents_cv: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, AMOUNT\n"
    "- labevents: ROW_ID, SUBJECT_ID, HADM_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM\n"
    "- microbiologyevents: ROW_ID, SUBJECT_ID, HADM_ID, CHARTTIME, SPEC_TYPE_DESC, ORG_NAME\n"
    "- outputevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, VALUE\n"
    "- patients: ROW_ID, SUBJECT_ID, GENDER, DOB, DOD\n"
    "- prescriptions: ROW_ID, SUBJECT_ID, HADM_ID, STARTDATE, ENDDATE, DRUG, "
    "DOSE_VAL_RX, DOSE_UNIT_RX, ROUTE\n"
    "- procedures_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME\n"
    "- transfers: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, EVENTTYPE, CAREUNIT, WARDID, INTIME, OUTTIME"
)

_LOADDB_TABLES = (
    "admissions, chartevents, cost, d_icd_diagnoses, d_icd_procedures, d_items, "
    "d_labitems, diagnoses_icd, icustays, inputevents_cv, labevents, "
    "microbiologyevents, outputevents, patients, prescriptions, procedures_icd, transfers"
)

_CODING_TEMPLATE = """{schema_preamble}Write a python code to solve the given question. You can use the following functions:
(1) Calculate(FORMULA), which calculates the FORMULA and returns the result.
(2) LoadDB(DBNAME) which loads the database DBNAME and returns the database. The DBNAME can be one of the following: {table_list}.
(3) FilterDB(DATABASE, CONDITIONS), which filters the DATABASE according to the CONDITIONS and returns the filtered database. The CONDITIONS is a string composed of multiple conditions, each of which consists of the column_name, the relation and the value (e.g., COST<10). The CONDITIONS is one single string (e.g., "admissions, SUBJECT_ID=24971").
(4) GetValue(DATABASE, ARGUMENT), which returns a string containing all the values of the column in the DATABASE (if multiple values, separated by ", "). When there is no additional operations on the values, the ARGUMENT is the column_name in demand. If the values need to be returned with certain operations, the ARGUMENT is composed of the column_name and the operation (like COST, sum). Please do not contain " or ' in the argument.
(5) SQLInterpreter(SQL), which interprets the query SQL and returns the result.
(6) Calendar(DURATION), which returns the date after the duration of time.
Use the variable 'answer' to store the answer of the code. Here are some examples:
{examples}
(END OF EXAMPLES)
Knowledge:
{knowledge}
Question: {question}
Solution: """

_COMPILER_BASE = """You are a code execution simulator for an EHR query system.
You receive Python code that uses EHR API functions and simulate what would happen if executed.
You know the full table and column schema but have NO access to actual patient data.
{schema_section}
Check for:
- Wrong table names passed to LoadDB()
- Wrong column names passed to FilterDB() or GetValue()
- Wrong argument format for any API function
- SQL syntax or schema errors in SQLInterpreter()
- Any other obvious code errors

Always respond with EXACTLY [SUCCESS] or [ERROR] on the first line, followed by your
simulated result (SUCCESS) or the predicted error message (ERROR)."""

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

--- Example 3: Invalid FilterDB separator → ERROR ---
Question: count patients in their 30s prescribed metformin.
Code:
patients_db = LoadDB('patients')
filtered_patients_db = FilterDB(patients_db, 'YEAR(DOB) >= 1984 && YEAR(DOB) <= 1993')
subject_id_list = GetValue(filtered_patients_db, 'SUBJECT_ID, list')

[ERROR]
Error: The filtering query YEAR(DOB) >= 1984 && YEAR(DOB) <= 1993 is incorrect. FilterDB only supports '||' to join conditions, not '&&'. SQL functions like YEAR() are also not supported.

--- Example 4: SQL subquery inside FilterDB → ERROR ---
Question: how many days since patient 55501 was first prescribed penicillin?
Code:
prescriptions_db = LoadDB('prescriptions')
filtered_prescriptions_db = FilterDB(prescriptions_db, 'SUBJECT_ID=55501||ITEMID=(SELECT ITEMID FROM d_items WHERE LABEL="penicillin")')

[ERROR]
Error: SQL subqueries are not supported inside FilterDB. Load the lookup table separately with LoadDB, retrieve the ITEMID with GetValue, then pass the value into FilterDB."""


def get_coding_agent_prompt(schema_str, examples, knowledge, question):
    if schema_str:
        schema_preamble = f"Assume you have knowledge of several tables:\n{schema_str}\n"
    else:
        schema_preamble = ""
    return _CODING_TEMPLATE.format(
        schema_preamble=schema_preamble,
        table_list=_LOADDB_TABLES,
        examples=examples,
        knowledge=knowledge,
        question=question,
    )


def get_compiler_system_message(schema_str):
    if schema_str:
        section = f"\nAvailable tables and columns (mimic_iii):\n{schema_str}\n"
    else:
        section = "\n(No schema provided — check API syntax and function argument format only, not column names.)\n"
    return _COMPILER_BASE.format(schema_section=section)


def get_compiler_debugger_system_message(schema_str):
    base = get_compiler_system_message(schema_str)
    return base + '\n\nIf you find an error, also provide a suggested fix on a new line prefixed with:\n"Suggested fix: "'
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/test_prompts.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/prompts/mimic_iii.py EhrAgent/ehragent/data_exploration/tests/test_prompts.py
git commit -m "feat(data_exploration): add parameterized MIMIC-III prompt templates"
```

---

## Task 7: `prompts/eicu.py`

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/prompts/eicu.py`

No separate tests — eICU is structurally identical to MIMIC-III; the shared test pattern covers the contract.

- [ ] **Step 1: Write `prompts/eicu.py`**

```python
# EhrAgent/ehragent/data_exploration/prompts/eicu.py
"""Schema-parameterized prompt templates for eICU."""

DATASET_SCHEMA_NARRATIVE = (
    "(1) Data include vital signs, laboratory measurements, medications, APACHE components, "
    "care plan information, admission diagnosis, patient history, time-stamped diagnoses "
    "from a structured problem list, and similarly chosen treatments.\n"
    "(2) Data from each patient is collected into a common warehouse only if certain "
    "'interfaces' are available. Each interface is used to transform and load a certain "
    "type of data: vital sign interfaces incorporate vital signs, laboratory interfaces "
    "provide measurements on blood samples, and so on.\n"
    "(3) It is important to be aware that different care units may have different interfaces "
    "in place, and that the lack of an interface will result in no data being available for "
    "a given patient, even if those measurements were made in reality.\n"
    "(4) All the databases are used to record information associated to patient care, such as "
    "allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, patient, treatment, "
    "vitalperiodic."
)

DATASET_SCHEMA_COLUMNS = (
    "- allergy: allergyid, patientunitstayid, drugname, allergyname, allergytime\n"
    "- cost: costid, uniquepid, patienthealthsystemstayid, eventtype, eventid, chargetime, cost\n"
    "- diagnosis: diagnosisid, patientunitstayid, icd9code, diagnosisname, diagnosistime\n"
    "- intakeoutput: intakeoutputid, patientunitstayid, cellpath, celllabel, cellvaluenumeric, intakeoutputtime\n"
    "- lab: labid, patientunitstayid, labname, labresult, labresulttime\n"
    "- medication: medicationid, patientunitstayid, drugname, dosage, routeadmin, drugstarttime, drugstoptime\n"
    "- microlab: microlabid, patientunitstayid, culturesite, organism, culturetakentime\n"
    "- patient: patientunitstayid, patienthealthsystemstayid, gender, age, ethnicity, "
    "hospitalid, wardid, admissionheight, hospitaladmitsource, hospitaldischargestatus, "
    "admissionweight, dischargeweight, uniquepid, hospitaladmittime, unitadmittime, "
    "unitdischargetime, hospitaldischargetime\n"
    "- treatment: treatmentid, patientunitstayid, treatmentname, treatmenttime\n"
    "- vitalperiodic: vitalperiodicid, patientunitstayid, temperature, sao2, heartrate, "
    "respiration, systemicsystolic, systemicdiastolic, systemicmean, observationtime"
)

_LOADDB_TABLES = (
    "allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, "
    "patient, treatment, vitalperiodic"
)

_CODING_TEMPLATE = """{schema_preamble}Write a python code to solve the given question. You can use the following functions:
(1) Calculate(FORMULA), which calculates the FORMULA and returns the result.
(2) LoadDB(DBNAME) which loads the database DBNAME and returns the database. The DBNAME can be one of the following: {table_list}.
(3) FilterDB(DATABASE, CONDITIONS), which filters the DATABASE according to the CONDITIONS and returns the filtered database. The CONDITIONS is a string composed of multiple conditions, each of which consists of the column_name, the relation and the value (e.g., COST<10). The CONDITIONS is one single string (e.g., "admissions, SUBJECT_ID=24971"). Different conditions are separated by '||'.
(4) GetValue(DATABASE, ARGUMENT), which returns a string containing all the values of the column in the DATABASE (if multiple values, separated by ", "). When there is no additional operations on the values, the ARGUMENT is the column_name in demand. If the values need to be returned with certain operations, the ARGUMENT is composed of the column_name and the operation (like COST, sum). Please do not contain " or ' in the argument.
(5) SQLInterpreter(SQL), which interprets the query SQL and returns the result.
(6) Calendar(DURATION), which returns the date after the duration of time.
Use the variable 'answer' to store the answer of the code. Here are some examples:
{examples}
(END OF EXAMPLES)
Knowledge:
{knowledge}
Question: {question}
Solution: """

_COMPILER_BASE = """You are a code execution simulator for an EHR query system.
You receive Python code that uses EHR API functions and simulate what would happen if executed.
You know the full table and column schema but have NO access to actual patient data.
{schema_section}
Check for:
- Wrong table names passed to LoadDB()
- Wrong column names passed to FilterDB() or GetValue()
- Wrong argument format for any API function
- SQL syntax or schema errors in SQLInterpreter()
- Any other obvious code errors

Always respond with EXACTLY [SUCCESS] or [ERROR] on the first line, followed by your
simulated result (SUCCESS) or the predicted error message (ERROR)."""

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

--- Example 3: Wrong table name → ERROR ---
Question: count patients with magnesium lab test this year.
Code:
lab_db = LoadDB('labs')
filtered_lab_db = FilterDB(lab_db, 'labname=magnesium')

[ERROR]
Error: 'labs' is not a valid table name. Valid tables are: allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, patient, treatment, vitalperiodic. Use LoadDB('lab') instead."""


def get_coding_agent_prompt(schema_str, examples, knowledge, question):
    if schema_str:
        schema_preamble = f"Assume you have knowledge of several tables:\n{schema_str}\n"
    else:
        schema_preamble = ""
    return _CODING_TEMPLATE.format(
        schema_preamble=schema_preamble,
        table_list=_LOADDB_TABLES,
        examples=examples,
        knowledge=knowledge,
        question=question,
    )


def get_compiler_system_message(schema_str):
    if schema_str:
        section = f"\nAvailable tables and columns (eicu):\n{schema_str}\n"
    else:
        section = "\n(No schema provided — check API syntax and function argument format only, not column names.)\n"
    return _COMPILER_BASE.format(schema_section=section)


def get_compiler_debugger_system_message(schema_str):
    base = get_compiler_system_message(schema_str)
    return base + '\n\nIf you find an error, also provide a suggested fix on a new line prefixed with:\n"Suggested fix: "'
```

- [ ] **Step 2: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/prompts/eicu.py
git commit -m "feat(data_exploration): add parameterized eICU prompt templates"
```

---

## Task 8: `pipeline/agents.py`

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/pipeline/agents.py`

No unit tests — this wires together autogen + existing MedAgent; integration verified by end-to-end test in Task 11.

- [ ] **Step 1: Write `pipeline/agents.py`**

```python
# EhrAgent/ehragent/data_exploration/pipeline/agents.py
import os
import sys

# Add parent directories so legacy EhrAgent modules are importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_EHRAGENT_INNER = os.path.abspath(os.path.join(_HERE, "..", ".."))   # EhrAgent/ehragent/
_EHRAGENT_OUTER = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))  # EhrAgent/
for _p in [_EHRAGENT_OUTER, _EHRAGENT_INNER]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import autogen
from medagent import MedAgent
from compiler_agent import CompilerAgent
from toolset_high import run_code
import tools.tabtools as tabtools


class SchemaAwareMedAgent(MedAgent):
    """MedAgent subclass that injects a parameterized schema into the initial message."""

    def set_schema(self, schema_str, prompt_builder):
        self.schema_str = schema_str
        self.prompt_builder = prompt_builder

    def generate_init_message(self, message, **kwargs):
        self.question = message
        knowledge = self.retrieve_knowledge(message)
        self.knowledge = knowledge
        examples = self.retrieve_examples(message)
        return self.prompt_builder(
            schema_str=self.schema_str,
            examples=examples,
            knowledge=knowledge,
            question=message,
        )


def build_agents(pipeline_type, schema_str, model, api_key, seed, dataset, dataset_path):
    """Build (user_proxy, chatbot) for a given pipeline type and schema string.

    pipeline_type: "compiler_agent" | "baseline"
    schema_str:    "" | dataset schema string | ReFoRCE-generated schema string
    """
    tabtools.configure(dataset_path, dataset)

    if dataset == "mimic_iii":
        from prompts.mimic_iii import (
            get_coding_agent_prompt,
            get_compiler_system_message,
            CompilerAgent_FewShot_Examples,
        )
    else:
        from prompts.eicu import (
            get_coding_agent_prompt,
            get_compiler_system_message,
            CompilerAgent_FewShot_Examples,
        )

    cfg = {"model": model, "api_key": api_key, "api_type": "openai"}
    llm_cfg = {
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
            }
        ],
        "config_list": [cfg],
        "timeout": 120,
        "cache_seed": seed,
        "temperature": 0,
    }

    chatbot = autogen.agentchat.AssistantAgent(
        name="chatbot",
        system_message=(
            "For coding tasks, only use the functions you have been provided with. "
            "Reply TERMINATE when the task is done. Save the answers to the questions "
            "in the variable 'answer'. Please only generate the code."
        ),
        llm_config=llm_cfg,
    )

    user_proxy = SchemaAwareMedAgent(
        name="user_proxy",
        api_key=api_key,
        model=model,
        is_termination_msg=lambda x: x.get("content", "")
        and x.get("content", "").rstrip().endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={"work_dir": "coding", "use_docker": False},
    )
    user_proxy.register_function(function_map={"python": run_code})
    user_proxy.register_dataset(dataset)
    user_proxy.set_schema(schema_str=schema_str, prompt_builder=get_coding_agent_prompt)

    if pipeline_type == "compiler_agent":
        ca = CompilerAgent(
            api_key=api_key,
            model=model,
            dataset=dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=get_compiler_system_message(schema_str),
        )
        user_proxy.set_mode("compiler_agent", compiler_agent=ca)
    # baseline: user_proxy.mode stays "baseline" (default in MedAgent)

    return user_proxy, chatbot
```

- [ ] **Step 2: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/pipeline/agents.py
git commit -m "feat(data_exploration): add SchemaAwareMedAgent and build_agents"
```

---

## Task 9: `pipeline/runner.py`

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/pipeline/runner.py`

- [ ] **Step 1: Write `pipeline/runner.py`**

```python
# EhrAgent/ehragent/data_exploration/pipeline/runner.py
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_EHRAGENT_INNER = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _EHRAGENT_INNER not in sys.path:
    sys.path.insert(0, _EHRAGENT_INNER)

from compiler_agent import CompilerSuccessButExecFailed
from pipeline.judge import judge

NUM_SHOTS = 4


def _extract_code(arguments):
    if isinstance(arguments, dict):
        return arguments.get("cell", str(arguments))
    try:
        parsed = json.loads(arguments)
        return parsed.get("cell", str(parsed))
    except Exception:
        return str(arguments)


def _strip_examples(message):
    marker = "(END OF EXAMPLES)"
    if marker in message:
        return message[message.index(marker) + len(marker):]
    return message


def run_question(user_proxy, chatbot, item, long_term_memory):
    """Run one question with the given agents.

    Returns a result dict compatible with run_pipeline.py output format.
    """
    question = item["template"]
    answer = item["answer"]
    gt_answer = answer if isinstance(answer, str) else ", ".join(answer)

    result = {
        "id": item.get("id", ""),
        "question": question,
        "ground_truth": gt_answer,
        "predicted_answer": "",
        "last_exec_result": "",
        "is_correct": False,
        "status": "incompleted",
        "incompleted_reason": None,
        "num_tries": 0,
        "last_code": "",
        "last_error": "",
        "agent_trace": [],
    }

    try:
        user_proxy.update_memory(NUM_SHOTS, long_term_memory)
        user_proxy.initiate_chat(chatbot, message=question)

        logs = user_proxy.chat_messages
        trace, num_tries, last_code, last_error = [], 0, "", ""

        for agent in list(logs.keys()):
            for msg in logs[agent]:
                content = msg.get("content")
                if content is not None and content != "":
                    cleaned = _strip_examples(str(content))
                    trace.append(cleaned)
                    if "error" in cleaned.lower() or "Error" in cleaned:
                        last_error = cleaned
                elif msg.get("function_call"):
                    code = _extract_code(msg["function_call"]["arguments"])
                    trace.append(code)
                    last_code = code
                    num_tries += 1
                elif msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {})
                        code = _extract_code(fn.get("arguments", ""))
                        trace.append(code)
                        last_code = code
                        num_tries += 1

        result["agent_trace"] = trace
        result["num_tries"] = max(num_tries, 1)
        result["last_code"] = last_code
        result["last_error"] = last_error

        exec_results = [
            trace[i].strip()
            for i in range(2, len(trace), 2)
            if "TERMINATE" not in trace[i]
        ]
        result["last_exec_result"] = exec_results[-1] if exec_results else ""

        logs_string = "\n".join(trace)
        term_idx = logs_string.rfind("TERMINATE")
        prediction_block = logs_string[:term_idx] if term_idx != -1 else logs_string

        is_correct = judge(prediction_block, gt_answer)
        result["predicted_answer"] = prediction_block.strip().split("\n")[-1]
        result["is_correct"] = is_correct
        result["status"] = "correct" if is_correct else "wrong"

    except CompilerSuccessButExecFailed as e:
        result["status"] = "incompleted"
        result["incompleted_reason"] = "compiler_success_exec_failed"
        result["last_error"] = str(e)
        result["last_exec_result"] = str(e)
        result["agent_trace"].append("[INCOMPLETED: compiler said SUCCESS but real exec failed]")

    except Exception as e:
        result["status"] = "incompleted"
        result["incompleted_reason"] = "exception"
        result["last_error"] = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: exception] {e}")

    return result
```

- [ ] **Step 2: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/pipeline/runner.py
git commit -m "feat(data_exploration): add run_question runner"
```

---

## Task 10: `run_exploration.py` — main loop, traces, graphs, summary

**Files:**
- Create: `EhrAgent/ehragent/data_exploration/run_exploration.py`

This is the largest file. Write it in three sub-steps: skeleton + main loop, then traces + summary, then graphs.

- [ ] **Step 1: Write the full `run_exploration.py`**

```python
# EhrAgent/ehragent/data_exploration/run_exploration.py
"""
6-condition benchmark: 2 pipelines × 3 schema variants.

Usage:
    cd EhrAgent/ehragent/data_exploration
    python run_exploration.py --dataset mimic_iii --n 30 --model gpt-4o-mini --seed 42

Output: outputs/YYYYMMDD_HHMMSS/
    summary.md
    raw_results.json
    graphs/accuracy_by_schema.png
    graphs/accuracy_by_pipeline.png
    graphs/completion_rate.png
    graphs/schema_overhead.png
    graphs/per_question_heatmap.png
    traces/<condition>_q<N>_<id>.json
"""
import os
import sys
import json
import random
import argparse
import re
import warnings
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
warnings.filterwarnings("ignore")

# Make data_exploration/ importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_openai_key, get_anthropic_key
from pipeline.agents import build_agents
from pipeline.runner import run_question

DATASET_DEFAULT = "mimic_iii"
DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "ehrsql-ehragent", "ehrsql-ehragent",
)
OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

PIPELINES = ["compiler_agent", "baseline"]
SCHEMA_MODES = ["no_schema", "dataset_schema", "reforce_schema"]

CONDITION_LABEL = {
    ("compiler_agent", "no_schema"):      "CA + No Schema",
    ("compiler_agent", "dataset_schema"): "CA + Dataset Schema",
    ("compiler_agent", "reforce_schema"): "CA + ReFoRCE Schema",
    ("baseline",       "no_schema"):      "BL + No Schema",
    ("baseline",       "dataset_schema"): "BL + Dataset Schema",
    ("baseline",       "reforce_schema"): "BL + ReFoRCE Schema",
}
CONDITION_KEY = {
    ("compiler_agent", "no_schema"):      "compiler_agent__no_schema",
    ("compiler_agent", "dataset_schema"): "compiler_agent__dataset_schema",
    ("compiler_agent", "reforce_schema"): "compiler_agent__reforce_schema",
    ("baseline",       "no_schema"):      "baseline__no_schema",
    ("baseline",       "dataset_schema"): "baseline__dataset_schema",
    ("baseline",       "reforce_schema"): "baseline__reforce_schema",
}


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Data Exploration — 6-condition EHR benchmark")
    p.add_argument("--dataset", default="mimic_iii", choices=["mimic_iii", "eicu"])
    p.add_argument("--dataset_path", default=DEFAULT_DATASET_PATH)
    p.add_argument("--n", type=int, default=10, help="Questions to run (-1 = all)")
    p.add_argument("--model", default="gpt-4o-mini", help="OpenAI model for coding/compiler agents")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--conditions",
        default="all",
        help="Comma-separated condition keys or 'all'. "
             "Keys: compiler_agent__no_schema, compiler_agent__dataset_schema, "
             "compiler_agent__reforce_schema, baseline__no_schema, "
             "baseline__dataset_schema, baseline__reforce_schema",
    )
    return p.parse_args()


# ── Dataset loading ───────────────────────────────────────────────────────────

def load_questions(dataset_path, dataset, n, seed):
    data_file = os.path.join(dataset_path, dataset, "valid_preprocessed.json")
    with open(data_file) as f:
        all_qs = json.load(f)
    random.seed(seed)
    random.shuffle(all_qs)
    fewshot = _extract_fewshot_questions(dataset)
    filtered = [q for q in all_qs if q["template"].strip().lower() not in fewshot]
    if n != -1:
        filtered = filtered[:n]
    return filtered


def _extract_fewshot_questions(dataset):
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _INNER = os.path.abspath(os.path.join(_HERE, ".."))
    if _INNER not in sys.path:
        sys.path.insert(0, _INNER)
    if dataset == "mimic_iii":
        from prompts_mimic import EHRAgent_4Shots_Knowledge, CompilerAgent_FewShot_Examples
    else:
        from prompts_eicu import EHRAgent_4Shots_Knowledge, CompilerAgent_FewShot_Examples
    questions = set()
    for block in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        m = re.search(r"Question:\s*(.+?)(?:\nKnowledge:|\Z)", block, re.DOTALL)
        if m:
            questions.add(m.group(1).strip().lower())
    for line in CompilerAgent_FewShot_Examples.split("\n"):
        if line.startswith("Question:"):
            questions.add(line[len("Question:"):].strip().lower())
    return questions


def load_long_term_memory(dataset):
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _INNER = os.path.abspath(os.path.join(_HERE, ".."))
    if _INNER not in sys.path:
        sys.path.insert(0, _INNER)
    if dataset == "mimic_iii":
        from prompts_mimic import EHRAgent_4Shots_Knowledge
    else:
        from prompts_eicu import EHRAgent_4Shots_Knowledge
    memory = []
    for block in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        block = block.split("Question:")[-1]
        q_part = block.split("\nKnowledge:\n")[0]
        rest = block.split("\nKnowledge:\n")[-1]
        k_part = rest.split("\nSolution:")[0]
        c_part = rest.split("\nSolution:")[-1]
        memory.append({"question": q_part, "knowledge": k_part, "code": c_part})
    return memory


# ── Schema string helpers ─────────────────────────────────────────────────────

def get_dataset_schema(dataset):
    if dataset == "mimic_iii":
        from prompts.mimic_iii import DATASET_SCHEMA_NARRATIVE, DATASET_SCHEMA_COLUMNS
        return DATASET_SCHEMA_NARRATIVE + "\n" + DATASET_SCHEMA_COLUMNS
    else:
        from prompts.eicu import DATASET_SCHEMA_NARRATIVE, DATASET_SCHEMA_COLUMNS
        return DATASET_SCHEMA_NARRATIVE + "\n" + DATASET_SCHEMA_COLUMNS


def get_reforce_schema(dataset, dataset_path, anthropic_key):
    from schema_explorer.explorer import SchemaExplorer
    if dataset == "mimic_iii":
        db_path = os.path.join(dataset_path, "mimic_iii", "mimic_iii.db")
    else:
        db_path = os.path.join(dataset_path, "eicu", "eicu.db")
    explorer = SchemaExplorer(db_path=db_path, api_key=anthropic_key)
    schema_str, explorer_trace = explorer.explore()
    return schema_str, explorer_trace


# ── Run one condition ─────────────────────────────────────────────────────────

def run_condition(
    pipeline_type, schema_mode, schema_str, questions,
    model, openai_key, seed, dataset, dataset_path,
    long_term_memory_base, run_dir, explorer_trace,
    verbose,
):
    ckey = CONDITION_KEY[(pipeline_type, schema_mode)]
    label = CONDITION_LABEL[(pipeline_type, schema_mode)]
    if verbose:
        print(f"\n{'='*60}\n  {label}\n{'='*60}")

    user_proxy, chatbot = build_agents(
        pipeline_type=pipeline_type,
        schema_str=schema_str,
        model=model,
        api_key=openai_key,
        seed=seed,
        dataset=dataset,
        dataset_path=dataset_path,
    )
    long_term_memory = list(long_term_memory_base)
    results = []
    traces_dir = os.path.join(run_dir, "traces")
    os.makedirs(traces_dir, exist_ok=True)

    for i, item in enumerate(questions):
        if verbose:
            print(f"  [{i+1}/{len(questions)}] {item['template'][:70]}...")

        result = run_question(user_proxy, chatbot, item, long_term_memory)
        results.append(result)

        # Build trace
        trace_doc = {
            "condition": ckey,
            "pipeline": pipeline_type,
            "schema_mode": schema_mode,
            "question_id": item.get("id", str(i)),
            "question_text": item["template"],
            "ground_truth": result["ground_truth"],
            "status": result["status"],
            "is_correct": result["is_correct"],
            "num_tries": result["num_tries"],
            "predicted_answer": result["predicted_answer"],
            "last_code": result["last_code"],
            "last_error": result["last_error"],
            "agent_trace": result["agent_trace"],
            "schema_explorer": explorer_trace if schema_mode == "reforce_schema" else None,
        }
        trace_bytes = json.dumps(trace_doc, indent=2, default=str).encode("utf-8")
        trace_fname = f"{ckey}__q{i+1:02d}_{item.get('id', str(i))[:8]}.json"
        trace_path = os.path.join(traces_dir, trace_fname)
        if len(trace_bytes) > 1_000_000:
            # Split into parts
            half = len(trace_doc["agent_trace"]) // 2
            for part_idx, chunk in enumerate(
                [trace_doc["agent_trace"][:half], trace_doc["agent_trace"][half:]]
            ):
                part_doc = dict(trace_doc)
                part_doc["agent_trace"] = chunk
                part_doc["_part"] = part_idx + 1
                part_path = trace_path.replace(".json", f"_part{part_idx+1}.json")
                with open(part_path, "w", encoding="utf-8") as f:
                    json.dump(part_doc, f, indent=2, default=str)
        else:
            with open(trace_path, "w", encoding="utf-8") as f:
                f.write(trace_bytes.decode("utf-8"))

        if result["status"] == "correct" and result["last_code"]:
            long_term_memory.append({
                "question": item["template"],
                "knowledge": user_proxy.knowledge,
                "code": result["last_code"],
            })

        if verbose:
            print(f"    -> {result['status'].upper()} | tries={result['num_tries']}")

    correct = sum(1 for r in results if r["status"] == "correct")
    if verbose:
        print(f"  Done: {correct}/{len(questions)} correct")
    return results


# ── Stats ─────────────────────────────────────────────────────────────────────

def _stats(results):
    n = len(results)
    correct = sum(1 for r in results if r["status"] == "correct")
    wrong = sum(1 for r in results if r["status"] == "wrong")
    incomp = sum(1 for r in results if r["status"] == "incompleted")
    return {
        "n": n,
        "correct": correct,
        "wrong": wrong,
        "incompleted": incomp,
        "accuracy": correct / n * 100 if n else 0,
        "completion_rate": (n - incomp) / n * 100 if n else 0,
    }


# ── Summary ───────────────────────────────────────────────────────────────────

def write_summary(run_dir, questions, all_results, explorer_tokens):
    lines = [
        "# Data Exploration — 6-Condition EHR Benchmark", "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Questions:** {len(questions)}", "",
        "---", "", "## Accuracy vs Ground Truth", "",
        "| Condition | Correct | Wrong | Incompleted | Accuracy | Completion Rate |",
        "|-----------|---------|-------|-------------|----------|-----------------|",
    ]
    for pipeline in PIPELINES:
        for schema in SCHEMA_MODES:
            ckey = CONDITION_KEY[(pipeline, schema)]
            label = CONDITION_LABEL[(pipeline, schema)]
            if ckey not in all_results:
                continue
            s = _stats(all_results[ckey])
            lines.append(
                f"| {label} | {s['correct']} | {s['wrong']} | {s['incompleted']} "
                f"| {s['accuracy']:.1f}% | {s['completion_rate']:.1f}% |"
            )

    if explorer_tokens:
        lines += ["", "---", "", "## Schema Explorer Overhead", "",
                  "| Metric | Value |", "|--------|-------|",
                  f"| Tokens used | {explorer_tokens.get('tokens_used', 'N/A')} |",
                  f"| API calls | {explorer_tokens.get('api_calls', 'N/A')} |"]

    lines += ["", "---", "", "## Per-Question Status", ""]
    header = "| # | Question |"
    sep = "|---|----------|"
    for pipeline in PIPELINES:
        for schema in SCHEMA_MODES:
            label = CONDITION_LABEL[(pipeline, schema)]
            header += f" {label} |"
            sep += "---------|"
    lines += [header, sep]

    for i, item in enumerate(questions):
        q_short = (item["template"][:45] + "...") if len(item["template"]) > 45 else item["template"]
        row = f"| {i+1} | {q_short} |"
        for pipeline in PIPELINES:
            for schema in SCHEMA_MODES:
                ckey = CONDITION_KEY[(pipeline, schema)]
                if ckey in all_results and i < len(all_results[ckey]):
                    r = all_results[ckey][i]
                    emoji = {"correct": "✅", "wrong": "❌", "incompleted": "⚠️"}.get(r["status"], "?")
                    row += f" {emoji} {r['status']} ({r['num_tries']}t) |"
                else:
                    row += " — |"
        lines.append(row)

    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Graphs ────────────────────────────────────────────────────────────────────

def _accuracy(results):
    if not results:
        return 0
    return sum(1 for r in results if r["status"] == "correct") / len(results) * 100


def _completion(results):
    if not results:
        return 0
    return sum(1 for r in results if r["status"] != "incompleted") / len(results) * 100


def plot_accuracy_by_schema(graphs_dir, all_results):
    schema_labels = ["No Schema", "Dataset Schema", "ReFoRCE Schema"]
    pipeline_labels = ["Compiler Agent", "Baseline"]
    x = np.arange(len(SCHEMA_MODES))
    width = 0.35
    colors = ["#F44336", "#2196F3"]

    fig, ax = plt.subplots(figsize=(9, 6))
    for j, (pipeline, color, plabel) in enumerate(zip(PIPELINES, colors, pipeline_labels)):
        vals = [_accuracy(all_results.get(CONDITION_KEY[(pipeline, s)], [])) for s in SCHEMA_MODES]
        offset = (j - 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=plabel, color=color, edgecolor="white")
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(schema_labels)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Accuracy by Schema Type")
    ax.legend()
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    plt.tight_layout()
    plt.savefig(os.path.join(graphs_dir, "accuracy_by_schema.png"), dpi=150)
    plt.close()


def plot_accuracy_by_pipeline(graphs_dir, all_results):
    pipeline_labels = ["Compiler Agent", "Baseline"]
    schema_labels = ["No Schema", "Dataset Schema", "ReFoRCE Schema"]
    x = np.arange(len(PIPELINES))
    width = 0.25
    colors = ["#9E9E9E", "#4CAF50", "#FF9800"]

    fig, ax = plt.subplots(figsize=(8, 6))
    for j, (schema, color, slabel) in enumerate(zip(SCHEMA_MODES, colors, schema_labels)):
        vals = [_accuracy(all_results.get(CONDITION_KEY[(p, schema)], [])) for p in PIPELINES]
        offset = (j - 1) * width
        bars = ax.bar(x + offset, vals, width, label=slabel, color=color, edgecolor="white")
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(pipeline_labels)
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Accuracy by Pipeline Type")
    ax.legend()
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    plt.tight_layout()
    plt.savefig(os.path.join(graphs_dir, "accuracy_by_pipeline.png"), dpi=150)
    plt.close()


def plot_completion_rate(graphs_dir, all_results):
    schema_labels = ["No Schema", "Dataset Schema", "ReFoRCE Schema"]
    pipeline_labels = ["Compiler Agent", "Baseline"]
    x = np.arange(len(SCHEMA_MODES))
    width = 0.35
    colors = ["#F44336", "#2196F3"]

    fig, ax = plt.subplots(figsize=(9, 6))
    for j, (pipeline, color, plabel) in enumerate(zip(PIPELINES, colors, pipeline_labels)):
        vals = [_completion(all_results.get(CONDITION_KEY[(pipeline, s)], [])) for s in SCHEMA_MODES]
        offset = (j - 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=plabel, color=color, edgecolor="white")
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(schema_labels)
    ax.set_ylabel("Completion Rate (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Completion Rate by Schema Type\n(questions that did not error entirely)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3, linestyle="--")
    plt.tight_layout()
    plt.savefig(os.path.join(graphs_dir, "completion_rate.png"), dpi=150)
    plt.close()


def plot_schema_overhead(graphs_dir, explorer_trace):
    if not explorer_trace:
        return
    tokens = explorer_trace.get("tokens_used", 0)
    calls = explorer_trace.get("api_calls", 0)

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    for ax, val, label, color in zip(
        axes,
        [tokens, calls],
        ["Tokens Used", "API Calls"],
        ["#9C27B0", "#FF5722"],
    ):
        ax.bar(["ReFoRCE Explorer"], [val], color=color, edgecolor="white", width=0.4)
        ax.set_title(label)
        ax.set_ylabel(label)
        ax.bar_label(ax.containers[0], padding=3)
        ax.set_ylim(0, val * 1.3 + 1)

    plt.suptitle("Schema Explorer Resource Usage (per run)", fontsize=12)
    plt.tight_layout()
    plt.savefig(os.path.join(graphs_dir, "schema_overhead.png"), dpi=150)
    plt.close()


def plot_per_question_heatmap(graphs_dir, questions, all_results):
    conditions_ordered = [
        ("compiler_agent", "no_schema"),
        ("compiler_agent", "dataset_schema"),
        ("compiler_agent", "reforce_schema"),
        ("baseline",       "no_schema"),
        ("baseline",       "dataset_schema"),
        ("baseline",       "reforce_schema"),
    ]
    condition_labels = [CONDITION_LABEL[c] for c in conditions_ordered]

    STATUS_VAL = {"correct": 2, "wrong": 1, "incompleted": 0}
    data = []
    for cond in conditions_ordered:
        ckey = CONDITION_KEY[cond]
        results = all_results.get(ckey, [])
        row = [STATUS_VAL.get(r["status"], 0) for r in results]
        row += [0] * (len(questions) - len(row))
        data.append(row)

    data = np.array(data)
    cmap = ListedColormap(["#FF9800", "#F44336", "#4CAF50"])

    fig, ax = plt.subplots(figsize=(max(10, len(questions) * 0.45), 5))
    ax.imshow(data, aspect="auto", cmap=cmap, vmin=0, vmax=2)

    ax.set_yticks(range(len(condition_labels)))
    ax.set_yticklabels(condition_labels, fontsize=9)
    ax.set_xticks(range(len(questions)))
    ax.set_xticklabels([str(i + 1) for i in range(len(questions))], fontsize=7)
    ax.set_xlabel("Question index")
    ax.set_title("Per-Question Outcomes Across All Conditions")

    legend_elements = [
        Patch(facecolor="#4CAF50", label="Correct"),
        Patch(facecolor="#F44336", label="Wrong"),
        Patch(facecolor="#FF9800", label="Incomplete"),
    ]
    ax.legend(handles=legend_elements, loc="upper right",
              bbox_to_anchor=(1.18, 1.0), fontsize=9)

    plt.tight_layout()
    plt.savefig(
        os.path.join(graphs_dir, "per_question_heatmap.png"),
        dpi=150, bbox_inches="tight",
    )
    plt.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    openai_key = get_openai_key()
    anthropic_key = get_anthropic_key()

    questions = load_questions(args.dataset_path, args.dataset, args.n, args.seed)
    print(f"Loaded {len(questions)} questions | dataset={args.dataset} | model={args.model}")

    long_term_memory = load_long_term_memory(args.dataset)
    dataset_schema = get_dataset_schema(args.dataset)

    # Determine which conditions to run
    all_condition_keys = set(CONDITION_KEY.values())
    if args.conditions == "all":
        conditions_to_run = set(all_condition_keys)
    else:
        conditions_to_run = set(k.strip() for k in args.conditions.split(","))
        unknown = conditions_to_run - all_condition_keys
        if unknown:
            raise ValueError(f"Unknown condition keys: {unknown}")

    # Run ReFoRCE schema explorer once if needed
    reforce_schema = ""
    explorer_trace = None
    needs_reforce = any(
        CONDITION_KEY[(p, "reforce_schema")] in conditions_to_run
        for p in PIPELINES
    )
    if needs_reforce:
        print("\nRunning ReFoRCE schema explorer...")
        reforce_schema, explorer_trace = get_reforce_schema(
            args.dataset, args.dataset_path, anthropic_key
        )
        print(f"  Schema explorer done. Tokens: {explorer_trace.get('tokens_used', '?')} | "
              f"API calls: {explorer_trace.get('api_calls', '?')}")

    schema_for_mode = {
        "no_schema":      "",
        "dataset_schema": dataset_schema,
        "reforce_schema": reforce_schema,
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(OUTPUT_BASE, ts)
    os.makedirs(os.path.join(run_dir, "graphs"), exist_ok=True)
    print(f"\nOutput: {run_dir}")

    all_results = {}
    for pipeline in PIPELINES:
        for schema_mode in SCHEMA_MODES:
            ckey = CONDITION_KEY[(pipeline, schema_mode)]
            if ckey not in conditions_to_run:
                continue
            results = run_condition(
                pipeline_type=pipeline,
                schema_mode=schema_mode,
                schema_str=schema_for_mode[schema_mode],
                questions=questions,
                model=args.model,
                openai_key=openai_key,
                seed=args.seed,
                dataset=args.dataset,
                dataset_path=args.dataset_path,
                long_term_memory_base=long_term_memory,
                run_dir=run_dir,
                explorer_trace=explorer_trace,
                verbose=True,
            )
            all_results[ckey] = results

    print("\nWriting summary and graphs...")
    write_summary(run_dir, questions, all_results, explorer_trace)

    graphs_dir = os.path.join(run_dir, "graphs")
    plot_accuracy_by_schema(graphs_dir, all_results)
    plot_accuracy_by_pipeline(graphs_dir, all_results)
    plot_completion_rate(graphs_dir, all_results)
    plot_schema_overhead(graphs_dir, explorer_trace)
    plot_per_question_heatmap(graphs_dir, questions, all_results)

    with open(os.path.join(run_dir, "raw_results.json"), "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n{'='*60}\nComplete: {run_dir}\n{'='*60}")
    for pipeline in PIPELINES:
        for schema_mode in SCHEMA_MODES:
            ckey = CONDITION_KEY[(pipeline, schema_mode)]
            if ckey in all_results:
                s = _stats(all_results[ckey])
                label = CONDITION_LABEL[(pipeline, schema_mode)]
                print(f"  {label}: {s['correct']}/{s['n']} correct ({s['accuracy']:.1f}%)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script is importable (no syntax errors)**

```bash
cd EhrAgent/ehragent/data_exploration
python -c "import run_exploration; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add EhrAgent/ehragent/data_exploration/run_exploration.py
git commit -m "feat(data_exploration): add run_exploration entry point with 6-condition loop and graphs"
```

---

## Task 11: Full test suite pass + smoke test

- [ ] **Step 1: Run the full test suite**

```bash
cd EhrAgent/ehragent/data_exploration
python -m pytest tests/ -v
```

Expected: All tests pass (judge: 8, sql_executor: 5, explorer: 3, prompts: 7 = 23 total)

- [ ] **Step 2: Dry-run smoke test (n=1, conditions=baseline__dataset_schema only)**

This uses real APIs. Run only if both keys are set. It runs 1 question with the baseline + dataset schema condition — the cheapest possible check.

```bash
cd EhrAgent/ehragent/data_exploration
export OPENAI_API_KEY=<your_key>
export ANTHROPIC_API_KEY=<your_key>   # needed even if not running reforce

python run_exploration.py \
  --dataset mimic_iii \
  --n 1 \
  --model gpt-4o-mini \
  --seed 42 \
  --conditions baseline__dataset_schema
```

Expected output:
```
Loaded 1 questions | dataset=mimic_iii | model=gpt-4o-mini
Output: outputs/YYYYMMDD_HHMMSS/
  [1/1] <question text>...
    -> <STATUS> | tries=<N>
  Done: <N>/1 correct
Writing summary and graphs...
Complete: outputs/YYYYMMDD_HHMMSS/
  BL + Dataset Schema: N/1 correct (N.N%)
```

Verify that `outputs/YYYYMMDD_HHMMSS/` contains:
- `summary.md` — has a table row for `BL + Dataset Schema`
- `graphs/accuracy_by_schema.png` — file exists
- `graphs/per_question_heatmap.png` — file exists
- `traces/baseline__dataset_schema__q01_*.json` — file exists and is valid JSON

- [ ] **Step 3: Final commit**

```bash
git add EhrAgent/ehragent/data_exploration/
git commit -m "feat(data_exploration): complete ReFoRCE schema explorer pipeline — 6 conditions, traces, graphs"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ 6 conditions (2 pipelines × 3 schema modes) — Tasks 8–10
- ✅ Schema stripped from both compiler system message AND coding agent initial prompt — Task 6/7/8
- ✅ ReFoRCE 3-stage explorer (table discovery, column probing, compression) — Task 5
- ✅ `claude-haiku-4-5-20251001` for all explorer LLM calls — Task 5
- ✅ Parameterized prompts — Tasks 6/7
- ✅ Trace JSON per question per condition — Task 10 (`run_condition`)
- ✅ 5 comparison graphs — Task 10 (`plot_*` functions)
- ✅ `summary.md` — Task 10 (`write_summary`)
- ✅ `raw_results.json` — Task 10 (main)
- ✅ API keys from env only — Task 1 (`config.py`)
- ✅ No modification of files outside `data_exploration/` — all paths are under `data_exploration/`
- ✅ ReFoRCE explorer runs once per run (not once per question) — Task 10 (`needs_reforce` block)
- ✅ Trace files split if > 1MB — Task 10 (`run_condition`)
- ✅ Few-shot questions excluded from benchmark — Task 10 (`load_questions`)

**Type consistency:**
- `SchemaAwareMedAgent.set_schema(schema_str, prompt_builder)` → called in `build_agents` ✅
- `SchemaExplorer.explore()` → returns `(schema_str, trace_dict)` → consumed in `get_reforce_schema` ✅
- `run_question(user_proxy, chatbot, item, long_term_memory)` → called in `run_condition` ✅
- `get_coding_agent_prompt(schema_str, examples, knowledge, question)` → matches call in `SchemaAwareMedAgent.generate_init_message` ✅
- `get_compiler_system_message(schema_str)` → called in `build_agents` ✅
- `_stats(results)` → dict with keys `n, correct, wrong, incompleted, accuracy, completion_rate` → used in `write_summary` and `main` ✅
