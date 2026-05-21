import os
import sys
import json
import random
import argparse
import time
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import autogen
from medagent import MedAgent
from config import openai_config, llm_config_list
from compiler_agent import CompilerAgent, CompilerDebuggerAgent, CompilerSuccessButExecFailed
from toolset_high import run_code
import tools.tabtools as tabtools

DEFAULT_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "ehrsql-ehragent", "ehrsql-ehragent"
)
OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


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


def _output_dir_name(dataset, mode, n, seed):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"run_{ts}_{dataset}_{mode}_n{n}_seed{seed}"


def parse_args():
    parser = argparse.ArgumentParser(description="EHRAgent pipeline")
    parser.add_argument("--dataset", required=True, choices=["mimic_iii", "eicu"])
    parser.add_argument("--dataset_path", default=None,
                        help="Path to ehrsql-ehragent folder (default: bundled dataset)")
    parser.add_argument("--n", type=int, default=30,
                        help="Number of questions to run (-1 = all)")
    parser.add_argument("--compiler_agent", action="store_true",
                        help="Approach 1: three-agent pipeline")
    parser.add_argument("--newdebugger", action="store_true",
                        help="Approach 2: combined compiler+debugger")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num_shots", type=int, default=4)
    args = parser.parse_args()
    if args.compiler_agent and args.newdebugger:
        parser.error("--compiler_agent and --newdebugger are mutually exclusive")
    if args.dataset_path is None:
        args.dataset_path = DEFAULT_DATASET_PATH
    return args


def get_api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set.\n"
            "Set it with: $env:OPENAI_API_KEY = 'sk-...'"
        )
    return key


def load_questions(dataset_path, dataset, n, seed):
    data_file = os.path.join(dataset_path, dataset, "valid_preprocessed.json")
    with open(data_file) as f:
        contents = json.load(f)
    random.seed(seed)
    random.shuffle(contents)
    if n != -1:
        contents = contents[:n]
    return contents


def run_question(user_proxy, chatbot, item, long_term_memory, num_shots):
    question = item["template"]
    answer = item["answer"]
    gt_answer = answer if isinstance(answer, str) else ", ".join(answer)

    result = {
        "id": item.get("id", ""),
        "question": question,
        "ground_truth": gt_answer,
        "predicted_answer": "",
        "is_correct": False,
        "status": "incompleted",
        "num_tries": 0,
        "last_code": "",
        "last_error": "",
        "agent_trace": [],
    }

    try:
        user_proxy.update_memory(num_shots, long_term_memory)
        user_proxy.initiate_chat(chatbot, message=question)

        logs = user_proxy._oai_messages
        trace = []
        num_tries = 0
        last_code = ""
        last_error = ""

        for agent in list(logs.keys()):
            for msg in logs[agent]:
                if msg.get("content") is not None:
                    cleaned = strip_examples(str(msg["content"]))
                    trace.append(cleaned)
                    if "error" in cleaned.lower() or "Error" in cleaned:
                        last_error = cleaned
                elif msg.get("function_call"):
                    argums = msg["function_call"]["arguments"]
                    if isinstance(argums, dict) and "cell" in argums:
                        trace.append(argums["cell"])
                        last_code = argums["cell"]
                        num_tries += 1
                    else:
                        trace.append(str(argums))
                        last_code = str(argums)
                        num_tries += 1

        result["agent_trace"] = trace
        result["num_tries"] = max(num_tries, 1)
        result["last_code"] = last_code
        result["last_error"] = last_error

        logs_string = "\n".join(trace)
        term_idx = logs_string.rfind("TERMINATE")
        prediction_block = logs_string[:term_idx] if term_idx != -1 else logs_string

        is_correct = judge(prediction_block, gt_answer)
        result["predicted_answer"] = prediction_block.strip().split("\n")[-1]
        result["is_correct"] = is_correct
        result["status"] = "correct" if is_correct else "wrong"

    except CompilerSuccessButExecFailed as e:
        result["status"] = "incompleted"
        result["last_error"] = str(e)
        result["agent_trace"].append("[INCOMPLETED: compiler said SUCCESS but real exec failed]")
    except Exception as e:
        result["status"] = "incompleted"
        result["last_error"] = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: exception] {e}")

    return result


def save_outputs(output_dir, results):
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    errors = [r for r in results if r["status"] in ("wrong", "incompleted")]
    with open(os.path.join(output_dir, "errors.json"), "w") as f:
        json.dump(errors, f, indent=2)

    correct = sum(1 for r in results if r["status"] == "correct")
    wrong = sum(1 for r in results if r["status"] == "wrong")
    incompleted = sum(1 for r in results if r["status"] == "incompleted")
    total_tries = sum(r["num_tries"] for r in results)

    labels = ["Correct", "Wrong", "Incompleted", "Total Tries"]
    values = [correct, wrong, incompleted, total_tries]
    colors = ["#4CAF50", "#F44336", "#FF9800", "#2196F3"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.barh(labels, values, color=colors)
    ax.bar_label(bars, padding=3)
    ax.set_xlabel("Count")
    ax.set_title("EHRAgent Pipeline Results")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "summary_plot.png"), dpi=120)
    plt.close()

    print(f"\nResults saved to: {output_dir}")
    print(f"  Correct:     {correct}/{len(results)}")
    print(f"  Wrong:       {wrong}/{len(results)}")
    print(f"  Incompleted: {incompleted}/{len(results)}")
    print(f"  Total tries: {total_tries}")


def main():
    args = parse_args()
    api_key = get_api_key()

    tabtools.configure(args.dataset_path, args.dataset)

    if args.compiler_agent:
        mode = "compiler_agent"
    elif args.newdebugger:
        mode = "newdebugger"
    else:
        mode = "baseline"

    output_dir = os.path.join(OUTPUT_BASE, _output_dir_name(args.dataset, mode, args.n, args.seed))

    questions = load_questions(args.dataset_path, args.dataset, args.n, args.seed)
    print(f"Running {len(questions)} questions | dataset={args.dataset} | mode={mode} | model={args.model}")

    if args.dataset == "mimic_iii":
        from prompts_mimic import EHRAgent_4Shots_Knowledge
    else:
        from prompts_eicu import EHRAgent_4Shots_Knowledge

    long_term_memory = []
    for item in EHRAgent_4Shots_Knowledge.strip().split("\n\n"):
        item = item.split("Question:")[-1]
        question_part = item.split("\nKnowledge:\n")[0]
        rest = item.split("\nKnowledge:\n")[-1]
        knowledge_part = rest.split("\nSolution:")[0]
        code_part = rest.split("\nSolution:")[-1]
        long_term_memory.append({
            "question": question_part,
            "knowledge": knowledge_part,
            "code": code_part,
        })

    cfg = openai_config(args.model, api_key)
    config_list = [cfg]
    llm_cfg = llm_config_list(args.seed, config_list)

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
        model=args.model,
        is_termination_msg=lambda x: x.get("content", "") and x.get("content", "").rstrip().endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={"work_dir": "coding"},
    )
    user_proxy.register_function(function_map={"python": run_code})
    user_proxy.register_dataset(args.dataset)

    if args.compiler_agent:
        if args.dataset == "mimic_iii":
            from prompts_mimic import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        else:
            from prompts_eicu import CompilerAgent_System_Message, CompilerAgent_FewShot_Examples
        ca = CompilerAgent(
            api_key=api_key, model=args.model, dataset=args.dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerAgent_System_Message,
        )
        user_proxy.set_mode("compiler_agent", compiler_agent=ca)

    elif args.newdebugger:
        if args.dataset == "mimic_iii":
            from prompts_mimic import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples
        else:
            from prompts_eicu import CompilerDebuggerAgent_System_Message, CompilerAgent_FewShot_Examples
        cda = CompilerDebuggerAgent(
            api_key=api_key, model=args.model, dataset=args.dataset,
            few_shot_examples=CompilerAgent_FewShot_Examples,
            system_message=CompilerDebuggerAgent_System_Message,
        )
        user_proxy.set_mode("newdebugger", compiler_debugger_agent=cda)

    results = []
    start_time = time.time()

    for i, item in enumerate(questions):
        print(f"\n[{i+1}/{len(questions)}] {item['template'][:80]}...")
        result = run_question(user_proxy, chatbot, item, long_term_memory, args.num_shots)
        result["id"] = item.get("id", str(i))
        results.append(result)

        if result["status"] == "correct" and result["last_code"]:
            long_term_memory.append({
                "question": item["template"],
                "knowledge": user_proxy.knowledge,
                "code": result["last_code"],
            })

        print(f"  -> {result['status'].upper()} | tries={result['num_tries']}")

    elapsed = time.time() - start_time
    print(f"\nTotal time: {elapsed:.1f}s")
    save_outputs(output_dir, results)


if __name__ == "__main__":
    main()
