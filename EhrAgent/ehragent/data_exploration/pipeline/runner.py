# EhrAgent/ehragent/data_exploration/pipeline/runner.py
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_EHRAGENT_INNER = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _EHRAGENT_INNER not in sys.path:
    sys.path.insert(0, _EHRAGENT_INNER)

from compiler_agent import CompilerSuccessButExecFailed
from pipeline.judge import judge

NUM_SHOTS = 4


def _extract_code(arguments):
    if isinstance(arguments, dict):
        return arguments.get("cell", str(arguments))
    try:
        parsed = json.loads(arguments)
        return parsed.get("cell", str(parsed))
    except Exception:
        return str(arguments)


def _strip_examples(message):
    marker = "(END OF EXAMPLES)"
    if marker in message:
        return message[message.index(marker) + len(marker):]
    return message


def run_question(user_proxy, chatbot, item, long_term_memory):
    """Run one question with the given agents.

    Returns a result dict compatible with run_pipeline.py output format.
    """
    question = item["template"]
    answer = item["answer"]
    gt_answer = answer if isinstance(answer, str) else ", ".join(answer)

    result = {
        "id": item.get("id", ""),
        "question": question,
        "ground_truth": gt_answer,
        "predicted_answer": "",
        "last_exec_result": "",
        "is_correct": False,
        "status": "incompleted",
        "incompleted_reason": None,
        "num_tries": 0,
        "last_code": "",
        "last_error": "",
        "agent_trace": [],
    }

    try:
        user_proxy.update_memory(NUM_SHOTS, long_term_memory)
        user_proxy.initiate_chat(chatbot, message=question)

        logs = user_proxy.chat_messages
        trace, num_tries, last_code, last_error = [], 0, "", ""

        for agent in list(logs.keys()):
            for msg in logs[agent]:
                content = msg.get("content")
                if content is not None and content != "":
                    cleaned = _strip_examples(str(content))
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
        result["num_tries"] = max(num_tries, 1)
        result["last_code"] = last_code
        result["last_error"] = last_error

        exec_results = [
            trace[i].strip()
            for i in range(2, len(trace), 2)
            if "TERMINATE" not in trace[i]
        ]
        result["last_exec_result"] = exec_results[-1] if exec_results else ""

        logs_string = "\n".join(trace)
        term_idx = logs_string.rfind("TERMINATE")
        prediction_block = logs_string[:term_idx] if term_idx != -1 else logs_string

        is_correct = judge(prediction_block, gt_answer)
        result["predicted_answer"] = prediction_block.strip().split("\n")[-1]
        result["is_correct"] = is_correct
        result["status"] = "correct" if is_correct else "wrong"

    except CompilerSuccessButExecFailed as e:
        result["status"] = "incompleted"
        result["incompleted_reason"] = "compiler_success_exec_failed"
        result["last_error"] = str(e)
        result["last_exec_result"] = str(e)
        result["agent_trace"].append("[INCOMPLETED: compiler said SUCCESS but real exec failed]")

    except Exception as e:
        result["status"] = "incompleted"
        result["incompleted_reason"] = "exception"
        result["last_error"] = str(e)
        result["agent_trace"].append(f"[INCOMPLETED: exception] {e}")

    return result
