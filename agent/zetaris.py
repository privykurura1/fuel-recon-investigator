"""Data layer: run one SQL statement through the Zetaris REST API.

Per the hackathon setup guide: POST {ZETARIS_REST_URL}/sql-editor/sqls/run with a
bearer API key, X-Org-ID and a fresh UUID X-Request-ID. The guide only documents
the `data` field of the reply (a list of rows), so column names are picked up
if Zetaris sends them and skipped otherwise.
"""
import re
import uuid
from decimal import Decimal, InvalidOperation

import requests

from . import config


class SQLError(RuntimeError):
    pass


FORBIDDEN = re.compile(r"^\s*(insert|update|delete|drop|create|alter|register|truncate|grant)\b", re.I)


def run_sql(sql: str, limit: int = 500):
    """Returns (columns or None, rows). Raises SQLError with Zetaris's message."""
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise SQLError("Send exactly one statement, without semicolons.")
    if FORBIDDEN.match(sql):
        raise SQLError("Read-only: only SELECT / SHOW / DESCRIBE statements are allowed.")
    key = config.need("ZETARIS_API_KEY")
    try:
        r = requests.post(
            config.ZETARIS_REST_URL + "/sql-editor/sqls/run",
            headers={
                "Authorization": "Bearer " + key,
                "X-Org-ID": config.ZETARIS_ORG_ID,
                "X-Request-ID": str(uuid.uuid4()),
            },
            json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
            timeout=120,
        )
    except requests.RequestException as exc:
        raise SQLError(f"Cannot reach Zetaris at {config.ZETARIS_REST_URL}: {exc}") from exc
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or not isinstance(body, dict) or "data" not in body:
        raise SQLError(f"Zetaris {r.status_code}: {short_error(body or r.text)}")
    rows = [[clean(v) for v in row] for row in (body.get("data") or [])]
    return find_columns(body), rows


def find_columns(body: dict):
    for key in ("columns", "columnNames", "header", "headers", "schema", "fields"):
        cols = body.get(key)
        if isinstance(cols, list) and cols:
            return [c.get("name", str(c)) if isinstance(c, dict) else str(c) for c in cols]
    return None


def clean(v):
    """Turn '9620.000000000000000' into 9620 and '13.80000' into 13.8."""
    if isinstance(v, str) and re.fullmatch(r"-?\d+\.\d+", v):
        try:
            d = Decimal(v).quantize(Decimal("0.01"))
            return int(d) if d == d.to_integral() else float(d)
        except InvalidOperation:
            return v
    if isinstance(v, float):
        return round(v, 2)
    return v


def short_error(body) -> str:
    """Keep the useful first lines of a Java stack trace."""
    text = body if isinstance(body, str) else str(body.get("message") or body.get("error") or body)
    keep = []
    for line in text.splitlines():
        if line.strip().startswith("at ") or line.strip().startswith("..."):
            break
        keep.append(line.strip())
    return " ".join(x for x in keep if x)[:600]


def as_table(columns, rows, max_rows=40) -> str:
    """Compact text table for the model and the console."""
    shown = rows[:max_rows]
    lines = []
    if columns:
        lines.append(" | ".join(columns))
    for row in shown:
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    if len(rows) > max_rows:
        lines.append(f"... {len(rows) - max_rows} more rows not shown (aggregate or filter to see them)")
    if not rows:
        lines.append("(no rows)")
    return "\n".join(lines)
