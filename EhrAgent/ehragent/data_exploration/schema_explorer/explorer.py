# EhrAgent/ehragent/data_exploration/schema_explorer/explorer.py
import json
import anthropic

from .sql_executor import SQLExecutor
from . import prompts as P

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_RETRIES = 3


class SchemaExplorer:
    """Probes a SQLite EHR database and synthesizes a schema string using claude-haiku."""

    def __init__(self, db_path, api_key, model=HAIKU_MODEL):
        self.executor = SQLExecutor(db_path)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.tokens_used = 0
        self.api_calls = 0

    def explore(self):
        """Run all 3 stages. Returns (schema_str, trace_dict)."""
        self.tokens_used = 0
        self.api_calls = 0
        trace = {}

        all_tables, clusters, representatives = self._stage1(trace)
        column_data = self._stage2(representatives, trace)
        schema_str = self._stage3(clusters, column_data, trace)

        trace["tokens_used"] = self.tokens_used
        trace["api_calls"] = self.api_calls
        return schema_str, trace

    # ── LLM helper ────────────────────────────────────────────────────────────

    def _llm(self, prompt):
        self.api_calls += 1
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        self.tokens_used += response.usage.input_tokens + response.usage.output_tokens
        return response.content[0].text

    # ── Stage 1: Table discovery + clustering ──────────────────────────────────

    def _stage1(self, trace):
        result, error = self.executor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        if error or result is None:
            raise RuntimeError(f"Cannot list tables: {error}")

        all_tables = [row[0] for row in result["rows"]]

        prompt = P.CLUSTER_TABLES.format(table_list=", ".join(all_tables))
        response_text = self._llm(prompt)

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            parsed = {"clusters": {}, "singletons": all_tables}

        clusters = {}
        representatives = {}

        for label, info in parsed.get("clusters", {}).items():
            members = info.get("members", [])
            rep = info.get("representative") or (members[0] if members else None)
            if rep:
                clusters[label] = members
                representatives[label] = rep

        for singleton in parsed.get("singletons", []):
            clusters[singleton] = [singleton]
            representatives[singleton] = singleton

        trace["stage_1"] = {
            "all_tables": all_tables,
            "clusters": clusters,
            "representative_tables": list(representatives.values()),
            "llm_prompt": prompt,
            "llm_response": response_text,
        }
        return all_tables, clusters, representatives

    # ── Stage 2: Column probing ────────────────────────────────────────────────

    def _stage2(self, representatives, trace):
        column_data = {}
        trace["stage_2"] = []

        for cluster_label, rep_table in representatives.items():
            table_trace = {"table": rep_table, "cluster": cluster_label, "queries": []}

            pragma_result, _ = self._probe(f"PRAGMA table_info({rep_table})", table_trace)
            sample_result, _ = self._probe(f"SELECT * FROM {rep_table} LIMIT 3", table_trace)

            followup_queries = self._decide_followup(rep_table, pragma_result, sample_result, table_trace)

            followup_results = []
            for fq in followup_queries:
                fq_result, fq_error = self._probe(fq["sql"], table_trace)
                followup_results.append({
                    "purpose": fq["purpose"],
                    "result": fq_result,
                    "error": fq_error,
                })

            column_data[rep_table] = {
                "pragma": pragma_result,
                "sample": sample_result,
                "followups": followup_results,
            }
            trace["stage_2"].append(table_trace)

        return column_data

    def _probe(self, sql, table_trace):
        """Execute SQL, retrying with LLM rewrite on error. Returns (result, error)."""
        current_sql = sql
        for attempt in range(MAX_RETRIES):
            result, error = self.executor.execute(current_sql)
            entry = {
                "attempt": attempt + 1,
                "sql": current_sql,
                "result": result,
                "error": error,
            }
            table_trace["queries"].append(entry)

            if result is not None:
                return result, None

            if attempt < MAX_RETRIES - 1:
                rewrite_prompt = P.REWRITE_QUERY.format(sql=current_sql, error=error)
                rewritten = self._llm(rewrite_prompt).strip()
                entry["rewrite_prompt"] = rewrite_prompt
                entry["rewritten_to"] = rewritten
                current_sql = rewritten

        return None, error

    def _decide_followup(self, table, pragma_result, sample_result, table_trace):
        pragma_str = json.dumps(pragma_result, default=str) if pragma_result else "unavailable"
        sample_str = json.dumps(sample_result, default=str) if sample_result else "unavailable"

        prompt = P.DECIDE_FOLLOWUP.format(
            table=table,
            pragma_result=pragma_str,
            sample_result=sample_str,
        )
        response_text = self._llm(prompt)
        table_trace["followup_decision"] = {"prompt": prompt, "response": response_text}

        try:
            parsed = json.loads(response_text)
            if parsed.get("needs_followup"):
                return parsed.get("followup_queries", [])[:2]
        except json.JSONDecodeError:
            pass
        return []

    # ── Stage 3: Schema synthesis ──────────────────────────────────────────────

    def _stage3(self, clusters, column_data, trace):
        explored = set(column_data.keys())
        skipped = []
        for label, members in clusters.items():
            for m in members:
                if m not in explored:
                    skipped.append(m)

        exploration_json = json.dumps(column_data, indent=2, default=str)
        skipped_str = ", ".join(skipped) if skipped else "(none)"

        prompt = P.SYNTHESIZE_SCHEMA.format(
            exploration_json=exploration_json,
            skipped_tables=skipped_str,
        )
        schema_str = self._llm(prompt)

        trace["stage_3"] = {
            "prompt": prompt,
            "schema_output": schema_str,
            "skipped_tables": skipped,
        }
        return schema_str
