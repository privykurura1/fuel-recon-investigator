"""Run first: python check_setup.py  -> four PASS lines means the agent can run."""
from agent.llm import chat
from agent.zetaris import as_table, run_sql

checks = []


def check(name, fn):
    try:
        detail = fn()
        checks.append(("PASS", name, detail))
    except BaseException as exc:  # includes SystemExit from a missing .env value
        checks.append(("FAIL", name, str(exc)[:300]))


def zetaris_basic():
    cols, rows = run_sql("SELECT 1 AS one")
    return f"reply {rows} columns={cols}"


def zetaris_station():
    cols, rows = run_sql("SELECT delivery_note AS dn, invoiced_litres AS litres FROM supplier.delivery_notes ORDER BY dn")
    return f"{len(rows)} delivery notes; first rows:\n" + as_table(cols, rows, 3)


def nightshift():
    text, receipt = chat([{"role": "user", "content": "Reply with the single word: ready"}])
    return f"reply={text[:40]!r} routed_model={receipt['routed_model']} receipt={receipt['receipt_id']}"


def station_db_upload():
    from agent.loader import _connect
    with _connect("forecourt") as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pump_meter_readings")
        n = cur.fetchone()[0]
    return f"station database reachable for uploads ({n} meter readings loaded)"


check("Zetaris answers SQL over REST", zetaris_basic)
check("Station data reachable through Zetaris", zetaris_station)
check("Nightshift -> Nemotron replies", nightshift)
check("Upload path: station database (port 5433)", station_db_upload)
for status, name, detail in checks:
    print(f"{status}  {name}\n      {detail}\n")
