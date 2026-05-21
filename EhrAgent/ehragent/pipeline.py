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


if __name__ == "__main__":
    pass  # execution loop added next
