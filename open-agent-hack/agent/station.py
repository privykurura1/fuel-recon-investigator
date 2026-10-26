"""Which station's data is loaded, read live from Zetaris so the agent never assumes.

The facts block tells the model the real date range, tank/pump IDs and shift names of
whatever records the manager uploaded (or the Sunrise Fuels sample).
"""
import re
from datetime import datetime

from . import loader
from .zetaris import SQLError, run_sql


def _hhmm(v) -> str:
    m = re.search(r"(\d{1,2}):(\d{2})", str(v or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else "?"


def _day(v) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(v or ""))
    return m.group(0) if m else str(v)


def _q(text):
    return "'" + str(text).replace("'", "''") + "'"


def facts() -> dict:
    """Returns {'name', 'scope', 'from', 'to', 'text'}; 'text' goes into the system prompt."""
    info = loader.current_station()
    out = {"name": info.get("name", "My station"), "scope": info.get("scope", ""),
           "from": info.get("summary", {}).get("from"), "to": info.get("summary", {}).get("to")}
    try:
        _, r = run_sql("SELECT MIN(shift_date) AS first_day, MAX(shift_date) AS last_day FROM forecourt.shifts")
        if r and r[0][0]:
            out["from"], out["to"] = _day(r[0][0]), _day(r[0][1])
        _, tanks = run_sql("SELECT tank_id, fuel_type FROM forecourt.tanks ORDER BY tank_id")
        _, pumps = run_sql("SELECT pump_id, tank_id FROM forecourt.pumps ORDER BY pump_id")
        _, shifts = run_sql("SELECT shift_name, MIN(starts_at) AS starts_at, MIN(ends_at) AS ends_at "
                            "FROM forecourt.shifts GROUP BY shift_name ORDER BY MIN(starts_at)")
    except SQLError as exc:
        out["text"] = (f"\nDATA FACTS: Station: {out['name']}. The data covers {out['from']} to {out['to']}. "
                       f"(Station details could not be read just now: {exc}. Query forecourt.tanks, "
                       "forecourt.pumps and forecourt.shifts first to learn the IDs.)\nMoney: every price and amount in the data is in US dollars. Always write money as US$ (e.g. US$630.00), never any other currency.\n")
        return out

    year = (out["to"] or "")[:4] or "the data's year"
    try:
        d0 = datetime.strptime(out["from"], "%Y-%m-%d")
    except (TypeError, ValueError):
        d0 = datetime(int(year) if year.isdigit() else 2026, 10, 8)
    date_eg = f"'{d0.day} {d0:%B}' = DATE '{d0:%Y-%m-%d}'"
    tank_txt = ", ".join(f"{_q(t)} {f}" for t, f in tanks) or "none"
    pump_txt = ", ".join(f"{_q(p)} (tank {t})" for p, t in pumps) or "none"
    shift_txt = ", ".join(f"{_q(n)} {_hhmm(s)}-{_hhmm(e)}" for n, s, e in shifts) or "none"
    example = shifts[0][0] if shifts else "DAY"
    out["text"] = f"""
DATA FACTS (read from the loaded data; use these exact IDs, they are text):
Station: {out['name']}. The data covers {out['from']} to {out['to']} only.
A date without a year means {year}, e.g. {date_eg}.
Tanks: {tank_txt}.
Pumps: {pump_txt}.
Shifts each day (shift_name, usual times): {shift_txt}.
Bank reference for a shift's cash deposit: 'SF-' + MMdd of the shift date + '-' + shift_name, e.g. 'SF-{d0:%m%d}-{example}'.
Money: every price and amount in the data is in US dollars. Always write money as US$ (e.g. US$630.00), never any other currency.
"""
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(facts()["text"])
