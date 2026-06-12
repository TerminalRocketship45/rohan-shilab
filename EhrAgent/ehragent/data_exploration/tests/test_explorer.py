# EhrAgent/ehragent/data_exploration/tests/test_explorer.py
import sys, os, sqlite3, tempfile, json
from unittest.mock import MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from schema_explorer.explorer import SchemaExplorer


def _make_ehr_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(f.name)
    conn.execute("CREATE TABLE patients (SUBJECT_ID INTEGER, GENDER TEXT, DOB TEXT)")
    conn.execute("CREATE TABLE admissions (HADM_ID INTEGER, SUBJECT_ID INTEGER, ADMITTIME TEXT)")
    conn.execute("INSERT INTO patients VALUES (1, 'M', '1980-01-01')")
    conn.execute("INSERT INTO admissions VALUES (100, 1, '2020-05-01')")
    conn.commit()
    conn.close()
    return f.name


def _make_mock_anthropic(responses):
    """responses: list of strings, returned in order from client.messages.create."""
    mock_client = MagicMock()
    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    call_count = [0]

    def create_side_effect(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        text = responses[idx % len(responses)]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=text)]
        mock_response.usage = mock_usage
        return mock_response

    mock_client.messages.create.side_effect = create_side_effect
    return mock_client


def test_stage1_discovers_tables():
    db_path = _make_ehr_db()
    cluster_response = json.dumps({
        "clusters": {},
        "singletons": ["patients", "admissions"]
    })
    followup_response = json.dumps({"needs_followup": False, "followup_queries": []})
    schema_response = "Available tables and columns:\n- patients: SUBJECT_ID (INTEGER), GENDER (TEXT), DOB (TEXT)\n  Description: Stores patient demographics."

    mock_client = _make_mock_anthropic([cluster_response, followup_response, followup_response, schema_response])

    explorer = SchemaExplorer(db_path=db_path, api_key="fake")
    explorer.client = mock_client

    schema_str, trace = explorer.explore()

    assert "patients" in trace["stage_1"]["all_tables"]
    assert "admissions" in trace["stage_1"]["all_tables"]


def test_stage3_returns_schema_string():
    db_path = _make_ehr_db()
    cluster_response = json.dumps({
        "clusters": {},
        "singletons": ["patients", "admissions"]
    })
    followup_response = json.dumps({"needs_followup": False, "followup_queries": []})
    schema_response = "Available tables and columns:\n- patients: SUBJECT_ID (INTEGER)\n  Description: Patient table."

    mock_client = _make_mock_anthropic([cluster_response, followup_response, followup_response, schema_response])

    explorer = SchemaExplorer(db_path=db_path, api_key="fake")
    explorer.client = mock_client

    schema_str, trace = explorer.explore()

    assert "patients" in schema_str
    assert "stage_3" in trace
    assert trace["tokens_used"] > 0
    assert trace["api_calls"] > 0


def test_bad_query_retried():
    db_path = _make_ehr_db()
    cluster_response = json.dumps({
        "clusters": {},
        "singletons": ["patients"]
    })
    followup_response = json.dumps({"needs_followup": False, "followup_queries": []})
    schema_response = "Available tables and columns:\n- patients: SUBJECT_ID (INTEGER)\n  Description: Patients."

    mock_client = _make_mock_anthropic([
        cluster_response,
        "SELECT SUBJECT_ID, GENDER, DOB FROM patients LIMIT 3",  # rewrite with different SQL
        followup_response,
        schema_response,
    ])

    explorer = SchemaExplorer(db_path=db_path, api_key="fake")
    explorer.client = mock_client

    # Patch execute to fail on the first SELECT LIMIT call, succeed on retry
    original_execute = explorer.executor.execute
    failed = [False]

    def patched_execute(sql, row_limit=20):
        if "SELECT * FROM patients LIMIT 3" in sql and not failed[0]:
            failed[0] = True
            return None, "simulated error: forced failure"
        return original_execute(sql, row_limit)

    explorer.executor.execute = patched_execute
    schema_str, trace = explorer.explore()

    # Verify retry was attempted: the stage_2 queries for patients should have 2 LIMIT entries
    patients_stage = next(s for s in trace["stage_2"] if s["table"] == "patients")
    limit_queries = [q for q in patients_stage["queries"] if "LIMIT" in q["sql"]]
    assert len(limit_queries) == 2, f"Expected 2 LIMIT queries (original + retry), got {len(limit_queries)}: {[q['sql'] for q in limit_queries]}"
    assert limit_queries[0]["error"] is not None, "First LIMIT query should have failed"
    assert limit_queries[1]["error"] is None, "Retry LIMIT query should have succeeded"
