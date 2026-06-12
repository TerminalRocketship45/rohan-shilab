# Design: ReFoRCE Schema Explorer — `data_exploration/` Pipeline

**Date:** 2026-06-11  
**Status:** Approved

---

## Goal

Benchmark six conditions across two pipeline types × three schema variants to measure the marginal value of (a) compiler-agent validation and (b) auto-generated vs. dataset vs. no schema, against the EHRSQL MIMIC-III and eICU benchmarks.

References:
- EHRAgent paper: https://arxiv.org/abs/2401.07128
- ReFoRCE paper: https://arxiv.org/abs/2502.00675
- ReFoRCE code: https://github.com/Snowflake-Labs/ReFoRCE

---

## Six Conditions

| Condition | Pipeline | Schema |
|-----------|----------|--------|
| 1 | Compiler Agent + Coding Agent | No schema |
| 2 | Compiler Agent + Coding Agent | Dataset schema (original EHRAgent) |
| 3 | Compiler Agent + Coding Agent | ReFoRCE-generated schema |
| 4 | Baseline (Coding Agent only) | No schema |
| 5 | Baseline (Coding Agent only) | Dataset schema |
| 6 | Baseline (Coding Agent only) | ReFoRCE-generated schema |

Schema is stripped/replaced in **both** the compiler agent system message AND the coding agent's initial prompt for all conditions. This is consistent with the original paper, which injects schema (D + C_i) into the coding agent's initial message.

---

## Folder Structure

```
EhrAgent/ehragent/data_exploration/
├── run_exploration.py          # CLI entry point
├── schema_explorer/
│   ├── __init__.py
│   ├── explorer.py             # Core schema explorer agent
│   ├── prompts.py              # LLM prompts for explorer (all claude-haiku-4-5)
│   └── sql_executor.py         # SQLite execution wrapper
├── pipeline/
│   ├── __init__.py
│   ├── agents.py               # Build coding agent + optional compiler agent
│   ├── runner.py               # Run one question under one condition
│   └── judge.py                # judge() function (copied from run_pipeline.py)
├── prompts/
│   ├── mimic_iii.py            # Schema-parameterized prompt templates for MIMIC-III
│   └── eicu.py                 # Schema-parameterized prompt templates for eICU
├── outputs/
│   └── .gitkeep
└── config.py                   # API key reading from environment variables only
```

**Hard constraints:**
- Do NOT modify any file outside `data_exploration/`
- Do NOT modify the coding agent in any way
- No API keys hardcoded anywhere — all from `os.environ`

---

## Schema Explorer Design

### LLM: `claude-haiku-4-5-20251001` via Anthropic API

### Stage 1 — Table Discovery
- Query: `SELECT name FROM sqlite_master WHERE type='table'`
- Group tables by name prefix/suffix into clusters (e.g. `d_icd_diagnoses`, `d_icd_procedures` → `d_icd_*`)
- Select one representative per cluster for full exploration
- Non-representative tables: record name only (no column probe)

### Stage 2 — Column Probing (per representative table)
For each representative table, run this sequence:

1. `PRAGMA table_info({table})` → column names + declared SQLite types
2. `SELECT * FROM {table} LIMIT 3` → sample values, detect ambiguous/coded columns
3. LLM decides if any column needs a targeted follow-up (e.g. ITEMID → join with d_items)
4. Run follow-up queries as needed

**Error handling:** If a query fails, treat the error as a schema signal. Ask LLM to rewrite the query. Retry up to 3× per query. Log error + rewrite + outcome to trace.

### Stage 3 — Schema Compression
LLM synthesizes per table:
- Column list: `col_name (SQLite_type)`
- One-sentence narrative description inferred from sample rows
- Output format matches dataset schema exactly (same style as `CompilerAgent_System_Message`)

### Output
A schema string usable as a drop-in replacement for the hardcoded dataset schema. Used for condition 3 and 6.

---

## Prompt Templates (parameterized)

`prompts/mimic_iii.py` and `prompts/eicu.py` are adapted from the originals. Each prompt that contained a hardcoded schema now accepts a `schema` parameter:

- `schema=""` → condition A/D (no schema)
- `schema=DATASET_SCHEMA` → condition B/E (dataset schema)
- `schema=explorer.explore(db_path, question)` → condition C/F (ReFoRCE schema)

Both `CompilerAgent_System_Message` and `EHRAgent_Message_Prompt` are parameterized.

---

## Entry Point CLI

```bash
python run_exploration.py \
  --dataset mimic_iii \
  --n 30 \
  --model gpt-4o-mini \
  --seed 42 \
  --dataset_path ../ehrsql-ehragent/ehrsql-ehragent
```

Flags:
- `--dataset`: `mimic_iii` or `eicu`
- `--n`: number of questions (-1 = all, excluding few-shot)
- `--model`: OpenAI model for coding/compiler agents
- `--seed`: random seed
- `--dataset_path`: path to the EHRSQL data folder
- `--conditions`: comma-separated subset e.g. `1,2,3` (default: all 6)

---

## Output Folder Structure

```
outputs/YYYYMMDD_HHMMSS/
├── summary.md                        # Full stats table: all 6 conditions
├── graphs/
│   ├── accuracy_by_schema.png        # Grouped bar: accuracy per schema, one group per pipeline
│   ├── accuracy_by_pipeline.png      # Grouped bar: accuracy per pipeline, one group per schema
│   ├── completion_rate.png           # Same layout, completion rate metric
│   ├── schema_overhead.png           # Bar: tokens + API calls used by schema explorer
│   └── per_question_heatmap.png      # Heatmap: question × condition, color = correct/wrong/incomplete
├── traces/
│   ├── compiler_agent__no_schema__q01_<id>.json
│   ├── compiler_agent__dataset_schema__q01_<id>.json
│   ├── compiler_agent__reforce_schema__q01_<id>.json
│   ├── baseline__no_schema__q01_<id>.json
│   ├── baseline__dataset_schema__q01_<id>.json
│   └── baseline__reforce_schema__q01_<id>.json
└── raw_results.json                  # All result dicts for all 6 conditions
```

---

## Trace Schema (per question per condition)

```json
{
  "condition": "compiler_agent__reforce_schema",
  "pipeline": "compiler_agent",
  "schema_mode": "reforce",
  "question_id": "...",
  "question_text": "...",
  "ground_truth": "...",
  "timestamp_start": "...",
  "timestamp_end": "...",

  "schema_explorer": {
    "stage_1_tables": [...],
    "stage_1_clusters": {},
    "stage_2_column_exploration": [
      {
        "table": "...",
        "queries": [
          {"sql": "...", "result": "...", "error": null, "retry_count": 0,
           "llm_prompt": "...", "llm_response": "..."}
        ]
      }
    ],
    "stage_3_schema_output": "...",
    "tokens_used": 0,
    "api_calls": 0
  },

  "compiler_agent_iterations": [...],

  "final_answer": "...",
  "is_correct": true,
  "status": "correct",
  "num_tries": 1,
  "tokens_used": {"schema_explorer": 0, "compiler_agent": 0, "total": 0},
  "api_calls": {"schema_explorer": 0, "compiler_agent": 0, "total": 0}
}
```

Baseline-mode traces omit `schema_explorer` and `compiler_agent_iterations`. Files exceeding 1 MB are split into `_part1.json`, `_part2.json`.

---

## Graphs

| Graph | X-axis | Y-axis | Series |
|-------|--------|--------|--------|
| `accuracy_by_schema.png` | Schema type (none / dataset / ReFoRCE) | Accuracy % | One bar group per pipeline |
| `accuracy_by_pipeline.png` | Pipeline (compiler / baseline) | Accuracy % | One bar group per schema |
| `completion_rate.png` | Schema type | Completion rate % | One bar group per pipeline |
| `schema_overhead.png` | Schema type | Tokens / API calls | Stacked bars |
| `per_question_heatmap.png` | Question index | Condition (6 rows) | Color: correct=green, wrong=red, incomplete=orange |

---

## Metrics

Same as original EHRAgent paper (for direct comparability):
- **Accuracy**: fraction of questions with correct final answer (via `judge()`)
- **Completion rate**: fraction where execution did not error entirely

New metrics:
- **Schema explorer overhead**: tokens + API calls consumed by explorer only
- **Delta vs. no-schema**: accuracy lift from using dataset or ReFoRCE schema

---

## API Key Requirements

```bash
export OPENAI_API_KEY=...          # for coding agent + compiler agent
export ANTHROPIC_API_KEY=...       # for schema explorer (claude-haiku-4-5)
```

Both read via `os.environ` in `config.py`. `EnvironmentError` raised immediately if missing.
