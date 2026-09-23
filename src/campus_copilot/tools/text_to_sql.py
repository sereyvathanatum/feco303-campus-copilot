"""Text-to-SQL sandbox for E07 (`sql.mode = text_to_sql`). The only place with model-written SQL.

The sandbox is a read-only connection whose allow-list drops every `account_id`
column, because the authorizer works per column and cannot scope rows. A model
can therefore never read or filter on another account's records. Results are
capped at 50 rows, and each denial names the authorizer rule that stopped it.
"""

from __future__ import annotations

import re
import sqlite3

from pydantic import BaseModel, Field

from ..db import connection
from .registry import ToolContext, ToolSpec

ROW_CAP = 50
SANDBOX_ALLOW = {table: {c for c in cols if c != "account_id"} for table, cols in connection.READ_ALLOW.items()}
SANDBOX_ALLOW.pop("enrollments")  # only account_id and course_code; without account_id it leaks nothing useful

SCHEMA_TEXT = "\n".join(f"{table}({', '.join(sorted(cols))})" for table, cols in sorted(SANDBOX_ALLOW.items()))
PROMPT = ("Write one SQLite SELECT statement that answers `question` over these tables:\n" + SCHEMA_TEXT +
          "\nWeekdays are lowercase English names. Output only the SQL.")


class SqlArgs(BaseModel):
    sql: str = Field(description="One SQLite SELECT statement over the campus tables.")


def run_sql(ctx: ToolContext, args: SqlArgs) -> dict:
    conn = connection.read_connection(ctx.db_path, allow=SANDBOX_ALLOW)
    sql = args.sql.strip().rstrip(";")
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = [dict(zip(columns, row)) for row in cursor.fetchmany(ROW_CAP + 1)]
    except (sqlite3.DatabaseError, sqlite3.ProgrammingError, sqlite3.Warning) as exc:
        rule = conn.authorizer_log.denials[-1] if conn.authorizer_log.denials else f"sqlite: {exc}"
        return {"ok": False, "error": f"query refused ({rule})", "summary": f"The query was refused: {rule}.",
                "data": {"sql": sql, "stopped_by": rule}}
    capped = len(rows) > ROW_CAP
    rows = rows[:ROW_CAP]
    return {"data": {"sql": sql, "rows": rows, "capped": capped},
            "summary": f"{len(rows)} row(s){' (capped at 50)' if capped else ''} for: {sql}"}


def generate_sql(llm, question: str) -> str:
    reply = llm.complete([{"role": "system", "content": PROMPT}, {"role": "user", "content": f"question: {question}"}],
                         task="generic", payload={"text": _stub_sql(question)}, max_tokens=200)
    text = re.sub(r"^```(?:sql)?|```$", "", reply.text.strip(), flags=re.MULTILINE).strip()
    return text


def _stub_sql(question: str) -> str:
    """Offline stand-in for a model writing SQL: a naive keyword mapping, good enough for the E07 comparison."""
    q = question.lower()
    code = re.search(r"\b([a-z]{4}\d{3})\b", q)
    if "loan" in q:
        account = re.search(r"\ba\d{4}\b", q)
        where = f" WHERE account_id = '{account.group(0).upper()}'" if account else ""
        return f"SELECT isbn, due_date FROM loans{where}"
    if "room" in q:
        return "SELECT id, capacity, has_projector FROM rooms WHERE has_projector = 1"
    if "deadline" in q or "due" in q:
        return "SELECT course_code, title, due_at FROM assignments" + (f" WHERE course_code = '{code.group(1).upper()}'"
                                                                       if code else "") + " ORDER BY due_at"
    if code:
        return f"SELECT weekday, start, \"end\", room_id, kind FROM sessions WHERE course_code = '{code.group(1).upper()}'"
    return "SELECT title, date FROM events ORDER BY date LIMIT 10"


SPECS = [ToolSpec("run_sql", "E07 only: run one read-only SELECT in the text-to-SQL sandbox (50-row cap).", SqlArgs,
                  run_sql, source="sandboxed read connection")]
