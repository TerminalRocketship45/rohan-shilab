"""
Run all three pipeline approaches (baseline, compiler_agent, newdebugger) on N questions
and write a structured output folder with per-question traces + full analysis visuals.

Usage:
    python run_pipeline.py --n 10
    python run_pipeline.py --n 30 --model gpt-4 --seed 42
    python run_pipeline.py --n -1   # all questions (minus few-shot exclusions)

Output structure:
    outputs/<YYYY-MM-DD_HH-MM-SS>/
        summary.md
        per_question_comparison.png   -- line plot, outcome per question
        baseline_agreement.png        -- bar: % of questions matching baseline answer
        status_breakdown.png          -- stacked bars: correct/wrong/incompleted per approach
        error_breakdown.png           -- categorised failure types per approach
        q01_<id>/trace.md
        q02_<id>/trace.md
        ...
"""
import os
import sys
import json
import random
import warnings
import argparse
import re
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import autogen
from medagent import MedAgent
from config import openai_config, llm_config_list
from compiler_agent import CompilerAgent, CompilerDebuggerAgent, CompilerSuccessButExecFailed
from toolset_high import run_code
import tools.tabtools as tabtools

DATASET = "mimic_iii"
DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "ehrsql-ehragent", "ehrsql-ehragent",
)
OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
NUM_SHOTS = 4
MAX_TRIES = 11

APPROACHES = ["baseline", "compiler_agent", "newdebugger"]
APPROACH_LABELS = {
    "baseline":       "Baseline",
    "compiler_agent": "Compiler Agent",
    "newdebugger":    "New Debugger",
}
APPROACH_COLORS = {
    "baseline":       "#2196F3",
    "compiler_agent": "#F44336",
    "newdebugger":    "#FF9800",
}

STATUS_EMOJI = {"correct": "✅", "wrong": "❌", "incompleted": "⚠️"}


# ── Few-shot question extraction ──────────────────────────────────────────────────

def extract_fewshot_questions():
    from prompts_mimic import EHRAgent_4Shots_Knowledge, CompilerAgent_FewShot_Examples
    questions = set()
    for block in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        m = re.search(r"Question:\s*(.+?)(?:\nKnowledge:|\Z)", block, re.DOTALL)
        if m:
            questions.add(m.group(1).strip().lower())
    for line in CompilerAgent_FewShot_Examples.split("\n"):
        if line.startswith("Question:"):
            questions.add(line[len("Question:"):].strip().lower())
    return questions


# ── Judge ─────────────────────────────────────────────────────────────────────────

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
    if ans in ("False", "false"): ans = "0"
    if ans in ("True",  "true"):  ans = "1"
    if ans in ("No",    "no"):    ans = "0"
    if ans in ("Yes",   "yes"):   ans = "1"
    if ans in ("None",  "none"):  ans = "0"
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


# ── Baseline-agreement match logic ────────────────────────────────────────────────

def matches_baseline(baseline_r, new_r):
    """
    True if new_r produced the same answer as baseline_r, treating baseline as GT.

    Rules:
      - Both correct                  → match (multiple valid formats exist)
      - Both wrong                    → judge(new_pred, baseline_pred) bidirectional
      - Both incompleted, same reason → match
      - Any other combination         → no match
    """
    bs, ns = baseline_r["status"], new_r["status"]

    if bs == "correct" and ns == "correct":
        return True

    if bs == "wrong" and ns == "wrong":
        bp = baseline_r.get("predicted_answer", "")
        np_ = new_r.get("predicted_answer", "")
        # Bidirectional: handles cases where one contains the other
        return judge(np_, bp) or judge(bp, np_)

    if bs == "incompleted" and ns == "incompleted":
        return baseline_r.get("incompleted_reason") == new_r.get("incompleted_reason")

    return False


# ── Error categorisation ──────────────────────────────────────────────────────────

ERROR_CATEGORIES = [
    "Compiler false positive (silenced)",
    "Wrong column name",
    "Invalid separator (&&/AND)",
    "SQL subquery in FilterDB",
    "Hit max tries",
    "No error info",
    "Other",
]


def categorize_error(r):
    """Return an error category string for a wrong/incompleted result."""
    if r["status"] not in ("wrong", "incompleted"):
        return None

    if r.get("incompleted_reason") == "compiler_success_exec_failed":
        return "Compiler false positive (silenced)"

    err = r.get("last_error", "")
    err_lower = err.lower()

    if "&&" in err or (re.search(r"\bAND\b", err) and "incorrect" in err_lower):
        return "Invalid separator (&&/AND)"

    if ("column" in err_lower or "no such column" in err_lower) and \
       ("incorrect" in err_lower or "does not exist" in err_lower or "no such" in err_lower):
        return "Wrong column name"

    if "select" in err_lower and ("filterdb" in err_lower or "subquery" in err_lower
                                   or "incorrect" in err_lower):
        return "SQL subquery in FilterDB"

    if r.get("num_tries", 0) >= MAX_TRIES:
        return "Hit max tries"

    if not err.strip():
        return "No error info"

    return "Other"


# ── Agent construction ────────────────────────────────────────────────────────────

def build_agents(model, api_key, seed, mode):
    cfg = openai_config(model, api_key)
    llm_cfg = llm_config_list(seed, [cfg])

    chatbot = autogen.agentchat.AssistantAgent(
        name="chatbot",
        system_message=(
            "For coding tasks, only use the functions you have been provided with. "
            "Reply TERMINATE when the task is done. Save the answers to the questions "
            "in the variable 'answer'. Please only generate the code."
        ),
        llm_config=llm_cfg,
    )

    user_proxy = MedAgent(
        name="user_proxy",
        api_key=api_key,
        model=model,
        is_termination_msg=lambda x: x.get("content", "") and
                                     x.get("content", "").rstrip().endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={"work_dir": "coding", "use_docker": False},
    )
    user_proxy.register_function(function_map={"python": run_code})
    user_proxy.register_dataset(DATASET)

    if mode == "compiler_agent":
        from prompts_mimic import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        ca = CompilerAgent(
            api_key=api_key, model=model, dataset=DATASET,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerAgent_System_Message,
        )
        user_proxy.set_mode("compiler_agent", compiler_agent=ca)

    elif mode == "newdebugger":
        from prompts_mimic import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples
        cda = CompilerDebuggerAgent(
            api_key=api_key, model=model, dataset=DATASET,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerDebuggerAgent_System_Message,
        )
        user_proxy.set_mode("newdebugger", compiler_debugger_agent=cda)

    return user_proxy, chatbot


# ── Run single question ───────────────────────────────────────────────────────────

def run_question(user_proxy, chatbot, item, long_term_memory):
    question = item["template"]
    answer   = item["answer"]
    gt_answer = answer if isinstance(answer, str) else ", ".join(answer)

    result = {
        "id":                item.get("id", ""),
        "question":          question,
        "ground_truth":      gt_answer,
        "predicted_answer":  "",
        "last_exec_result":  "",
        "is_correct":        False,
        "status":            "incompleted",
        "incompleted_reason": None,   # "compiler_success_exec_failed" | "exception" | None
        "num_tries":         0,
        "last_code":         "",
        "last_error":        "",
        "agent_trace":       [],
    }

    try:
        user_proxy.update_memory(NUM_SHOTS, long_term_memory)
        user_proxy.initiate_chat(chatbot, message=question)

        logs = user_proxy.chat_messages
        trace, num_tries, last_code, last_error = [], 0, "", ""

        def _extract_code(arguments):
            if isinstance(arguments, dict):
                return arguments.get("cell", str(arguments))
            try:
                parsed = json.loads(arguments)
                return parsed.get("cell", str(parsed))
            except Exception:
                return str(arguments)

        for agent in list(logs.keys()):
            for msg in logs[agent]:
                content = msg.get("content")
                if content is not None and content != "":
                    cleaned = strip_examples(str(content))
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
        result["num_tries"]   = max(num_tries, 1)
        result["last_code"]   = last_code
        result["last_error"]  = last_error

        exec_results = [trace[i].strip() for i in range(2, len(trace), 2)
                        if "TERMINATE" not in trace[i]]
        result["last_exec_result"] = exec_results[-1] if exec_results else ""

        logs_string = "\n".join(trace)
        term_idx = logs_string.rfind("TERMINATE")
        prediction_block = logs_string[:term_idx] if term_idx != -1 else logs_string

        is_correct = judge(prediction_block, gt_answer)
        result["predicted_answer"] = prediction_block.strip().split("\n")[-1]
        result["is_correct"]       = is_correct
        result["status"]           = "correct" if is_correct else "wrong"
        # Not incompleted — reason stays None

    except CompilerSuccessButExecFailed as e:
        result["status"]            = "incompleted"
        result["incompleted_reason"] = "compiler_success_exec_failed"
        result["last_error"]        = str(e)
        result["last_exec_result"]  = str(e)
        result["agent_trace"].append("[INCOMPLETED: compiler said SUCCESS but real exec failed]")

    except Exception as e:
        result["status"]            = "incompleted"
        result["incompleted_reason"] = "exception"
        result["last_error"]        = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: exception] {e}")

    return result


# ── Run one approach across all questions ─────────────────────────────────────────

def run_approach(questions, mode, model, api_key, seed, long_term_memory_base):
    print(f"\n{'='*60}\n  APPROACH: {APPROACH_LABELS[mode]}\n{'='*60}")
    user_proxy, chatbot = build_agents(model, api_key, seed, mode)
    long_term_memory = list(long_term_memory_base)
    results = []

    for i, item in enumerate(questions):
        print(f"  [{i+1}/{len(questions)}] {item['template'][:70]}...")
        result = run_question(user_proxy, chatbot, item, long_term_memory)
        results.append(result)

        if result["status"] == "correct" and result["last_code"]:
            long_term_memory.append({
                "question": item["template"],
                "knowledge": user_proxy.knowledge,
                "code":     result["last_code"],
            })

        print(f"    -> {result['status'].upper()} | tries={result['num_tries']}"
              + (f" | reason={result['incompleted_reason']}" if result["status"] == "incompleted" else ""))

    correct = sum(1 for r in results if r["status"] == "correct")
    print(f"  Done: {correct}/{len(questions)} correct")
    return results


# ── Trace formatter ───────────────────────────────────────────────────────────────

def format_trace(trace):
    if not trace:
        return "(no trace captured)"
    lines = ["**[INITIAL MESSAGE]**", "```",
             (trace[0][:800] + "...") if len(trace[0]) > 800 else trace[0],
             "```", ""]
    i, attempt_num = 1, 1
    while i < len(trace):
        code_block = trace[i]         if i     < len(trace) else None
        exec_block = trace[i + 1]     if i + 1 < len(trace) else None
        lines.append(f"**[ATTEMPT {attempt_num}]**")
        if code_block is not None:
            lines += ["*Code submitted:*", "```python",
                      (code_block[:1200] + "...") if len(code_block) > 1200 else code_block,
                      "```"]
        if exec_block is not None:
            lbl = "Final reply" if "TERMINATE" in exec_block else "Execution result"
            lines += [f"*{lbl}:*", "```",
                      (exec_block[:800] + "...") if len(exec_block) > 800 else exec_block,
                      "```"]
        lines.append("")
        i += 2
        attempt_num += 1
    return "\n".join(lines)


# ── Per-question trace file ───────────────────────────────────────────────────────

def write_question_trace(q_dir, item, results_by_mode):
    gt = item["answer"] if isinstance(item["answer"], str) else ", ".join(item["answer"])
    q  = item["template"]

    b = results_by_mode["baseline"]

    lines = [
        f"# Question: {q}", "",
        f"**Ground truth:** `{gt}`", "",
        "## Summary", "",
        "| Approach | Status | Incompleted Reason | Tries | Last Exec Result | Correct? | Matches Baseline? |",
        "|----------|--------|--------------------|-------|-----------------|----------|-------------------|",
    ]
    for mode in APPROACHES:
        r = results_by_mode[mode]
        exec_res   = r["last_exec_result"].replace("|", "\\|")[:60]
        reason     = r.get("incompleted_reason") or "—"
        matches    = "—" if mode == "baseline" else ("YES" if matches_baseline(b, r) else "NO")
        lines.append(
            f"| {APPROACH_LABELS[mode]} | {r['status'].upper()} | {reason} | {r['num_tries']} "
            f"| `{exec_res}` | {'YES' if r['is_correct'] else 'NO'} | {matches} |"
        )

    lines += ["", "---", ""]

    for mode in APPROACHES:
        r = results_by_mode[mode]
        reason_str = f" | Incompleted reason: `{r['incompleted_reason']}`" if r["status"] == "incompleted" else ""
        matches_str = "" if mode == "baseline" else f" | Matches baseline: {'YES' if matches_baseline(b, r) else 'NO'}"
        lines += [
            f"## {APPROACH_LABELS[mode]}", "",
            f"**Status:** {r['status'].upper()} | **Tries:** {r['num_tries']} | "
            f"**Correct:** {'YES' if r['is_correct'] else 'NO'}{reason_str}{matches_str}", "",
            f"**Ground truth:** `{gt}`",
            f"**Last exec result:** `{r['last_exec_result'][:300]}`",
            f"**Predicted answer (last-line):** `{r['predicted_answer'][:200]}`",
            "",
            "### Full Trace", "",
            format_trace(r["agent_trace"]), "",
            "---", "",
        ]

    os.makedirs(q_dir, exist_ok=True)
    with open(os.path.join(q_dir, "trace.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Stats helpers ─────────────────────────────────────────────────────────────────

def _stats(results):
    n     = len(results)
    corr  = sum(1 for r in results if r["status"] == "correct")
    wrong = sum(1 for r in results if r["status"] == "wrong")
    incomp = sum(1 for r in results if r["status"] == "incompleted")
    hit   = sum(1 for r in results if r["num_tries"] >= MAX_TRIES)
    return dict(n=n, correct=corr, wrong=wrong, incompleted=incomp, hit_max=hit,
                accuracy=corr / n * 100, completion=(n - incomp) / n * 100)


def _agreement(baseline_results, new_results):
    """Return count and % of questions where new_results matches baseline_results."""
    matched = sum(1 for b, r in zip(baseline_results, new_results) if matches_baseline(b, r))
    return matched, matched / len(baseline_results) * 100


def _error_counts(results):
    """Return {category: count} for wrong/incompleted results."""
    counts = {c: 0 for c in ERROR_CATEGORIES}
    for r in results:
        cat = categorize_error(r)
        if cat:
            counts[cat] += 1
    return counts


# ── summary.md ────────────────────────────────────────────────────────────────────

def write_summary(run_dir, questions, all_results):
    stats = {mode: _stats(all_results[mode]) for mode in APPROACHES}
    base  = all_results["baseline"]

    lines = [
        "# EHRAgent Pipeline Analysis", "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Dataset:** {DATASET} | **n={len(questions)}**", "",
        "---", "", "## Accuracy vs Ground Truth", "",
        "| Metric | Baseline | Compiler Agent | New Debugger |",
        "|--------|----------|----------------|--------------|",
    ]
    for label, fn in [
        ("Correct",          lambda s: f"{s['correct']} ({s['accuracy']:.1f}%)"),
        ("Wrong",            lambda s: str(s['wrong'])),
        ("Incompleted",      lambda s: str(s['incompleted'])),
        ("  — compiler_success_exec_failed",
                             lambda s: str(sum(1 for r in all_results[_m]
                                               if r.get("incompleted_reason") == "compiler_success_exec_failed"))),
        ("  — exception",    lambda s: str(sum(1 for r in all_results[_m]
                                               if r.get("incompleted_reason") == "exception"))),
        ("Completion rate",  lambda s: f"{s['completion']:.1f}%"),
        (f"Hit max ({MAX_TRIES}t)", lambda s: str(s['hit_max'])),
    ]:
        row = f"| {label} |"
        for _m in APPROACHES:
            row += f" {fn(stats[_m])} |"
        lines.append(row)

    # Baseline-agreement table
    lines += ["", "---", "", "## Agreement with Baseline Answer", "",
              "> Baseline is treated as ground truth here, regardless of whether it was correct.",
              "> Two approaches 'match' when: both correct; both wrong with equivalent answer (judge); both incompleted with same reason.", "",
              "| Approach | Matched | Total | Agreement % |",
              "|----------|---------|-------|-------------|",
              "| Baseline | — | — | 100% (reference) |"]
    for mode in ["compiler_agent", "newdebugger"]:
        matched, pct = _agreement(base, all_results[mode])
        lines.append(f"| {APPROACH_LABELS[mode]} | {matched} | {len(questions)} | {pct:.1f}% |")

    # Per-question status
    lines += ["", "---", "", "## Per-Question Status", "",
              "| # | Question | Baseline | Compiler Agent | CA matches BL? | New Debugger | ND matches BL? |",
              "|---|----------|----------|----------------|----------------|--------------|----------------|"]
    for i, item in enumerate(questions):
        q_short = (item["template"][:50] + "...") if len(item["template"]) > 50 else item["template"]
        bl = all_results["baseline"][i]
        ca = all_results["compiler_agent"][i]
        nd = all_results["newdebugger"][i]
        bl_str = f"{STATUS_EMOJI.get(bl['status'],'?')} {bl['status']} ({bl['num_tries']}t)"
        ca_str = f"{STATUS_EMOJI.get(ca['status'],'?')} {ca['status']} ({ca['num_tries']}t)"
        nd_str = f"{STATUS_EMOJI.get(nd['status'],'?')} {nd['status']} ({nd['num_tries']}t)"
        ca_match = "YES" if matches_baseline(bl, ca) else "NO"
        nd_match = "YES" if matches_baseline(bl, nd) else "NO"
        lines.append(f"| {i+1} | {q_short} | {bl_str} | {ca_str} | {ca_match} | {nd_str} | {nd_match} |")

    # Flip analysis
    lines += ["", "---", ""]
    for mode in ["compiler_agent", "newdebugger"]:
        gains, regressions, to_incomp = [], [], []
        for i, item in enumerate(questions):
            bs = all_results["baseline"][i]["status"]
            ms = all_results[mode][i]["status"]
            if   bs == "wrong"   and ms == "correct":    gains.append(item["template"][:70])
            elif bs == "correct" and ms == "wrong":       regressions.append(item["template"][:70])
            elif bs == "correct" and ms == "incompleted": to_incomp.append(item["template"][:70])
        net = len(gains) - len(regressions) - len(to_incomp)
        lines += [
            f"## {APPROACH_LABELS[mode]} vs Baseline — Flips", "",
            "| Change | Count |", "|--------|-------|",
            f"| Gains (wrong -> correct) | {len(gains)} |",
            f"| Regressions (correct -> wrong) | {len(regressions)} |",
            f"| Correct -> Incompleted | {len(to_incomp)} |",
            f"| Net | {net:+d} |", "",
        ]
        for title, lst in [("Gains", gains), ("Regressions", regressions), ("Correct -> Incompleted", to_incomp)]:
            if lst:
                lines.append(f"**{title}:**")
                for q in lst: lines.append(f"- {q}")
                lines.append("")

    # Error breakdown
    lines += ["---", "", "## Error Breakdown (wrong + incompleted only)", ""]
    lines += ["| Category | Baseline | Compiler Agent | New Debugger |",
              "|----------|----------|----------------|--------------|"]
    for cat in ERROR_CATEGORIES:
        row = f"| {cat} |"
        for mode in APPROACHES:
            counts = _error_counts(all_results[mode])
            row += f" {counts[cat]} |"
        lines.append(row)

    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Plots ─────────────────────────────────────────────────────────────────────────

def plot_per_question_comparison(run_dir, questions, all_results):
    """Line plot: x=question, y=outcome level, one line per approach."""
    STATUS_VAL = {"incompleted": 0, "wrong": 1, "correct": 2}
    MARKERS    = {"baseline": "o", "compiler_agent": "s", "newdebugger": "^"}
    x = np.arange(1, len(questions) + 1)

    fig, ax = plt.subplots(figsize=(max(12, len(questions) * 0.5), 5))
    for mode in APPROACHES:
        y = [STATUS_VAL[all_results[mode][i]["status"]] for i in range(len(questions))]
        ax.plot(x, y, marker=MARKERS[mode], color=APPROACH_COLORS[mode],
                label=APPROACH_LABELS[mode], linewidth=1.4, markersize=6, alpha=0.85)

    for i in range(len(questions)):
        color = "#e8f5e9" if all_results["baseline"][i]["status"] == "correct" else "#ffebee"
        ax.axvspan(i + 0.5, i + 1.5, color=color, alpha=0.35, linewidth=0)

    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["Incompleted", "Wrong", "Correct"], fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels([str(i) for i in x], fontsize=7)
    ax.set_xlabel("Question index", fontsize=10)
    ax.set_ylabel("Outcome", fontsize=10)
    ax.set_title("Per-Question Outcome\n(green bg = baseline correct, red bg = baseline wrong)", fontsize=12)
    ax.set_xlim(0.5, len(questions) + 0.5)
    ax.set_ylim(-0.3, 2.3)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    plt.savefig(os.path.join(run_dir, "per_question_comparison.png"), dpi=150)
    plt.close()


def plot_baseline_agreement(run_dir, questions, all_results):
    """
    Bar chart treating baseline as 100% ground truth.
    Shows what % of questions each approach answered the same way baseline did.
    Matching rules: both correct → match; both wrong + same value → match;
                    both incompleted with same reason → match.
    """
    base = all_results["baseline"]
    labels = [APPROACH_LABELS[m] for m in APPROACHES]
    pcts   = [100.0]  # baseline always 100%
    counts = [len(questions)]

    for mode in ["compiler_agent", "newdebugger"]:
        matched, pct = _agreement(base, all_results[mode])
        pcts.append(pct)
        counts.append(matched)

    colors = [APPROACH_COLORS[m] for m in APPROACHES]
    x = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(x, pcts, color=colors, width=0.5, edgecolor="white", linewidth=1.2)

    for bar, pct, cnt in zip(bars, pcts, counts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.5,
                f"{pct:.1f}%\n({cnt}/{len(questions)})",
                ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Agreement with Baseline Answer (%)", fontsize=10)
    ax.set_ylim(0, 120)
    ax.set_title("Agreement with Baseline Answer\n(baseline treated as ground truth)", fontsize=12)
    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(run_dir, "baseline_agreement.png"), dpi=150)
    plt.close()


def plot_status_breakdown(run_dir, questions, all_results):
    """Stacked horizontal bar: correct / wrong / incompleted per approach."""
    fig, ax = plt.subplots(figsize=(8, 4))
    y_pos = np.arange(len(APPROACHES))
    n = len(questions)

    correct_vals   = [sum(1 for r in all_results[m] if r["status"] == "correct")   for m in APPROACHES]
    wrong_vals     = [sum(1 for r in all_results[m] if r["status"] == "wrong")     for m in APPROACHES]
    incomp_vals    = [sum(1 for r in all_results[m] if r["status"] == "incompleted") for m in APPROACHES]

    bars_c = ax.barh(y_pos, correct_vals, color="#4CAF50", label="Correct")
    bars_w = ax.barh(y_pos, wrong_vals,   color="#F44336", label="Wrong",
                     left=correct_vals)
    bars_i = ax.barh(y_pos, incomp_vals,  color="#FF9800", label="Incompleted",
                     left=[c + w for c, w in zip(correct_vals, wrong_vals)])

    # Labels inside bars
    for i, (c, w, inc) in enumerate(zip(correct_vals, wrong_vals, incomp_vals)):
        if c:   ax.text(c / 2,          i, str(c),   ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        if w:   ax.text(c + w / 2,      i, str(w),   ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        if inc: ax.text(c + w + inc / 2,i, str(inc), ha="center", va="center", fontsize=9, color="white", fontweight="bold")

    ax.set_yticks(y_pos)
    ax.set_yticklabels([APPROACH_LABELS[m] for m in APPROACHES], fontsize=11)
    ax.set_xlabel("Number of questions", fontsize=10)
    ax.set_xlim(0, n + 1)
    ax.set_title("Status Breakdown per Approach", fontsize=12)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(run_dir, "status_breakdown.png"), dpi=150)
    plt.close()


def plot_error_breakdown(run_dir, questions, all_results):
    """Grouped bar: error category counts per approach (wrong + incompleted only)."""
    cats   = ERROR_CATEGORIES
    n_cats = len(cats)
    x      = np.arange(n_cats)
    width  = 0.25

    fig, ax = plt.subplots(figsize=(13, 5))
    for j, mode in enumerate(APPROACHES):
        counts = _error_counts(all_results[mode])
        vals   = [counts[c] for c in cats]
        offset = (j - 1) * width
        bars   = ax.bar(x + offset, vals, width, label=APPROACH_LABELS[mode],
                        color=APPROACH_COLORS[mode], edgecolor="white", linewidth=0.8)
        for bar, v in zip(bars, vals):
            if v:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                        str(v), ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(cats, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Count", fontsize=10)
    ax.set_title("Failure Type Breakdown\n(wrong + incompleted questions only)", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(run_dir, "error_breakdown.png"), dpi=150)
    plt.close()


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10,
                        help="Number of questions (-1 = all excluding few-shots)")
    parser.add_argument("--model",  default="gpt-4")
    parser.add_argument("--seed",   type=int, default=42)
    parser.add_argument("--dataset_path", default=DEFAULT_DATASET_PATH)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set.")

    tabtools.configure(args.dataset_path, DATASET)

    data_file = os.path.join(args.dataset_path, DATASET, "valid_preprocessed.json")
    with open(data_file) as f:
        all_questions = json.load(f)
    random.seed(args.seed)
    random.shuffle(all_questions)

    fewshot_questions = extract_fewshot_questions()
    questions = [q for q in all_questions
                 if q["template"].strip().lower() not in fewshot_questions]
    excluded = len(all_questions) - len(questions)
    print(f"Loaded {len(all_questions)} questions, excluded {excluded} few-shot questions.")

    if args.n != -1:
        questions = questions[:args.n]
    print(f"Running {len(questions)} questions | model={args.model} | seed={args.seed}")
    for i, q in enumerate(questions):
        print(f"  {i+1}. {q['template'][:70]}")

    from prompts_mimic import EHRAgent_4Shots_Knowledge
    long_term_memory = []
    for item in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        item = item.split("Question:")[-1]
        q_part = item.split("\nKnowledge:\n")[0]
        rest   = item.split("\nKnowledge:\n")[-1]
        k_part = rest.split("\nSolution:")[0]
        c_part = rest.split("\nSolution:")[-1]
        long_term_memory.append({"question": q_part, "knowledge": k_part, "code": c_part})

    # Human-readable timestamp folder: 2026-05-30_19-41-13
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(OUTPUT_BASE, ts)
    os.makedirs(run_dir, exist_ok=True)
    print(f"\nOutput directory: {run_dir}")

    all_results = {}
    for mode in APPROACHES:
        all_results[mode] = run_approach(
            questions, mode, args.model, api_key, args.seed, long_term_memory
        )

    print("\nWriting per-question traces...")
    for i, item in enumerate(questions):
        q_id  = item.get("id", str(i))[:8]
        q_dir = os.path.join(run_dir, f"q{i+1:02d}_{q_id}")
        write_question_trace(q_dir, item, {m: all_results[m][i] for m in APPROACHES})

    print("Writing summary and plots...")
    write_summary(run_dir, questions, all_results)
    plot_per_question_comparison(run_dir, questions, all_results)
    plot_baseline_agreement(run_dir, questions, all_results)
    plot_status_breakdown(run_dir, questions, all_results)
    plot_error_breakdown(run_dir, questions, all_results)

    print(f"\n{'='*60}\nRun complete: {run_dir}\n{'='*60}")
    print("\nAccuracy vs ground truth:")
    for mode in APPROACHES:
        s = _stats(all_results[mode])
        print(f"  {APPROACH_LABELS[mode]}: {s['correct']}/{s['n']} correct ({s['accuracy']:.1f}%)")

    print("\nAgreement with baseline answer:")
    for mode in ["compiler_agent", "newdebugger"]:
        matched, pct = _agreement(all_results["baseline"], all_results[mode])
        print(f"  {APPROACH_LABELS[mode]}: {matched}/{len(questions)} match ({pct:.1f}%)")

    with open(os.path.join(run_dir, "raw_results.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nRaw results: {os.path.join(run_dir, 'raw_results.json')}")


if __name__ == "__main__":
    main()
