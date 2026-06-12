import sys, os, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from schema_explorer.sql_executor import SQLExecutor


def _make_db():
    """Create a temp SQLite db with one table for testing."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(f.name)
    conn.execute("CREATE TABLE patients (id INTEGER, name TEXT, age INTEGER)")
    conn.execute("INSERT INTO patients VALUES (1, 'Alice', 30)")
    conn.execute("INSERT INTO patients VALUES (2, 'Bob', 25)")
    conn.commit()
    conn.close()
    return f.name


def test_successful_query():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT * FROM patients")
    assert error is None
    assert result["columns"] == ["id", "name", "age"]
    assert len(result["rows"]) == 2
    assert result["rows"][0] == [1, "Alice", 30]


def test_pragma_query():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("PRAGMA table_info(patients)")
    assert error is None
    assert result["columns"] == ["cid", "name", "type", "notnull", "dflt_value", "pk"]
    assert any(row[1] == "id" for row in result["rows"])


def test_list_tables():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT name FROM sqlite_master WHERE type='table'")
    assert error is None
    table_names = [row[0] for row in result["rows"]]
    assert "patients" in table_names


def test_bad_sql_returns_error():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT * FROM nonexistent_table")
    assert result is None
    assert error is not None
    assert "nonexistent_table" in error.lower() or "no such table" in error.lower()


def test_row_limit():
    db_path = _make_db()
    ex = SQLExecutor(db_path)
    result, error = ex.execute("SELECT * FROM patients", row_limit=1)
    assert error is None
    assert len(result["rows"]) == 1
