"""
Standalone analysis script for a completed EHRAgent run.
Reads raw_results.json and regenerates: summary.md + all plots.

Usage:
    python analyze_run.py <run_dir>
    python analyze_run.py EhrAgent/ehragent/outputs/20260530_201842
"""

import os
import sys
import json
import re
import warnings
import argparse

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

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
STATUS_EMOJI = {"correct": "YES", "wrong": "NO", "incompleted": "INCOMP"}
MAX_TRIES = 11

ERROR_CATEGORIES = [
    "Compiler false positive (silenced)",
    "Wrong column name",
    "Invalid separator (&&/AND)",
    "SQL subquery in FilterDB",
    "Hit max tries",
    "No error info",
    "Other",
]


# ── Judge ─────────────────────────────────────────────────────────────────────

def judge(pred, ans):
    pred = str(pred)
    ans  = str(ans)
    old_flag = ans in pred
    pred2 = pred
    if "True"  in pred2: pred2 = pred2.replace("True",  "1")
    if "False" in pred2: pred2 = pred2.replace("False", "0")
    if "yes"   in pred2.lower(): pred2 = pred2.lower().replace("yes", "1")
    if "no"    in pred2.lower() and "1" not in pred2: pred2 = pred2.lower().replace("no", "0")
    for old, new in [("False","0"),("True","1"),("No","0"),("Yes","1"),("None","0")]:
        if ans in (old, old.lower()): ans = new
    ans_list = ans.split(", ") if ", " in ans else [ans]
    ans_list = [a[:-2] if a.endswith(".0") else a for a in ans_list]
    new_flag = all(a in pred2 for a in ans_list)
    return old_flag or new_flag


def matches_baseline(bl, r):
    bs, ns = bl["status"], r["status"]
    if bs == "correct"    and ns == "correct":    return True
    if bs == "wrong"      and ns == "wrong":
        bp = bl.get("predicted_answer", "")
        np_ = r.get("predicted_answer", "")
        return judge(np_, bp) or judge(bp, np_)
    if bs == "incompleted" and ns == "incompleted":
        return bl.get("incompleted_reason") == r.get("incompleted_reason")
    return False


# ── Error categorisation ──────────────────────────────────────────────────────

def categorize_error(r):
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


# ── Stats ─────────────────────────────────────────────────────────────────────

def _stats(results):
    n     = len(results)
    corr  = sum(1 for r in results if r["status"] == "correct")
    wrong = sum(1 for r in results if r["status"] == "wrong")
    incomp = sum(1 for r in results if r["status"] == "incompleted")
    hit   = sum(1 for r in results if r.get("num_tries", 0) >= MAX_TRIES)
    return dict(n=n, correct=corr, wrong=wrong, incompleted=incomp, hit_max=hit,
                accuracy=corr/n*100 if n else 0,
                completion=(n-incomp)/n*100 if n else 0)


def _agreement(base_results, new_results):
    matched = sum(1 for b, r in zip(base_results, new_results) if matches_baseline(b, r))
    n = len(base_results)
    return matched, matched/n*100 if n else 0


def _error_counts(results):
    counts = {c: 0 for c in ERROR_CATEGORIES}
    for r in results:
        cat = categorize_error(r)
        if cat:
            counts[cat] += 1
    return counts


# ── Summary.md ────────────────────────────────────────────────────────────────

def write_summary(run_dir, all_results):
    questions = [{"id": r["id"], "template": r["question"], "answer": r["ground_truth"]}
                 for r in all_results["baseline"]]
    n = len(questions)
    stats = {mode: _stats(all_results[mode]) for mode in APPROACHES}
    base  = all_results["baseline"]

    lines = [
        "# EHRAgent Pipeline Analysis",
        "",
        f"**Run directory:** `{run_dir}`",
        f"**n = {n} questions**",
        "",
        "---",
        "",
        "## Accuracy vs Ground Truth",
        "",
        "| Metric | Baseline | Compiler Agent | New Debugger |",
        "|--------|----------|----------------|--------------|",
    ]

    def _row(label, fn):
        return f"| {label} | " + " | ".join(fn(stats[m], all_results[m]) for m in APPROACHES) + " |"

    lines.append(_row("Correct",
        lambda s, _: f"{s['correct']} / {s['n']} ({s['accuracy']:.1f}%)"))
    lines.append(_row("Wrong",
        lambda s, _: str(s['wrong'])))
    lines.append(_row("Incompleted",
        lambda s, _: str(s['incompleted'])))
    lines.append(_row("  — compiler false positive",
        lambda s, rs: str(sum(1 for r in rs if r.get("incompleted_reason") == "compiler_success_exec_failed"))))
    lines.append(_row("  — exception",
        lambda s, rs: str(sum(1 for r in rs if r.get("incompleted_reason") == "exception"))))
    lines.append(_row("Completion rate",
        lambda s, _: f"{s['completion']:.1f}%"))
    lines.append(_row(f"Hit max ({MAX_TRIES} tries)",
        lambda s, _: str(s['hit_max'])))

    lines += ["", "---", "", "## Agreement with Baseline Answer", "",
              "> Matching rules: both correct = match; both wrong with same value = match;",
              "> both incompleted with same reason = match.", "",
              "| Approach | Matched | Total | Agreement % |",
              "|----------|---------|-------|-------------|",
              "| Baseline | — | — | 100% (reference) |"]
    for mode in ["compiler_agent", "newdebugger"]:
        matched, pct = _agreement(base, all_results[mode])
        lines.append(f"| {APPROACH_LABELS[mode]} | {matched} | {n} | {pct:.1f}% |")

    # Per-question table
    lines += ["", "---", "", "## Per-Question Status", "",
              "| # | Question | Baseline | Compiler Agent | CA=BL? | New Debugger | ND=BL? |",
              "|---|----------|----------|----------------|--------|--------------|--------|"]
    for i, item in enumerate(questions):
        q_short = (item["template"][:55] + "...") if len(item["template"]) > 55 else item["template"]
        bl = all_results["baseline"][i]
        ca = all_results["compiler_agent"][i]
        nd = all_results["newdebugger"][i]
        def _fmt(r):
            em = {"correct": "CORRECT", "wrong": "WRONG", "incompleted": "INCOMP"}
            return f"{em.get(r['status'], r['status'])} ({r.get('num_tries',0)}t)"
        lines.append(f"| {i+1} | {q_short} | {_fmt(bl)} | {_fmt(ca)} | {'YES' if matches_baseline(bl,ca) else 'NO'} | {_fmt(nd)} | {'YES' if matches_baseline(bl,nd) else 'NO'} |")

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
            f"## {APPROACH_LABELS[mode]} vs Baseline -- Flips", "",
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
    lines += ["---", "", "## Error Breakdown (wrong + incompleted only)", "",
              "| Category | Baseline | Compiler Agent | New Debugger |",
              "|----------|----------|----------------|--------------|"]
    for cat in ERROR_CATEGORIES:
        row = f"| {cat} |"
        for mode in APPROACHES:
            row += f" {_error_counts(all_results[mode])[cat]} |"
        lines.append(row)

    out_path = os.path.join(run_dir, "summary.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Written: {out_path}")


# ── Plots ─────────────────────────────────────────────────────────────────────

def plot_per_question(run_dir, all_results):
    n = len(all_results["baseline"])
    STATUS_VAL = {"incompleted": 0, "wrong": 1, "correct": 2}
    MARKERS    = {"baseline": "o", "compiler_agent": "s", "newdebugger": "^"}
    x = np.arange(1, n + 1)

    fig, ax = plt.subplots(figsize=(max(10, n * 0.8), 5))
    for mode in APPROACHES:
        y = [STATUS_VAL[all_results[mode][i]["status"]] for i in range(n)]
        ax.plot(x, y, marker=MARKERS[mode], color=APPROACH_COLORS[mode],
                label=APPROACH_LABELS[mode], linewidth=1.6, markersize=8, alpha=0.9)

    for i in range(n):
        color = "#e8f5e9" if all_results["baseline"][i]["status"] == "correct" else "#ffebee"
        ax.axvspan(i + 0.5, i + 1.5, color=color, alpha=0.35, linewidth=0)

    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["Incompleted", "Wrong", "Correct"], fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels([f"Q{i}" for i in x], fontsize=9)
    ax.set_xlabel("Question", fontsize=11)
    ax.set_ylabel("Outcome", fontsize=11)
    ax.set_title("Per-Question Outcome by Approach\n(green = baseline correct, red = baseline wrong)", fontsize=13)
    ax.set_xlim(0.5, n + 0.5)
    ax.set_ylim(-0.35, 2.35)
    ax.legend(loc="lower right", fontsize=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    plt.tight_layout()
    out = os.path.join(run_dir, "per_question_comparison.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  Written: {out}")


def plot_baseline_agreement(run_dir, all_results):
    n = len(all_results["baseline"])
    base = all_results["baseline"]
    labels = [APPROACH_LABELS[m] for m in APPROACHES]
    pcts   = [100.0]
    counts = [n]
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
                f"{pct:.1f}%\n({cnt}/{n})",
                ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Agreement with Baseline Answer (%)", fontsize=10)
    ax.set_ylim(0, 125)
    ax.set_title("Agreement with Baseline Answer\n(baseline treated as reference)", fontsize=12)
    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    plt.tight_layout()
    out = os.path.join(run_dir, "baseline_agreement.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  Written: {out}")


def plot_status_breakdown(run_dir, all_results):
    n = len(all_results["baseline"])
    fig, ax = plt.subplots(figsize=(8, 4))
    y_pos = np.arange(len(APPROACHES))

    correct_vals = [sum(1 for r in all_results[m] if r["status"] == "correct")    for m in APPROACHES]
    wrong_vals   = [sum(1 for r in all_results[m] if r["status"] == "wrong")      for m in APPROACHES]
    incomp_vals  = [sum(1 for r in all_results[m] if r["status"] == "incompleted") for m in APPROACHES]

    ax.barh(y_pos, correct_vals, color="#4CAF50", label="Correct")
    ax.barh(y_pos, wrong_vals,   color="#F44336", label="Wrong",
            left=correct_vals)
    ax.barh(y_pos, incomp_vals,  color="#FF9800", label="Incompleted",
            left=[c + w for c, w in zip(correct_vals, wrong_vals)])

    for i, (c, w, inc) in enumerate(zip(correct_vals, wrong_vals, incomp_vals)):
        if c:   ax.text(c/2,           i, str(c),   ha="center", va="center", fontsize=11, color="white", fontweight="bold")
        if w:   ax.text(c + w/2,       i, str(w),   ha="center", va="center", fontsize=11, color="white", fontweight="bold")
        if inc: ax.text(c + w + inc/2, i, str(inc), ha="center", va="center", fontsize=11, color="white", fontweight="bold")

    ax.set_yticks(y_pos)
    ax.set_yticklabels([APPROACH_LABELS[m] for m in APPROACHES], fontsize=11)
    ax.set_xlabel("Number of questions", fontsize=10)
    ax.set_xlim(0, n + 0.5)
    ax.set_title(f"Status Breakdown per Approach  (n={n})", fontsize=12)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    plt.tight_layout()
    out = os.path.join(run_dir, "status_breakdown.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  Written: {out}")


def plot_error_breakdown(run_dir, all_results):
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
                        str(v), ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(cats, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Count", fontsize=10)
    ax.set_title("Failure Type Breakdown\n(wrong + incompleted questions only)", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    plt.tight_layout()
    out = os.path.join(run_dir, "error_breakdown.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  Written: {out}")


def plot_accuracy_bar(run_dir, all_results):
    """Simple accuracy bar chart comparing the three approaches."""
    n = len(all_results["baseline"])
    labels = [APPROACH_LABELS[m] for m in APPROACHES]
    accs   = [_stats(all_results[m])["accuracy"] for m in APPROACHES]
    colors = [APPROACH_COLORS[m] for m in APPROACHES]

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(labels, accs, color=colors, width=0.5, edgecolor="white", linewidth=1.2)
    for bar, acc, mode in zip(bars, accs, APPROACHES):
        cnt = _stats(all_results[mode])["correct"]
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.5,
                f"{acc:.1f}%\n({cnt}/{n})",
                ha="center", va="bottom", fontsize=12, fontweight="bold")

    ax.set_ylabel("Accuracy (%)", fontsize=11)
    ax.set_ylim(0, 110)
    ax.set_title(f"Accuracy vs Ground Truth  (n={n})", fontsize=13)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    plt.tight_layout()
    out = os.path.join(run_dir, "accuracy_comparison.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"  Written: {out}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="Path to the run output folder containing raw_results.json")
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    raw_path = os.path.join(run_dir, "raw_results.json")

    if not os.path.exists(raw_path):
        print(f"ERROR: raw_results.json not found in {run_dir}")
        sys.exit(1)

    with open(raw_path) as f:
        all_results = json.load(f)

    # Normalise: ensure all modes present and same length
    for mode in APPROACHES:
        if mode not in all_results:
            print(f"WARNING: mode '{mode}' not found in raw_results.json, skipping.")
            all_results[mode] = []

    n = max(len(all_results[m]) for m in APPROACHES)
    print(f"Loaded {n} questions across {len(APPROACHES)} approaches from:\n  {raw_path}\n")

    print("Generating outputs...")
    write_summary(run_dir, all_results)
    plot_per_question(run_dir, all_results)
    plot_baseline_agreement(run_dir, all_results)
    plot_status_breakdown(run_dir, all_results)
    plot_error_breakdown(run_dir, all_results)
    plot_accuracy_bar(run_dir, all_results)

    print("\nDone. Files written to:", run_dir)

    # Print quick summary to console
    print("\n--- Quick Summary ---")
    for mode in APPROACHES:
        s = _stats(all_results[mode])
        print(f"  {APPROACH_LABELS[mode]}: {s['correct']}/{s['n']} correct ({s['accuracy']:.1f}%)  |  {s['incompleted']} incompleted")
    print("\n  Agreement with Baseline:")
    base = all_results["baseline"]
    for mode in ["compiler_agent", "newdebugger"]:
        matched, pct = _agreement(base, all_results[mode])
        print(f"    {APPROACH_LABELS[mode]}: {matched}/{len(base)} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
