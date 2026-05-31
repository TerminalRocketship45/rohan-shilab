"""Full statistical analysis + plots for the three pipeline runs."""
import json
import os
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Load results ─────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
RUNS = {
    "Baseline":         os.path.join(BASE, "run_20260521_185004_mimic_iii_baseline_n30_seed42",       "results.json"),
    "Compiler Agent":   os.path.join(BASE, "run_20260521_193940_mimic_iii_compiler_agent_n30_seed42", "results.json"),
    "New Debugger":     os.path.join(BASE, "run_20260521_212530_mimic_iii_newdebugger_n30_seed42",    "results.json"),
}

data = {}
for name, path in RUNS.items():
    with open(path) as f:
        results = json.load(f)
    data[name] = {r["id"]: r for r in results}

# Canonical question order (baseline order)
with open(RUNS["Baseline"]) as f:
    baseline_list = json.load(f)
question_order = [r["id"] for r in baseline_list]
id_to_q = {r["id"]: r["question"] for r in baseline_list}

# ── Per-approach summary stats ────────────────────────────────────────────────
APPROACHES = list(RUNS.keys())
MAX_TRIES = 11  # max_consecutive_auto_reply=10 → 11 turns


def summarise(approach):
    rows = [data[approach][qid] for qid in question_order]
    n = len(rows)
    correct     = sum(1 for r in rows if r["status"] == "correct")
    wrong       = sum(1 for r in rows if r["status"] == "wrong")
    incompleted = sum(1 for r in rows if r["status"] == "incompleted")
    hit_max     = sum(1 for r in rows if r["num_tries"] >= MAX_TRIES)
    accuracy    = correct / n * 100
    completion  = (n - incompleted) / n * 100
    return dict(n=n, correct=correct, wrong=wrong, incompleted=incompleted,
                hit_max=hit_max, accuracy=accuracy, completion=completion)


stats = {a: summarise(a) for a in APPROACHES}

# ── Flip analysis (vs Baseline) ───────────────────────────────────────────────
def flip_analysis(approach):
    """Return lists of question IDs that flipped relative to Baseline."""
    b = data["Baseline"]
    a = data[approach]
    correct_to_wrong  = []
    correct_to_incomp = []
    wrong_to_correct  = []
    wrong_to_incomp   = []
    for qid in question_order:
        bs = b[qid]["status"]
        as_ = a[qid]["status"]
        if bs == "correct" and as_ == "wrong":        correct_to_wrong.append(qid)
        elif bs == "correct" and as_ == "incompleted": correct_to_incomp.append(qid)
        elif bs == "wrong"   and as_ == "correct":    wrong_to_correct.append(qid)
        elif bs == "wrong"   and as_ == "incompleted": wrong_to_incomp.append(qid)
    return dict(
        correct_to_wrong=correct_to_wrong,
        correct_to_incomp=correct_to_incomp,
        wrong_to_correct=wrong_to_correct,
        wrong_to_incomp=wrong_to_incomp,
    )


flips = {a: flip_analysis(a) for a in ["Compiler Agent", "New Debugger"]}

# ── Build Markdown report ─────────────────────────────────────────────────────
lines = []

lines += [
    "# EHRAgent Pipeline Full Analysis",
    "",
    "**Dataset:** mimic_iii | **n=30** | **seed=42** | **Model:** gpt-4o-mini",
    "",
    "---",
    "",
    "## Few-Shot Examples",
    "",
    "### Coding Agent (EHRAgent_4Shots_Knowledge) — `prompts_mimic.py`",
    "",
    "| # | Question |",
    "|---|----------|",
    "| 1 | What is the maximum total hospital cost that involves a diagnosis named comp-oth vasc dev/graft since 1 year ago? |",
    "| 2 | Had any tpn w/lipids been given to patient 2238 in their last hospital visit? |",
    "| 3 | What was the name of the procedure that was given two or more times to patient 58730? |",
    "| 4 | Calculate the length of stay of the first stay of patient 27392 in the icu. |",
    "",
    "### Compiler / Debugger Agent (CompilerAgent_FewShot_Examples) — `prompts_mimic.py`",
    "",
    "| # | Question | Label |",
    "|---|----------|-------|",
    "| 1 | Had any tpn w/lipids been given to patient 2238 in their last hospital visit? | SUCCESS |",
    "| 2 | Calculate the length of stay of the first stay of patient 27392 in the icu. | SUCCESS |",
    "| 3 | **Count the number of patients who stayed in careunit ccu since 5 year ago.** | ERROR (`SUBJECT_ID, unique`) |",
    "| 4 | **What was the total amount of dose of ranitidine that patient 24971 were prescribed in 01/2105?** | ERROR (`DRUG_NAME` wrong col) |",
    "",
    "> ⚠️ **Contamination:** Examples 3 and 4 above appear verbatim in the 30 evaluated questions.",
    "> The CCU question (shown as ERROR for `SUBJECT_ID, unique`) and the ranitidine question",
    "> (shown as ERROR for `DRUG_NAME`) are in the evaluation set. Both are `wrong` in baseline.",
    "",
    "---",
    "",
    "## Per-Approach Summary Tables",
    "",
]

for a in APPROACHES:
    s = stats[a]
    lines += [
        f"### {a}",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total questions | {s['n']} |",
        f"| **Correct** | **{s['correct']} ({s['accuracy']:.1f}%)** |",
        f"| Wrong | {s['wrong']} |",
        f"| Incompleted (never ran) | {s['incompleted']} |",
        f"| Completion rate (ran at all) | {s['completion']:.1f}% |",
        f"| Hit max tries (≥{MAX_TRIES}) | {s['hit_max']} |",
        "",
    ]

# ── Comparison table ──────────────────────────────────────────────────────────
lines += [
    "## Approach Comparison",
    "",
    "| Metric | Baseline | Compiler Agent | New Debugger |",
    "|--------|----------|----------------|--------------|",
]
metrics = [
    ("Correct",               lambda s: f"{s['correct']} ({s['accuracy']:.1f}%)"),
    ("Wrong",                 lambda s: str(s['wrong'])),
    ("Incompleted",           lambda s: str(s['incompleted'])),
    ("Completion rate",       lambda s: f"{s['completion']:.1f}%"),
    ("Hit max tries (≥11)",   lambda s: str(s['hit_max'])),
]
for label, fn in metrics:
    row = f"| {label} |"
    for a in APPROACHES:
        row += f" {fn(stats[a])} |"
    lines.append(row)

lines += ["", "---", ""]

# ── Flip tables ───────────────────────────────────────────────────────────────
def short_q(qid, max_len=72):
    q = id_to_q.get(qid, qid)
    return (q[:max_len] + "…") if len(q) > max_len else q


for a in ["Compiler Agent", "New Debugger"]:
    f = flips[a]
    lines += [
        f"## {a} vs Baseline — What Changed?",
        "",
        f"| Direction | Count |",
        f"|-----------|-------|",
        f"| ✅ Wrong → Correct (gains) | {len(f['wrong_to_correct'])} |",
        f"| ❌ Correct → Wrong (regressions) | {len(f['correct_to_wrong'])} |",
        f"| ⚠️ Correct → Incompleted | {len(f['correct_to_incomp'])} |",
        f"| — Wrong → Incompleted | {len(f['wrong_to_incomp'])} |",
        f"| Net correct change | {len(f['wrong_to_correct']) - len(f['correct_to_wrong']) - len(f['correct_to_incomp']):+d} |",
        "",
    ]
    if f["wrong_to_correct"]:
        lines.append("**Gains (wrong → correct):**")
        lines.append("")
        for qid in f["wrong_to_correct"]:
            lines.append(f"- `{short_q(qid)}`")
        lines.append("")
    if f["correct_to_wrong"]:
        lines.append("**Regressions (correct → wrong):**")
        lines.append("")
        for qid in f["correct_to_wrong"]:
            lines.append(f"- `{short_q(qid)}`")
        lines.append("")
    if f["correct_to_incomp"]:
        lines.append("**Correct → Incompleted:**")
        lines.append("")
        for qid in f["correct_to_incomp"]:
            lines.append(f"- `{short_q(qid)}`")
        lines.append("")

lines += ["---", ""]

# ── Per-question status table ─────────────────────────────────────────────────
lines += [
    "## Per-Question Status (all 30)",
    "",
    "| # | Question (truncated) | Baseline | Compiler Agent | New Debugger |",
    "|---|----------------------|----------|----------------|--------------|",
]
STATUS_EMOJI = {"correct": "✅", "wrong": "❌", "incompleted": "⚠️"}
for i, qid in enumerate(question_order, 1):
    q_short = short_q(qid, 55)
    row = f"| {i} | {q_short} |"
    for a in APPROACHES:
        r = data[a][qid]
        emoji = STATUS_EMOJI.get(r["status"], "?")
        row += f" {emoji} {r['status']} ({r['num_tries']}t) |"
    lines.append(row)

lines += ["", "---", ""]

# ── Write markdown ────────────────────────────────────────────────────────────
out_md = os.path.join(BASE, "full_analysis.md")
with open(out_md, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Markdown written: {out_md}")

# ── Plot ──────────────────────────────────────────────────────────────────────
STATUS_VAL = {"incompleted": 0, "wrong": 1, "correct": 2}
COLORS = {
    "Baseline":       "#2196F3",   # blue
    "Compiler Agent": "#F44336",   # red
    "New Debugger":   "#FF9800",   # orange
}
MARKERS = {
    "Baseline":       "o",
    "Compiler Agent": "s",
    "New Debugger":   "^",
}

fig, ax = plt.subplots(figsize=(16, 5))

x = np.arange(1, len(question_order) + 1)

for a in APPROACHES:
    y = [STATUS_VAL[data[a][qid]["status"]] for qid in question_order]
    ax.plot(x, y, marker=MARKERS[a], color=COLORS[a], label=a,
            linewidth=1.4, markersize=6, alpha=0.85)

# Shade background by baseline status
for i, qid in enumerate(question_order):
    bs = data["Baseline"][qid]["status"]
    color = "#e8f5e9" if bs == "correct" else "#ffebee"
    ax.axvspan(i + 0.5, i + 1.5, color=color, alpha=0.35, linewidth=0)

ax.set_yticks([0, 1, 2])
ax.set_yticklabels(["Incompleted\n(didn't finish)", "Wrong", "Correct"], fontsize=10)
ax.set_xticks(x)
ax.set_xticklabels([str(i) for i in x], fontsize=7)
ax.set_xlabel("Question index (ordered by baseline evaluation order)", fontsize=10)
ax.set_ylabel("Outcome", fontsize=10)
ax.set_title("EHRAgent Pipeline Comparison — Per-Question Outcome\n(green bg = baseline correct, red bg = baseline wrong)",
             fontsize=12)
ax.set_xlim(0.5, len(question_order) + 0.5)
ax.set_ylim(-0.3, 2.3)
ax.legend(loc="lower right", fontsize=9)
ax.grid(axis="y", linestyle="--", alpha=0.4)

plt.tight_layout()
out_plot = os.path.join(BASE, "per_question_comparison.png")
plt.savefig(out_plot, dpi=150)
plt.close()
print(f"Plot written: {out_plot}")

# ── Print key numbers to console ──────────────────────────────────────────────
print("\n=== SUMMARY ===")
for a in APPROACHES:
    s = stats[a]
    print(f"\n{a}:")
    print(f"  Correct:     {s['correct']}/30  ({s['accuracy']:.1f}%)")
    print(f"  Wrong:       {s['wrong']}/30")
    print(f"  Incompleted: {s['incompleted']}/30")
    print(f"  Hit max(11): {s['hit_max']}/30")

for a in ["Compiler Agent", "New Debugger"]:
    f = flips[a]
    net = len(f['wrong_to_correct']) - len(f['correct_to_wrong']) - len(f['correct_to_incomp'])
    print(f"\n{a} vs Baseline:")
    print(f"  Gains (wrong->correct):        {len(f['wrong_to_correct'])}")
    print(f"  Regressions (correct->wrong):  {len(f['correct_to_wrong'])}")
    print(f"  Correct->Incompleted:          {len(f['correct_to_incomp'])}")
    print(f"  Wrong->Incompleted:            {len(f['wrong_to_incomp'])}")
    print(f"  Net change in correct:        {net:+d}")
