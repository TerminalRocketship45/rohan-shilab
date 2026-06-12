import sqlite3


class SQLExecutor:
    def __init__(self, db_path):
        self.db_path = db_path

    def execute(self, sql, row_limit=20):
        """Execute SQL against the SQLite db.

        Returns (result_dict, None) on success or (None, error_str) on failure.
        result_dict = {"columns": [...], "rows": [[...], ...]}
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchmany(row_limit)
            col_names = (
                [desc[0] for desc in cursor.description]
                if cursor.description
                else []
            )
            return {"columns": col_names, "rows": [list(r) for r in rows]}, None
        except Exception as e:
            return None, str(e)
        finally:
            if conn is not None:
                conn.close()
