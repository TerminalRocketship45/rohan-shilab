"""
Token counter for EHRAgent runs.
Estimates input/output tokens from all agent traces and API calls.
"""

import json
import os
import re

# Approximate token counting without tiktoken (4 chars ~= 1 token for English)
def count_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(str(text)) // 4)

# ─── Prompt templates (from prompts_mimic.py) ────────────────────────────────
RETR_KNOWLEDGE_PREFIX = """Read the following data descriptions, generate the background knowledge as the context information that could be helpful for answering the question.
(1) Tables are linked by identifiers which usually have the suffix 'ID'. For example, SUBJECT_ID refers to a unique patient, HADM_ID refers to a unique admission to the hospital, and ICUSTAY_ID refers to a unique admission to an intensive care unit.
(2) Charted events such as notes, laboratory tests, and fluid balance are stored in a series of 'events' tables. For example the outputevents table contains all measurements related to output for a given patient, while the labevents table contains laboratory test results for a patient.
(3) Tables prefixed with 'd_' are dictionary tables and provide definitions for identifiers. For example, every row of chartevents is associated with a single ITEMID which represents the concept measured, but it does not contain the actual name of the measurement. By joining chartevents and d_items on ITEMID, it is possible to identify the concept represented by a given ITEMID.
(4) For the databases, four of them are used to define and track patient stays: admissions, patients, icustays, and transfers. Another four tables are dictionaries for cross-referencing codes against their respective definitions: d_icd_diagnoses, d_icd_procedures, d_items, and d_labitems. The remaining tables, including chartevents, cost, inputevents_cv, labevents, microbiologyevents, outputevents, prescriptions, procedures_icd, contain data associated with patient care, such as physiological measurements, caregiver observations, and billing information.
For different tables, they contain the following information:
(1) admissions: ROW_ID, SUBJECT_ID, HADM_ID, ADMITTIME, DISCHTIME, ADMISSION_TYPE, ADMISSION_LOCATION, DISCHARGE_LOCATION, INSURANCE, LANGUAGE, MARITAL_STATUS, ETHNICITY, AGE
(2) chartevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM
(3) cost: ROW_ID, SUBJECT_ID, HADM_ID, EVENT_TYPE, EVENT_ID, CHARGETIME, COST
(4) d_icd_diagnoses: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE
(5) d_icd_procedures: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE
(6) d_items: ROW_ID, ITEMID, LABEL, LINKSTO
(7) d_labitems: ROW_ID, ITEMID, LABEL
(8) dianoses_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME
(9) icustays: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, FIRST_CAREUNIT, LAST_CAREUNIT, FIRST_WARDID, LAST_WARDID, INTIME, OUTTIME
(10) inputevents_cv: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, AMOUNT
(11) labevents: ROW_ID, SUBJECT_ID, HADM_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM
(12) microbiologyevents: RROW_ID, SUBJECT_ID, HADM_ID, CHARTTIME, SPEC_TYPE_DESC, ORG_NAME
(13) outputevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, VALUE
(14) patients: ROW_ID, SUBJECT_ID, GENDER, DOB, DOD
(15) prescriptions: ROW_ID, SUBJECT_ID, HADM_ID, STARTDATE, ENDDATE, DRUG, DOSE_VAL_RX, DOSE_UNIT_RX, ROUTE
(16) procedures_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME
(17) transfers: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, EVENTTYPE, CAREUNIT, WARDID, INTIME, OUTTIME

Question: {question}
Knowledge:
"""

SYSTEM_PROMPT = """You are a helpful AI assistant. Solve tasks using your coding and language skills.
In the following cases, suggest python code (in a python coding block) or shell script (in a sh
coding block) for the user to execute.
1. When you need to collect info, use the code to output the info you need, for example, browse or
search the web, download/read a file, print the content of a webpage or a file, get the current
date/time. After sufficient info is printed and the task is ready to be solved based on your
language skill, you can solve the task by yourself.
2. When you need to perform some task with code, use the code to perform the task and output the
result. Finish the task smartly.
Solve the task step by step if you need to. If a plan is not provided, explain your plan first. Be
clear which step uses code, and which step uses your language skill.
When using code, you must indicate the script type in the code block. The user cannot provide any
other feedback or perform any other action beyond executing the code you suggest. The user can't
modify your code. So do not suggest incomplete code which requires users to modify. Don't use a
code block if it's not intended to be executed by the user.
If you want the user to save the code in a file before executing it, put # filename: <filename>
inside the code block as the first line. Don't include multiple code blocks in one response. Do not
ask users to copy and paste the result. Instead, use 'print' function for the output when relevant.
Check the execution result returned by the user.
If the result indicates there is an error, fix the error and output the code again. Suggest the
full code instead of partial code or code changes. If the error can't be fixed or if the task is
not solved even after the code is executed successfully, analyze the problem, revisit your
assumption, collect additional info you need, and think of a different approach to try.
When you find an answer, verify the answer carefully. Include verifiable evidence in your response if possible."""

DEBUGGER_SYSTEM = "You are an AI assistant that helps people debug their code. Only list one most possible reason to the errors."
KNOWLEDGE_SYSTEM = "You are an AI assistant that helps people find information."

def analyze_results(results, run_name, mode="baseline"):
    """
    Analyze token usage from a results list.

    Each question's agent_trace alternates:
      [0] = initial message (user sends knowledge+question+examples)
      [1] = LLM response (code attempt 1)
      [2] = execution result (user sends back)
      [3] = LLM response (code attempt 2 or TERMINATE)
      ...

    For each LLM call:
      - Input = system_prompt + all prior messages in conversation
      - Output = the LLM response content

    Additional per-question API calls:
      - 1x knowledge retrieval (input = RETR_KNOWLEDGE prompt, output = knowledge text)
      - 1x error_debugger per failed attempt (input = CodeDebugger prompt, output = reasons)
    """
    total_input = 0
    total_output = 0

    system_tokens = count_tokens(SYSTEM_PROMPT)
    knowledge_system_tokens = count_tokens(KNOWLEDGE_SYSTEM)
    debugger_system_tokens = count_tokens(DEBUGGER_SYSTEM)

    skipped = 0
    processed = 0

    for item in results:
        trace = item.get("agent_trace", [])
        question = item.get("question", "")
        status = item.get("status", "")

        # Skip runs that failed immediately (no API calls made)
        if status == "incompleted" and len(trace) <= 1:
            skipped += 1
            continue
        if not trace:
            skipped += 1
            continue

        processed += 1

        # ── 1. Knowledge retrieval call ──────────────────────────────────────
        retr_input = RETR_KNOWLEDGE_PREFIX.format(question=question)
        retr_input_tokens = knowledge_system_tokens + count_tokens(retr_input)
        # Knowledge output is the first part of trace[0] (before "Question:")
        # Approximate from trace[0] knowledge section
        knowledge_text = ""
        if trace and "Knowledge:" in str(trace[0]):
            knowledge_text = str(trace[0]).split("Knowledge:")[1].split("Question:")[0]
        retr_output_tokens = count_tokens(knowledge_text) if knowledge_text else 100

        total_input += retr_input_tokens
        total_output += retr_output_tokens

        # ── 2. AutoGen conversation calls ────────────────────────────────────
        # The trace is: [initial_msg, llm_response1, exec_result1, llm_response2, ...]
        # We simulate the growing conversation history.

        # Identify which trace entries are "user" (input) vs "assistant" (output)
        # trace[0] = initial user message
        # trace[1] = LLM code response
        # trace[2] = execution result (user)
        # trace[3] = LLM response
        # etc.

        conversation_history = []  # list of (role, content) tuples

        i = 0
        while i < len(trace):
            entry = str(trace[i])

            if i == 0:
                # Initial user message
                conversation_history.append(("user", entry))
                i += 1
            elif i % 2 == 1:
                # LLM response (output) — this is what the model generates
                # Input = system + all prior conversation
                input_tokens = system_tokens
                for role, content in conversation_history:
                    input_tokens += count_tokens(content)

                output_tokens = count_tokens(entry)

                total_input += input_tokens
                total_output += output_tokens

                conversation_history.append(("assistant", entry))
                i += 1
            else:
                # Execution result (user sends back)
                # This also triggers error_debugger call if there's an error
                if "Error:" in entry or "error" in entry.lower()[:50]:
                    # error_debugger is called: input = CodeDebugger prompt
                    # We estimate ~500 tokens for the CodeDebugger prompt + code + error
                    debug_input_tokens = debugger_system_tokens + count_tokens(entry) + 200
                    debug_output_tokens = 100  # typical short explanation
                    total_input += debug_input_tokens
                    total_output += debug_output_tokens

                    # The debug reasons are appended to the entry before sending back
                    entry = entry + "\nPotential Reasons: [~100 token explanation]"

                conversation_history.append(("user", entry))
                i += 1

    return total_input, total_output, processed, skipped


def main():
    base_dir = r"C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehragent\outputs"

    grand_total_input = 0
    grand_total_output = 0
    all_runs = []

    print("=" * 70)
    print("EHRAgent Token Usage Analysis")
    print("=" * 70)

    # ── Scan all run_* directories ────────────────────────────────────────────
    run_dirs = [
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d))
        and d.startswith("run_")
    ]

    for run_dir in sorted(run_dirs):
        results_path = os.path.join(base_dir, run_dir, "results.json")
        if not os.path.exists(results_path):
            continue

        with open(results_path) as f:
            results = json.load(f)

        # Extract mode from folder name
        mode = "baseline"
        if "compiler_agent" in run_dir:
            mode = "compiler_agent"
        elif "newdebugger" in run_dir or "debugger" in run_dir:
            mode = "newdebugger"

        inp, out, processed, skipped = analyze_results(results, run_dir, mode)
        grand_total_input += inp
        grand_total_output += out

        print(f"\nRun: {run_dir}")
        print(f"  Mode: {mode} | Questions processed: {processed} | Skipped: {skipped}")
        print(f"  Input tokens:  {inp:>10,}")
        print(f"  Output tokens: {out:>10,}")
        all_runs.append((run_dir, mode, processed, skipped, inp, out))

    # ── Scan 20260530_201842 (raw_results.json with 3 modes) ─────────────────
    raw_path = os.path.join(base_dir, "20260530_201842", "raw_results.json")
    if os.path.exists(raw_path):
        with open(raw_path) as f:
            raw = json.load(f)

        print(f"\nRun: 20260530_201842 (multi-mode raw results)")
        for mode_key in ["baseline", "compiler_agent", "newdebugger"]:
            if mode_key in raw:
                results = raw[mode_key]
                inp, out, processed, skipped = analyze_results(results, "20260530_201842", mode_key)
                grand_total_input += inp
                grand_total_output += out
                print(f"  [{mode_key}] Questions: {processed} | Skipped: {skipped}")
                print(f"    Input tokens:  {inp:>10,}")
                print(f"    Output tokens: {out:>10,}")

    # ── Single test file ──────────────────────────────────────────────────────
    single_test_path = os.path.join(base_dir, "single_test_20260530_194113.md")
    if os.path.exists(single_test_path):
        with open(single_test_path) as f:
            content = f.read()
        est_tokens = count_tokens(content)
        # Rough split: single question trace
        single_in = est_tokens * 2  # accumulating input
        single_out = est_tokens // 3
        grand_total_input += single_in
        grand_total_output += single_out
        print(f"\nRun: single_test_20260530_194113.md")
        print(f"  Input tokens (est):  {single_in:>10,}")
        print(f"  Output tokens (est): {single_out:>10,}")

    # ── Grand totals ──────────────────────────────────────────────────────────
    grand_total = grand_total_input + grand_total_output

    print("\n" + "=" * 70)
    print("TOTALS ACROSS ALL RUNS")
    print("=" * 70)
    print(f"  Total input tokens:  {grand_total_input:>12,}")
    print(f"  Total output tokens: {grand_total_output:>12,}")
    print(f"  GRAND TOTAL tokens:  {grand_total:>12,}")

    # ── GPT-4 pricing (as of 2025) ────────────────────────────────────────────
    # GPT-4 (8k context):   $0.03/1K input,  $0.06/1K output
    # GPT-4 (32k context):  $0.06/1K input,  $0.12/1K output
    # GPT-4o:               $0.005/1K input, $0.015/1K output
    # GPT-4 Turbo:          $0.01/1K input,  $0.03/1K output

    print("\n" + "-" * 70)
    print("COST ESTIMATES (GPT-4 variants)")
    print("-" * 70)

    models = [
        ("GPT-4 (8k)",    0.03,   0.06),
        ("GPT-4 (32k)",   0.06,   0.12),
        ("GPT-4 Turbo",   0.01,   0.03),
        ("GPT-4o",        0.005,  0.015),
        ("GPT-4o mini",   0.00015, 0.0006),
    ]

    for name, input_price, output_price in models:
        cost = (grand_total_input / 1000 * input_price) + (grand_total_output / 1000 * output_price)
        print(f"  {name:<18} ${cost:>8.4f}  (${input_price}/1K in, ${output_price}/1K out)")

    print("\n  Note: Token counts are estimated via character-count proxy (~4 chars/token).")
    print("  Actual usage depends on tokenizer, prompt padding, and API overhead.")
    print("  The AutoGen framework sends the full conversation history each turn,")
    print("  which is accounted for in the cumulative input estimation above.")


if __name__ == "__main__":
    main()
