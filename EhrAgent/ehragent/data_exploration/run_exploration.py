# EhrAgent/ehragent/data_exploration/run_exploration.py
"""
6-condition benchmark: 2 pipelines x 3 schema variants.

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
import contextlib
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

from config import get_openai_key, get_anthropic_key, get_provider
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


# -- Argument parsing ----------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Data Exploration -- 6-condition EHR benchmark")
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
    p.add_argument(
        "--compact_terminal",
        action="store_true",
        help="Suppress raw agent output and print compact per-problem progress.",
    )
    return p.parse_args()


# -- Dataset loading -----------------------------------------------------------

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


# -- Schema string helpers -----------------------------------------------------

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


# -- Run one condition ---------------------------------------------------------

def run_condition(
    pipeline_type, schema_mode, schema_str, questions,
    model, openai_key, seed, dataset, dataset_path,
    long_term_memory_base, run_dir, explorer_trace,
    verbose, provider="openai", compact_terminal=False,
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
        provider=provider,
    )
    long_term_memory = list(long_term_memory_base)
    results = []
    traces_dir = os.path.join(run_dir, "traces")
    os.makedirs(traces_dir, exist_ok=True)

    for i, item in enumerate(questions):
        if compact_terminal:
            print(
                f"Problem {i+1} out of {len(questions)} | {ckey} | running...",
                end="\r",
                flush=True,
            )
        elif verbose:
            print(f"  [{i+1}/{len(questions)}] {item['template'][:70]}...")

        if compact_terminal:
            with open(os.devnull, "w") as devnull:
                with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    result = run_question(user_proxy, chatbot, item, long_term_memory)
        else:
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

        if compact_terminal:
            print(
                f"Problem {i+1} out of {len(questions)} | {ckey} | "
                f"{result['status'].upper()} | complete on try {result['num_tries']}"
            )
        elif verbose:
            print(f"    -> {result['status'].upper()} | tries={result['num_tries']}")

    correct = sum(1 for r in results if r["status"] == "correct")
    if verbose:
        print(f"  Done: {correct}/{len(questions)} correct")
    return results


# -- Stats ---------------------------------------------------------------------

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


# -- Summary -------------------------------------------------------------------

def write_summary(run_dir, questions, all_results, explorer_tokens):
    lines = [
        "# Data Exploration -- 6-Condition EHR Benchmark", "",
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
                    emoji = {"correct": "OK", "wrong": "WRONG", "incompleted": "INC"}.get(r["status"], "?")
                    row += f" {emoji} ({r['num_tries']}t) |"
                else:
                    row += " -- |"
        lines.append(row)

    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# -- Graphs --------------------------------------------------------------------

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


# -- Main ----------------------------------------------------------------------

def main():
    args = parse_args()
    provider = get_provider()
    openai_key = get_openai_key()          # returns ANTHROPIC_API_KEY when in anthropic mode
    anthropic_key = get_anthropic_key()
    print(f"Provider: {provider} | model: {args.model}")

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
                provider=provider,
                compact_terminal=args.compact_terminal,
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
