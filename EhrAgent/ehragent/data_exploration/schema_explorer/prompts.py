# EhrAgent/ehragent/data_exploration/schema_explorer/prompts.py

CLUSTER_TABLES = """You are analyzing an EHR (Electronic Health Record) SQLite database.
Given these table names, identify clusters of tables that share the same schema structure
(e.g., partitioned by year, region, or category). Tables in the same cluster can be
represented by a single schema exploration.

Table names: {table_list}

Return ONLY valid JSON with no markdown fences:
{{
  "clusters": {{
    "cluster_label": {{
      "members": ["table_a", "table_b"],
      "representative": "table_a"
    }}
  }},
  "singletons": ["table_c", "table_d"]
}}

Rules:
- If no tables form natural clusters, put all in "singletons"
- Each table must appear exactly once across clusters and singletons
- Pick the first alphabetically as representative when tables are similar"""

DECIDE_FOLLOWUP = """You are exploring the schema of a SQLite EHR database table to understand
what it contains, without access to real patient data.

Table: {table}

PRAGMA table_info result (columns and declared types):
{pragma_result}

Sample rows (SELECT * LIMIT 3):
{sample_result}

Do any columns need a follow-up query to understand their values or relationships?
Examples of columns that need follow-up: coded IDs that reference other tables (ITEMID, ICD9_CODE),
columns with unclear ranges, or columns with complex values.

Return ONLY valid JSON, no markdown fences:
{{
  "needs_followup": true,
  "followup_queries": [
    {{"purpose": "short description", "sql": "SELECT ..."}}
  ]
}}

Limit to at most 2 follow-up queries. If nothing needs follow-up:
{{
  "needs_followup": false,
  "followup_queries": []
}}"""

REWRITE_QUERY = """A SQLite query for exploring an EHR database schema failed.

Failed SQL: {sql}
Error message: {error}

This is SQLite — use PRAGMA syntax, not INFORMATION_SCHEMA. Rewrite the query to fix the error.
Return ONLY the corrected SQL query, nothing else."""

SYNTHESIZE_SCHEMA = """You are generating a database schema description for an EHR coding agent.
The agent uses this description to write Python code that queries the database.

Below is the raw exploration data from probing the SQLite database.

Fully explored tables (PRAGMA + sample data):
{exploration_json}

Tables NOT fully explored (cluster members; share schema with their representative):
{skipped_tables}

Generate a schema description in EXACTLY this format — one line per table, columns in parentheses,
plus a one-sentence description on the next line:

Available tables and columns:
- table_name: COL1 (TYPE), COL2 (TYPE), COL3 (TYPE)
  Description: This table contains [what it stores, inferred from column names and sample data].

Rules:
- Use UPPERCASE for column names (as they appear in the data)
- Use the SQLite declared type in parentheses; use TEXT if unknown
- List all columns from PRAGMA for fully explored tables
- For skipped tables, include a line: - table_name: (see representative TABLE_X for schema)
- Do not invent columns; only use what the PRAGMA showed
- Keep each description to one sentence"""
