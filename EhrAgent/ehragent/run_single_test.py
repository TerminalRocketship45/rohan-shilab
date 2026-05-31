"""
Run a single question through all three pipeline approaches (baseline, compiler_agent,
newdebugger) using gpt-4 and write a readable Markdown log to the outputs/ folder.

Usage:
    python run_single_test.py
    python run_single_test.py --question_idx 3   # 0-based index after seed=42 shuffle
    python run_single_test.py --model gpt-4o     # override model
"""
import os
import sys
import json
import random
import argparse
import time
import warnings
from datetime import datetime

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
SEED = 42
NUM_SHOTS = 4


# ── Helpers (copied from pipeline.py so this script is self-contained) ──────────

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


def strip_examples(message):
    marker = "(END OF EXAMPLES)"
    if marker in message:
        return message[message.index(marker) + len(marker):]
    return message


def load_question(dataset_path, idx):
    data_file = os.path.join(dataset_path, DATASET, "valid_preprocessed.json")
    with open(data_file) as f:
        contents = json.load(f)
    random.seed(SEED)
    random.shuffle(contents)
    return contents[idx]


def build_long_term_memory():
    from prompts_mimic import EHRAgent_4Shots_Knowledge
    memory = []
    for item in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        item = item.split("Question:")[-1]
        question_part = item.split("\nKnowledge:\n")[0]
        rest = item.split("\nKnowledge:\n")[-1]
        knowledge_part = rest.split("\nSolution:")[0]
        code_part = rest.split("\nSolution:")[-1]
        memory.append({"question": question_part, "knowledge": knowledge_part, "code": code_part})
    return memory


def run_question(user_proxy, chatbot, item, long_term_memory):
    question = item["template"]
    answer = item["answer"]
    gt_answer = answer if isinstance(answer, str) else ", ".join(answer)

    result = {
        "question": question,
        "ground_truth": gt_answer,
        "predicted_answer": "",
        "last_exec_result": "",
        "is_correct": False,
        "status": "incompleted",
        "num_tries": 0,
        "agent_trace": [],
    }

    try:
        user_proxy.update_memory(NUM_SHOTS, long_term_memory)
        user_proxy.initiate_chat(chatbot, message=question)

        logs = user_proxy.chat_messages
        trace = []
        num_tries = 0
        last_exec_result = ""

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
                elif msg.get("function_call"):
                    code = _extract_code(msg["function_call"]["arguments"])
                    trace.append(code)
                    num_tries += 1
                elif msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {})
                        code = _extract_code(fn.get("arguments", ""))
                        trace.append(code)
                        num_tries += 1

        result["agent_trace"] = trace
        result["num_tries"] = max(num_tries, 1)

        logs_string = "\n".join(trace)
        term_idx = logs_string.rfind("TERMINATE")
        prediction_block = logs_string[:term_idx] if term_idx != -1 else logs_string

        # Best-effort: find the last execution result in the trace
        # Exec results land as plain content messages (not code blocks)
        # They appear at even trace indices starting from index 2
        exec_results = []
        i = 2
        while i < len(trace):
            candidate = trace[i].strip()
            # Skip TERMINATE messages and obvious LLM replies
            if "TERMINATE" not in candidate and not candidate.startswith("```"):
                exec_results.append(candidate)
            i += 2  # every other message starting from index 2 is an exec result

        last_exec_result = exec_results[-1] if exec_results else ""
        result["last_exec_result"] = last_exec_result

        is_correct = judge(prediction_block, gt_answer)
        result["predicted_answer"] = prediction_block.strip().split("\n")[-1]
        result["is_correct"] = is_correct
        result["status"] = "correct" if is_correct else "wrong"

    except CompilerSuccessButExecFailed as e:
        result["status"] = "incompleted"
        result["last_exec_result"] = str(e)
        result["agent_trace"].append("[INCOMPLETED: compiler said SUCCESS but real exec failed]")
    except Exception as e:
        result["status"] = "incompleted"
        result["last_exec_result"] = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: exception] {e}")

    return result


# ── Trace pretty-printer ─────────────────────────────────────────────────────────

def format_trace_for_log(trace):
    """Convert raw trace list into labelled sections for the log file."""
    if not trace:
        return "(no trace captured)"

    lines = []
    lines.append("**[INITIAL MESSAGE (knowledge + examples stripped)]**")
    # trace[0] is the initial message — strip_examples already removed the examples block
    lines.append("```")
    lines.append(trace[0][:800] + ("..." if len(trace[0]) > 800 else ""))
    lines.append("```")
    lines.append("")

    i = 1
    attempt_num = 1
    while i < len(trace):
        code_block = trace[i] if i < len(trace) else None
        exec_block = trace[i + 1] if (i + 1) < len(trace) else None

        lines.append(f"**[ATTEMPT {attempt_num}]**")

        if code_block is not None:
            lines.append(f"*Code submitted:*")
            lines.append("```python")
            lines.append(code_block[:1200] + ("..." if len(code_block) > 1200 else ""))
            lines.append("```")

        if exec_block is not None:
            label = "Execution result" if "TERMINATE" not in exec_block else "Final reply"
            lines.append(f"*{label}:*")
            lines.append("```")
            lines.append(exec_block[:800] + ("..." if len(exec_block) > 800 else ""))
            lines.append("```")

        lines.append("")
        i += 2
        attempt_num += 1

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────────

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
        is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().endswith("TERMINATE"),
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


def write_log(out_path, item, results_by_mode):
    q = item["template"]
    answer = item["answer"]
    gt = answer if isinstance(answer, str) else ", ".join(answer)

    log_lines = [
        "# EHRAgent Single-Question Test",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Dataset:** {DATASET} | **Seed:** {SEED}",
        "",
        "---",
        "",
        "## Question",
        "",
        f"> {q}",
        "",
        f"**Ground truth:** `{gt}`",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Approach | Status | Tries | Predicted Answer | Correct? |",
        "|----------|--------|-------|-----------------|----------|",
    ]

    MODE_LABELS = {
        "baseline": "Baseline",
        "compiler_agent": "Compiler Agent",
        "newdebugger": "New Debugger",
    }

    for mode in ["baseline", "compiler_agent", "newdebugger"]:
        r = results_by_mode[mode]
        label = MODE_LABELS[mode]
        correct_mark = "YES" if r["is_correct"] else "NO"
        pred = r["predicted_answer"].replace("|", "\\|")[:80]
        log_lines.append(f"| {label} | {r['status'].upper()} | {r['num_tries']} | `{pred}` | {correct_mark} |")

    log_lines += ["", "---", ""]

    for mode in ["baseline", "compiler_agent", "newdebugger"]:
        r = results_by_mode[mode]
        label = MODE_LABELS[mode]

        log_lines += [
            f"## {label}",
            "",
            f"**Status:** {r['status'].upper()} | **Tries:** {r['num_tries']} | **Correct:** {'YES' if r['is_correct'] else 'NO'}",
            "",
            f"**Ground truth:** `{gt}`",
            "",
            f"**Predicted answer (last-line extraction):** `{r['predicted_answer'][:200]}`",
            "",
            f"**Last execution result:** `{r['last_exec_result'][:300]}`",
            "",
            "### Full Trace",
            "",
            format_trace_for_log(r["agent_trace"]),
            "",
            "---",
            "",
        ]

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"\nLog written to: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question_idx", type=int, default=0,
                        help="0-based index into seed=42 shuffled question list (default: 0)")
    parser.add_argument("--model", default="gpt-4",
                        help="OpenAI model to use (default: gpt-4)")
    parser.add_argument("--dataset_path", default=DEFAULT_DATASET_PATH)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Run: $env:OPENAI_API_KEY = 'sk-...'"
        )

    tabtools.configure(args.dataset_path, DATASET)

    item = load_question(args.dataset_path, args.question_idx)
    print(f"Question [{args.question_idx}]: {item['template']}")
    print(f"Ground truth: {item['answer']}")
    print(f"Model: {args.model}")
    print()

    long_term_memory = build_long_term_memory()

    results_by_mode = {}
    for mode in ["baseline", "compiler_agent", "newdebugger"]:
        print(f"{'='*60}")
        print(f"Running: {mode}")
        print(f"{'='*60}")

        user_proxy, chatbot = build_agents(args.model, api_key, SEED, mode)
        result = run_question(user_proxy, chatbot, item, list(long_term_memory))
        results_by_mode[mode] = result

        status_str = result["status"].upper()
        print(f"  -> {status_str} | tries={result['num_tries']} | correct={result['is_correct']}")
        print(f"     last_exec_result: {result['last_exec_result'][:100]}")
        print()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_BASE, f"single_test_{ts}.md")
    write_log(out_path, item, results_by_mode)


if __name__ == "__main__":
    main()
