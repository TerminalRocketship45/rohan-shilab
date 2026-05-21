import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import tools.tabtools as tabtools

def setup_function():
    tabtools._DATASET_PATH = None
    tabtools._DATASET = None

def test_configure_sets_dataset_path():
    tabtools.configure("/data/ehrsql", "mimic_iii")
    assert tabtools._DATASET_PATH == "/data/ehrsql"

def test_configure_sets_dataset():
    tabtools.configure("/data/ehrsql", "eicu")
    assert tabtools._DATASET == "eicu"

def test_db_loader_raises_keyerror_for_unknown_table():
    tabtools.configure("/fake/path", "mimic_iii")
    with pytest.raises(KeyError):
        tabtools.db_loader("nonexistent_table")

def test_db_loader_raises_keyerror_for_eicu_unknown_table():
    tabtools.configure("/fake/path", "eicu")
    with pytest.raises(KeyError):
        tabtools.db_loader("admissions")  # admissions is mimic_iii only
