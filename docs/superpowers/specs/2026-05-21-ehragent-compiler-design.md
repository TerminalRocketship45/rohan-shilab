# EHRAgent Ethical Compiler Pipeline — Design Spec
**Date:** 2026-05-21  
**Status:** Approved

---

## 1. Problem & Motivation

The original EHRAgent pipeline runs the Coding Agent's generated Python code directly via `exec()` against real EHR CSV/SQLite data. This gives the AI unrestricted programmatic access to patient data — it could write code to dump entire tables and receive real patient records back in error messages (e.g. `"Five example values in HADM_ID: 100001, 100002..."`).

The goal is to introduce a **Compiler Agent** (LLM) that intercepts code before real execution, checks it against schema knowledge only, and ensures the Coding Agent never receives raw patient data in feedback. Real execution still happens — but only after the LLM gatekeeper approves the code, and any real execution error is silently swallowed (not fed back to the AI).

---

## 2. Datasets

Unzipped location: `C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehrsql-ehragent\ehrsql-ehragent\`

| Dataset | Question file | Tables |
|---------|--------------|--------|
| `mimic_iii` | `mimic_iii/valid_preprocessed.json` (581 questions) | admissions, chartevents, cost, d_icd_diagnoses, d_icd_procedures, d_items, d_labitems, diagnoses_icd, icustays, inputevents_cv, labevents, microbiologyevents, outputevents, patients, prescriptions, procedures_icd, transfers |
| `eicu` | `eicu/valid_preprocessed.json` (580 questions) | allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, patient, treatment, vitalperiodic |

Each question record has: `template` (the question), `answer` (ground truth), `id`.

---

## 3. Three Approaches

### Approach 3 — Baseline (no flag)
Original pipeline, no changes to execution logic. Used to establish accuracy baseline and to collect real error examples for the Compiler Agent prompts.

```
CodingAgent → code → run_code() [real exec()]
                          ↓
               result OR error + debugger explanation → CodingAgent → retry (up to 10 turns)
```

### Approach 1 — Three Agents (`--compiler_agent`)
```
CodingAgent → code → CompilerAgent (LLM, schema-aware)
                          ↓
              [ERROR]  → DebuggerAgent → one-line reason → CodingAgent → retry
                          ↓
              [SUCCESS] → run_code() [real exec()]
                              ↓
                        real result → CodingAgent → TERMINATE
                              ↓
                        real error  → mark INCOMPLETED, STOP (no AI feedback)
```

### Approach 2 — Two Agents (`--newdebugger`)
```
CodingAgent → code → CompilerDebuggerAgent (LLM, combined)
                          ↓
              [ERROR]  → error message + "Suggested fix: ..." → CodingAgent → retry
                          ↓
              [SUCCESS] → run_code() [real exec()]
                              ↓
                        real result → CodingAgent → TERMINATE
                              ↓
                        real error  → mark INCOMPLETED, STOP (no AI feedback)
```

**Key ethical property (Approaches 1 & 2):** The Coding Agent only ever sees:
- Its own generated code
- Schema-level `[ERROR]` messages (column/table names, no data values)
- A clean final answer string

It never sees real Python tracebacks or data-exposing error messages.

---

## 4. File Structure

```
EhrAgent/ehragent/
  pipeline.py          ← NEW: main entry point
  compiler_agent.py    ← NEW: CompilerAgent and CompilerDebuggerAgent classes
  medagent.py          ← MODIFIED: standard OpenAI, compiler hook in execute_function()
  config.py            ← MODIFIED: standard OpenAI config (api_key from env)
  prompts_mimic.py     ← MODIFIED: add CompilerAgent prompt templates
  prompts_eicu.py      ← MODIFIED: add CompilerAgent prompt templates
  toolset_high.py      ← MODIFIED: dataset_path injected at runtime via module global

EhrAgent/ehragent/outputs/
  run_<YYYYMMDD_HHMMSS>_<dataset>_<mode>_n<N>/
    results.json
    errors.json
    summary_plot.png
```

---

## 5. Pipeline Entry Point (`pipeline.py`)

### Arguments
```
--dataset       mimic_iii | eicu          (required)
--dataset_path  <path>                    (optional; defaults to the unzipped
                                           ehrsql-ehragent folder already on disk)
--n             30                        (default; -1 = all)
--compiler_agent                          (flag: Approach 1)
--newdebugger                             (flag: Approach 2)
--model         gpt-4o-mini               (default)
--seed          42
--num_shots     4
```

`--compiler_agent` and `--newdebugger` are mutually exclusive. Neither = Approach 3 baseline.

### API Key
Read from environment variable `OPENAI_API_KEY`. Pipeline exits with a clear error message if not set.

### Deterministic Question Selection
```python
random.seed(args.seed)
random.shuffle(contents)
questions = contents[:args.n]
```
Same seed → same N questions every run. All three approaches run on the identical question set.

---

## 6. OpenAI / AutoGen Configuration

### Standard OpenAI (replaces Azure)

```python
# config.py
def openai_config(model, api_key):
    return {
        "model": model,
        "api_key": api_key,
        "api_type": "openai",
    }

def llm_config_list(seed, config_list):
    return {
        "functions": [...],
        "config_list": config_list,
        "timeout": 120,
        "cache_seed": seed,   # prevents duplicate API calls for identical prompts
        "temperature": 0,
    }
```

### Direct LLM calls (medagent.py: retrieve_knowledge, error_debugger)
```python
from openai import OpenAI
client = OpenAI(api_key=api_key)   # single client instance, passed in at construction
response = client.chat.completions.create(
    model=model,
    messages=messages,
    temperature=0,
    max_tokens=800,
)
```
All dead v0.x assignments (`openai.api_type = ...`, `openai.api_base = ...`) are removed.

---

## 7. TabTools Path Configuration

`tabtools.py` currently has hardcoded `<YOUR_DATASET_PATH>` strings. A module-level global is injected at pipeline startup:

```python
# tabtools.py
_DATASET_PATH = None
_DATASET = None

def configure(dataset_path, dataset):
    global _DATASET_PATH, _DATASET
    _DATASET_PATH = dataset_path
    _DATASET = dataset

def db_loader(target_ehr):
    # builds path from _DATASET_PATH and _DATASET at call time
    ...
```

`pipeline.py` calls `tabtools.configure(args.dataset_path, args.dataset)` before any agent runs.

---

## 8. Compiler Agent Prompt Design

### System Message (both Approach 1 CompilerAgent and Approach 2 CompilerDebuggerAgent)
```
You are a code execution simulator for an EHR (Electronic Health Record) query system.
You receive Python code that uses EHR API functions and simulate what would happen if
it were executed. You know the full table and column schema but have NO access to actual
patient data.

Check for:
- Wrong table names passed to LoadDB()
- Wrong column names passed to FilterDB() or GetValue()
- Wrong argument format for any API function
- SQL syntax errors or wrong column/table names in SQLInterpreter()
- Any other obvious code errors

Always respond with EXACTLY [SUCCESS] or [ERROR] on the first line, followed by either
your simulated result (for SUCCESS) or the predicted error message (for ERROR).
```

### Approach 2 addition to system message
```
If you find an error, also provide a suggested fix on a new line prefixed with:
"Suggested fix: "
```

### Few-Shot Examples
4 examples total per dataset (mimic_iii and eicu have separate prompt files):

**Examples 1 & 2 — SUCCESS cases:**  
Taken from the 2 API-style examples in `EHRAgent_4Shots_Knowledge` (the LoadDB/FilterDB/GetValue ones, not the SQL ones). Run through the real `run_code()` during baseline build to capture the exact result strings.

**Examples 3 & 4 — ERROR cases:**  
Placeholders. Populated after the user runs Approach 3 baseline and inspects `errors.json`. Pick 2 real failures where:
- The code is clearly wrong (wrong column name, wrong table, bad argument)
- The error message from `run_code()` is short and informative

`errors.json` captures both the last code generated AND the exact `run_code()` error string, making it straightforward to copy these directly into the prompt.

### Prompt Template (per call)
```
{system_message}

Here are examples of how to evaluate code:

{few_shot_examples}

Now evaluate the following code written to answer this question:
Question: {question}

Code:
{code}

Respond with [SUCCESS] or [ERROR] followed by the result or error message.
```

---

## 9. MedAgent Modifications

### execute_function() — Approach 1 hook
```python
def execute_function(self, func_call):
    # ... parse arguments, extract code (same as now) ...

    if self.mode == 'compiler_agent':
        compiler_response = self.compiler_agent.evaluate(self.question, code)
        if compiler_response.startswith('[ERROR]'):
            # send to debugger, get reason, return to coding agent
            error_msg = compiler_response[len('[ERROR]'):].strip()
            reasons = self.error_debugger(self.config_list[0], code, error_msg)
            return False, {"name": func_name, "role": "function",
                           "content": error_msg + '\nPotential Reasons: ' + reasons}
        else:
            # [SUCCESS] — run real code
            content = run_code(code)
            if 'error' in content.lower():
                # real exec failed — incompleted, raise to break the loop
                raise CompilerSuccessButExecFailed(content)
            return True, {"name": func_name, "role": "function", "content": content}

    elif self.mode == 'newdebugger':
        compiler_response = self.compiler_debugger_agent.evaluate(self.question, code)
        if compiler_response.startswith('[ERROR]'):
            error_msg = compiler_response[len('[ERROR]'):].strip()
            return False, {"name": func_name, "role": "function", "content": error_msg}
        else:
            content = run_code(code)
            if 'error' in content.lower():
                raise CompilerSuccessButExecFailed(content)
            return True, {"name": func_name, "role": "function", "content": content}

    else:
        # Approach 3: original behavior
        content = func(**arguments)
        if 'error' in content or 'Error' in content:
            reasons = self.error_debugger(...)
            content = content + '\nPotential Reasons: ' + reasons
        return True, {"name": func_name, "role": "function", "content": content}
```

`CompilerSuccessButExecFailed` is a custom exception caught in `pipeline.py`'s per-question try/except, which marks the question as INCOMPLETED.

---

## 10. Output Structure

### Run folder naming
```
run_20260521_143022_mimic_iii_compiler_agent_n30
run_20260521_144500_mimic_iii_baseline_n30
run_20260521_145200_eicu_newdebugger_n30
```

### results.json
One entry per question:
```json
[
  {
    "id": "0d92a1f6eab9515735f242f4",
    "question": "what is the intake method of lidocaine 5% ointment?",
    "ground_truth": "tp",
    "predicted_answer": "tp",
    "is_correct": true,
    "status": "correct",
    "num_tries": 1,
    "agent_trace": [
      "Code attempt 1:\n<code here>",
      "Compiler/Executor response:\n<response here>",
      "..."
    ]
  }
]
```

`status` is one of: `correct`, `wrong`, `incompleted`.

`agent_trace` contains the full agent message sequence with the **examples section stripped** — everything from the start of the initial message up to and including `(END OF EXAMPLES)` is removed before saving.

### errors.json
Same format as `results.json` but only entries where `status` is `wrong` or `incompleted`.  
Critically includes `last_code` and `last_error` fields at the top level for easy copy-paste into Compiler Agent few-shot examples:
```json
{
  "id": "...",
  "question": "...",
  "ground_truth": "...",
  "predicted_answer": "...",
  "status": "wrong",
  "last_code": "<the last code block the agent generated>",
  "last_error": "<the exact string run_code() returned>",
  "agent_trace": [...]
}
```

### summary_plot.png
Horizontal bar chart with 4 bars:
- **Correct** — questions answered correctly
- **Wrong** — questions where agent answered but answer was wrong
- **Incompleted** — hit max retries OR crashed
- **Total tries** — sum of `num_tries` across all questions (shows retry cost)

---

## 11. Build Order

1. **Approach 3 baseline** first — gets the pipeline infrastructure working end-to-end with standard OpenAI API, correct tabtools paths, output folder, results.json, errors.json, bar chart.
2. **User runs Approach 3** on 30 questions, inspects `errors.json`, picks 2 real error examples.
3. **Approaches 1 & 2** built — Compiler Agent prompt filled with those 2 real errors + 2 real successes from the known-good examples.

---

## 12. Key Implementation Notes

- `run_code()` in `toolset_high.py` is used unchanged for real execution in all three approaches.
- `cache_seed=42` in autogen llm_config prevents repeat API calls for identical prompts across runs.
- The Compiler Agent makes a single `client.chat.completions.create()` call per code attempt — no autogen agent wrapping needed, just a direct OpenAI call.
- The `error_debugger()` in `medagent.py` is reused as-is for Approach 1's Debugger Agent step.
- For Approach 2, the `CompilerDebuggerAgent.evaluate()` response replaces both the compiler check AND the debugger explanation in a single call.
