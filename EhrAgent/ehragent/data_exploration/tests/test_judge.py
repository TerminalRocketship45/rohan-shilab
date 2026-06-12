import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pipeline.judge import judge


def test_exact_match():
    assert judge("The answer is 42", "42") is True


def test_boolean_true():
    assert judge("True", "1") is True


def test_boolean_false():
    assert judge("False", "0") is True


def test_yes_no():
    assert judge("yes", "1") is True
    assert judge("no", "0") is True


def test_none_answer():
    assert judge("0", "None") is True


def test_list_answer():
    assert judge("penicillin, amoxicillin", "penicillin, amoxicillin") is True


def test_trailing_zero():
    assert judge("3.0", "3") is True


def test_no_match():
    assert judge("The answer is 5", "42") is False
