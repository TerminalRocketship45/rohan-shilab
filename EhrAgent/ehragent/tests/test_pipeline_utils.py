import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest

# ── judge() tests ────────────────────────────────────────────────────────────

from pipeline import judge

def test_judge_exact_match():
    assert judge("the answer is tp", "tp") is True

def test_judge_true_false_normalization():
    assert judge("answer = True", "1") is True
    assert judge("answer = False", "0") is True

def test_judge_yes_no_normalization():
    assert judge("the answer is yes", "1") is True
    assert judge("answer: no", "0") is True

def test_judge_list_answer_all_present():
    assert judge("po, oral, PO", "po, oral") is True

def test_judge_wrong_answer():
    assert judge("the answer is 42", "tp") is False

def test_judge_trailing_zero():
    assert judge("answer: 3", "3.0") is True

# ── strip_examples() tests ───────────────────────────────────────────────────

from pipeline import strip_examples

def test_strip_examples_removes_everything_before_marker():
    msg = "LOTS OF EXAMPLES HERE\n(END OF EXAMPLES)\nQuestion: foo\nSolution: bar"
    result = strip_examples(msg)
    assert "LOTS OF EXAMPLES" not in result
    assert "Question: foo" in result

def test_strip_examples_no_marker_returns_unchanged():
    msg = "No examples section here"
    assert strip_examples(msg) == msg

def test_strip_examples_empty_string():
    assert strip_examples("") == ""

# ── _output_dir_name() tests ─────────────────────────────────────────────────

from pipeline import _output_dir_name

def test_output_dir_name_baseline():
    name = _output_dir_name("mimic_iii", "baseline", 30, 42)
    assert "mimic_iii" in name
    assert "baseline" in name
    assert "n30" in name
    assert "seed42" in name

def test_output_dir_name_compiler_agent():
    name = _output_dir_name("eicu", "compiler_agent", 10, 99)
    assert "compiler_agent" in name
    assert "n10" in name
