import json

runs = {
    "baseline":       r"C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehragent\outputs\run_20260521_185004_mimic_iii_baseline_n30_seed42\results.json",
    "compiler_agent": r"C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehragent\outputs\run_20260521_193940_mimic_iii_compiler_agent_n30_seed42\results.json",
    "newdebugger":    r"C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehragent\outputs\run_20260521_212530_mimic_iii_newdebugger_n30_seed42\results.json",
}
data = {k: {r["question"]: r for r in json.load(open(v))} for k, v in runs.items()}

selected = [
    "what does periph t cell lym abdom stand for?",
    "has patient 9474 received any diagnosis since 1 year ago?",
    "count the number of patients who were admitted to the hospital until 3 year ago.",
    "count the number of patients who were dead after having been diagnosed with dmii wo cmp nt st uncntr within the same hospital visit since 6 year ago.",
]


def parse_attempts(trace):
    knowledge = trace[0].strip() if trace else ""
    attempts = []
    i = 1
    while i + 1 < len(trace):
        attempts.append((trace[i].strip(), trace[i + 1].strip()))
        i += 2
    return knowledge, attempts


def split_compiler_debugger(response):
    if "Potential Reasons:" in response:
        parts = response.split("Potential Reasons:", 1)
        return parts[0].strip(), parts[1].strip()
    return response, None


lines = []
lines.append("# EHRAgent Pipeline Comparison — Case Studies")
lines.append("")
lines.append("**Dataset:** mimic_iii | **n=30** | **seed=42** | **Model:** gpt-4o-mini")
lines.append("")
lines.append("Four questions chosen to show how each approach differs in behavior and outcome.")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## Summary")
lines.append("")
lines.append("| Question | Baseline | Compiler Agent | New Debugger |")
lines.append("|----------|----------|----------------|--------------|")

for q in selected:
    b  = data["baseline"].get(q, {})
    ca = data["compiler_agent"].get(q, {})
    nd = data["newdebugger"].get(q, {})

    def fmt(r):
        if not r:
            return "—"
        return f'{r["status"].upper()} ({r["num_tries"]} tries)'

    short_q = (q[:55] + "...") if len(q) > 55 else q
    lines.append(f"| {short_q} | {fmt(b)} | {fmt(ca)} | {fmt(nd)} |")

lines.append("")
lines.append("---")
lines.append("")

for case_num, q in enumerate(selected, 1):
    b  = data["baseline"].get(q)
    ca = data["compiler_agent"].get(q)
    nd = data["newdebugger"].get(q)

    lines.append(f'## Case {case_num}: "{q}"')
    lines.append("")
    lines.append(f'**Ground truth:** `{b["ground_truth"]}`')
    lines.append("")

    # ── APPROACH 3: BASELINE ──────────────────────────────────────────────────
    lines.append("### Approach 3 — Baseline")
    lines.append("")
    lines.append(f'**Status:** {b["status"].upper()} | **Tries:** {b["num_tries"]}')
    lines.append("")
    b_knowledge, b_attempts = parse_attempts(b["agent_trace"])
    lines.append("**Knowledge retrieved:**")
    lines.append("```")
    lines.append(b_knowledge[:600])
    lines.append("```")
    lines.append("")
    for i, (code, response) in enumerate(b_attempts[:3], 1):
        lines.append(f"**Attempt {i} — Code:**")
        lines.append("```python")
        lines.append(code[:900])
        lines.append("```")
        lines.append("")
        lines.append("**run_code() result:**")
        lines.append("```")
        lines.append(response[:500])
        lines.append("```")
        lines.append("")
    if len(b_attempts) > 3:
        lines.append(f"*...{len(b_attempts) - 3} more attempt(s) omitted...*")
        lines.append("")

    # ── APPROACH 1: COMPILER AGENT ────────────────────────────────────────────
    lines.append("### Approach 1 — Compiler Agent")
    lines.append("")
    lines.append(f'**Status:** {ca["status"].upper()} | **Tries:** {ca["num_tries"]}')
    lines.append("")
    _, ca_attempts = parse_attempts(ca["agent_trace"])
    for i, (code, response) in enumerate(ca_attempts[:3], 1):
        compiler_msg, debugger_msg = split_compiler_debugger(response)
        lines.append(f"**Attempt {i} — Code sent to Compiler Agent:**")
        lines.append("```python")
        lines.append(code[:900])
        lines.append("```")
        lines.append("")
        if debugger_msg is not None:
            lines.append("**Compiler Agent → [ERROR]:**")
            lines.append("```")
            lines.append(compiler_msg[:500])
            lines.append("```")
            lines.append("")
            lines.append("**Debugger Agent explanation (sent back to Coding Agent):**")
            lines.append("```")
            lines.append(debugger_msg[:500])
            lines.append("```")
        else:
            lines.append("**Compiler Agent → [SUCCESS] — run_code() result:**")
            lines.append("```")
            lines.append(compiler_msg[:500])
            lines.append("```")
        lines.append("")
    if len(ca_attempts) > 3:
        lines.append(f"*...{len(ca_attempts) - 3} more attempt(s) omitted (all [ERROR] loops)...*")
        lines.append("")

    # ── APPROACH 2: NEW DEBUGGER ──────────────────────────────────────────────
    lines.append("### Approach 2 — New Debugger")
    lines.append("")
    lines.append(f'**Status:** {nd["status"].upper()} | **Tries:** {nd["num_tries"]}')
    lines.append("")
    _, nd_attempts = parse_attempts(nd["agent_trace"])
    for i, (code, response) in enumerate(nd_attempts[:3], 1):
        lines.append(f"**Attempt {i} — Code sent to CompilerDebugger Agent:**")
        lines.append("```python")
        lines.append(code[:900])
        lines.append("```")
        lines.append("")
        if "Suggested fix" in response:
            lines.append("**CompilerDebugger → [ERROR] + fix suggestion:**")
        else:
            lines.append("**CompilerDebugger → [SUCCESS] — run_code() result:**")
        lines.append("```")
        lines.append(response[:600])
        lines.append("```")
        lines.append("")
    # handle incompleted (no attempts extracted)
    if nd["status"] == "incompleted" and len(nd_attempts) == 0:
        lines.append("*Pipeline marked INCOMPLETED: Compiler Agent said [SUCCESS] but real execution")
        lines.append("failed with a patient-data-containing error. Error was NOT fed back to AI.*")
        lines.append("")
        lines.append(f'**Internal last_error (not shown to AI):** `{nd["last_error"][:200]}`')
        lines.append("")
    elif len(nd_attempts) > 3:
        lines.append(f"*...{len(nd_attempts) - 3} more attempt(s) omitted...*")
        lines.append("")

    lines.append("---")
    lines.append("")

out_path = r"C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehragent\outputs\pipeline_comparison.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Written:", out_path)
