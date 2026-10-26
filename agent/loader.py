"""Load a station's own records (CSV files) into the station database that Zetaris reads.

    python -m agent.loader <folder-with-csvs> ["Station name"]
    python -m agent.loader --sample          (restore the Sunrise Fuels sample data)

Every file is checked first (columns, dates, numbers, links between files). Nothing is
written unless all files pass, so a bad upload never leaves half-loaded data.
"""
import csv
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
STATION_FILE = os.path.join(ROOT, "station.json")

# file key -> (required columns, optional columns, description for the manager)
FILES = {
    "station_setup": (["pump_id", "tank_id", "fuel_type", "tank_capacity_l"], [],
                      "One row per pump: which tank it draws from, the fuel, and the tank size"),
    "shift_sheet": (["shift_date", "shift_name", "starts_at", "ends_at", "pump_id", "attendant",
                     "opening_meter_l", "closing_meter_l"], [],
                    "One row per pump per shift: attendant and the pump meter at start and end"),
    "pos_sales": (["sold_at", "pump_id", "litres", "unit_price", "amount", "payment_method"], [],
                  "Till export: one row per sale (payment_method: cash, card or mobile)"),
    "tank_dips": (["tank_id", "dipped_at", "volume_l", "dip_type"], [],
                  "Dip sheet (dip_type: opening, closing, pre-delivery, post-delivery)"),
    "delivery_notes": (["delivery_note", "tank_id", "delivered_at", "invoiced_litres", "unit_cost"],
                       ["supplier", "fuel_type", "invoice_amount", "driver", "truck_reg"],
                       "Supplier delivery notes / invoices"),
    "bank_statement": (["value_date", "description", "amount"],
                       ["cash_for_shift_date", "cash_for_shift_name", "reference"],
                       "Bank statement; for cash deposits fill in which shift the cash came from"),
    "calibration_log": (["pump_id", "tested_at", "litres_dispensed"], ["notes", "witnessed_by"],
                        "Pump tests where fuel was returned to the tank"),
}
OPTIONAL_FILES = {"calibration_log"}
DIP_TYPES = {"opening", "closing", "pre-delivery", "post-delivery"}
PAYMENTS = {"cash", "card", "mobile"}
# Words stations use for the same thing (compared lower-case, spaces/underscores as hyphens).
PAY_WORDS = {"cash": ["cash", "notes", "usd-cash"],
             "card": ["card", "swipe", "visa", "mastercard", "zimswitch", "debit", "credit-card", "debit-card", "pos", "eft"],
             "mobile": ["mobile", "ecocash", "onemoney", "one-money", "innbucks", "telecash", "mobile-money", "momo", "wallet"]}
DIP_WORDS = {"opening": ["opening", "open", "start", "morning", "opening-dip"],
             "closing": ["closing", "close", "end", "evening", "closing-dip"],
             "pre-delivery": ["pre-delivery", "before-delivery", "pre", "before"],
             "post-delivery": ["post-delivery", "after-delivery", "post", "after"]}


def _word(v, table):
    w = re.sub(r"[\s_]+", "-", str(v).strip().lower())
    for canon, words in table.items():
        if w in words:
            return canon
    return w
MAX_ERRORS = 25
SAMPLE_NAME = "Sunrise Fuels, Harare (sample data)"


class LoadError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors[:5]))
        self.errors = errors


# ---------- parsing helpers ----------

def _num(v, errs, where, col):
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v).replace(",", "")) or "x")
    except ValueError:
        errs.append(f"{where}: {col} '{v}' is not a number")
        return None


def _dt(v, errs, where, col):
    s = str(v).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M",
                "%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M", "%d/%m/%Y %I:%M %p", "%Y-%m-%d %I:%M %p", "%d %b %Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    errs.append(f"{where}: {col} '{v}' should look like 2026-10-08 14:30")
    return None


def _date(v, errs, where, col):
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    errs.append(f"{where}: {col} '{v}' should look like 2026-10-08")
    return None


def _time(v, errs, where, col):
    s = str(v).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%H.%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    errs.append(f"{where}: {col} '{v}' should look like 06:00")
    return None


def _clean_id(v):
    return str(v).strip().upper()


# Other names managers' own exports commonly use for each column (compared after _norm()).
ALIASES = {
    "station_setup": {
        "pump_id": ["pump", "pump_no", "pump_number", "pump_name", "dispenser", "nozzle"],
        "tank_id": ["tank", "tank_no", "tank_number", "tank_name"],
        "fuel_type": ["fuel", "product", "grade", "fuel_grade", "product_name"],
        "tank_capacity_l": ["capacity", "tank_capacity", "capacity_l", "capacity_litres", "tank_size", "size"],
    },
    "shift_sheet": {
        "shift_date": ["date", "business_date", "day", "shift_day"],
        "shift_name": ["shift", "shift_type", "shift_no"],
        "starts_at": ["start", "start_time", "shift_start", "time_in", "from"],
        "ends_at": ["end", "end_time", "shift_end", "time_out", "to"],
        "pump_id": ["pump", "pump_no", "pump_number", "pump_name", "dispenser", "nozzle"],
        "attendant": ["cashier", "employee", "staff", "staff_name", "operator", "pump_attendant", "attendant_name", "name"],
        "opening_meter_l": ["opening_meter", "open_meter", "opening_reading", "meter_open", "opening", "start_meter",
                            "opening_totaliser", "opening_totalizer", "opening_litres"],
        "closing_meter_l": ["closing_meter", "close_meter", "closing_reading", "meter_close", "closing", "end_meter",
                            "closing_totaliser", "closing_totalizer", "closing_litres"],
    },
    "pos_sales": {
        "sold_at": ["date_time", "datetime", "timestamp", "transaction_time", "sale_time", "sale_date_time", "date"],
        "pump_id": ["pump", "pump_no", "pump_number", "pump_name", "dispenser", "nozzle"],
        "litres": ["liters", "volume", "qty", "quantity", "quantity_l", "volume_l", "litres_sold", "liters_sold"],
        "unit_price": ["price", "price_per_litre", "price_per_liter", "rate", "unit_cost"],
        "amount": ["total", "value", "sale_amount", "total_amount", "amount_usd"],
        "payment_method": ["payment", "payment_type", "tender", "tender_type", "method", "mop", "pay_method"],
    },
    "tank_dips": {
        "tank_id": ["tank", "tank_no", "tank_number", "tank_name"],
        "dipped_at": ["date_time", "datetime", "dip_time", "timestamp", "date"],
        "volume_l": ["volume", "dip_volume", "litres", "liters", "stock", "volume_litres", "reading"],
        "dip_type": ["type", "reading_type", "dip"],
    },
    "delivery_notes": {
        "delivery_note": ["dn", "dn_no", "delivery_note_no", "note_no", "delivery_no", "invoice", "invoice_no",
                          "invoice_number", "document_no"],
        "tank_id": ["tank", "tank_no", "tank_number", "tank_name"],
        "delivered_at": ["delivery_date", "date_time", "delivery_time", "datetime", "date"],
        "invoiced_litres": ["litres", "liters", "quantity", "qty", "volume", "invoiced_qty", "invoice_litres", "litres_invoiced"],
        "unit_cost": ["cost", "price", "cost_per_litre", "cost_per_liter", "rate", "unit_price"],
        "supplier": ["vendor", "supplier_name", "company"],
        "fuel_type": ["fuel", "product", "grade"],
        "invoice_amount": ["amount", "total", "invoice_total", "value"],
        "driver": ["driver_name"],
        "truck_reg": ["truck", "vehicle", "vehicle_reg", "registration", "reg_no"],
    },
    "bank_statement": {
        "value_date": ["date", "transaction_date", "posting_date", "txn_date"],
        "description": ["details", "narration", "narrative", "particulars", "memo", "transaction_details"],
        "amount": ["credit", "deposit", "credit_amount", "value", "amount_usd"],
        "cash_for_shift_date": ["shift_date", "for_shift_date", "cash_shift_date"],
        "cash_for_shift_name": ["shift", "shift_name", "for_shift", "cash_shift"],
        "reference": ["ref", "reference_no", "ref_no"],
    },
    "calibration_log": {
        "pump_id": ["pump", "pump_no", "pump_number", "pump_name", "dispenser", "nozzle"],
        "tested_at": ["date_time", "datetime", "test_date", "test_time", "date"],
        "litres_dispensed": ["litres", "liters", "volume", "test_litres", "quantity"],
        "notes": ["note", "comment", "comments", "remarks"],
        "witnessed_by": ["witness", "inspector"],
    },
}
# Files whose timestamp may come as two columns (a date column and a time column).
DATETIME_COL = {"pos_sales": "sold_at", "tank_dips": "dipped_at", "delivery_notes": "delivered_at", "calibration_log": "tested_at"}
DATE_ONLY = {"date", "sale_date", "transaction_date", "dip_date", "delivery_date", "test_date", "business_date"}
TIME_ONLY = {"time", "sale_time", "transaction_time", "dip_time", "delivery_time", "test_time"}
FILE_HINTS = {"station_setup": ["setup", "station", "pumps", "tanks"], "shift_sheet": ["shift", "meter", "roster"],
              "pos_sales": ["sale", "pos", "till", "transaction"], "tank_dips": ["dip", "stock"],
              "delivery_notes": ["deliver", "supplier", "invoice", "dn"], "bank_statement": ["bank", "statement"],
              "calibration_log": ["calib", "test"]}


def _norm(h):
    h = re.sub(r"\(.*?\)|\[.*?\]", "", (h or "").replace("\ufeff", "").lower())   # drop units like "(L)"
    return re.sub(r"[^a-z0-9]+", "_", h).strip("_")


def _delim(text):
    first = text.lstrip("\ufeff").splitlines()[0] if text.strip() else ""
    return ";" if first.count(";") > first.count(",") else ","


def map_headers(headers, key):
    """Match a file's own column names to ours. Returns (index->column, missing required, (date_i, time_i) or None)."""
    required, optional, _ = FILES[key]
    cols = required + optional
    normed = [_norm(h) for h in headers]
    mapping = {}
    for i, n in enumerate(normed):                     # 1. exact names
        if n in cols and n not in mapping.values():
            mapping[i] = n
    split = None
    dtcol = DATETIME_COL.get(key)
    if dtcol and dtcol not in mapping.values():        # 2. separate Date + Time columns
        d = next((i for i, n in enumerate(normed) if i not in mapping and n in DATE_ONLY), None)
        t = next((i for i, n in enumerate(normed) if i not in mapping and n in TIME_ONLY), None)
        if d is not None and t is not None:
            split = (d, t)
    for col in cols:                                   # 3. common alternative names
        if col in mapping.values() or (split and col == dtcol):
            continue
        for alias in ALIASES.get(key, {}).get(col, []):
            idx = next((i for i, n in enumerate(normed)
                        if n == alias and i not in mapping and not (split and i in split)), None)
            if idx is not None:
                mapping[idx] = col
                break
    missing = [c for c in required if c not in mapping.values() and not (split and c == dtcol)]
    return mapping, missing, split


def detect(filename, header_line):
    """Guess which template a file is, from its columns (and its name as a tie-breaker)."""
    headers = next(csv.reader([header_line.lstrip("\ufeff")], delimiter=_delim(header_line)), [])
    fname = (filename or "").lower()
    result, best, best_score = {}, None, None
    for key, (required, optional, _) in FILES.items():
        mapping, missing, split = map_headers(headers, key)
        found = len(required) - len(missing)
        score = (len(missing) == 0, found, any(h in fname for h in FILE_HINTS[key]), -len(required))
        renamed = {headers[i]: c for i, c in mapping.items() if _norm(headers[i]) != c}
        if split:
            renamed[f"{headers[split[0]]} + {headers[split[1]]}"] = DATETIME_COL[key]
        result[key] = {"missing": missing, "renamed": renamed}
        if best_score is None or score > best_score:
            best, best_score = key, score
    if best_score and best_score[1] == 0:
        best = None
    return {"key": best, "columns": headers, "per_key": result}


def read_csv(text, key):
    """Parse one CSV text into a list of dicts keyed by our column names; check required columns."""
    required, optional, _ = FILES[key]
    text = text.lstrip("\ufeff")                       # Excel adds a byte-order mark
    reader = csv.reader(io.StringIO(text), delimiter=_delim(text))
    headers = next(reader, [])
    mapping, missing, split = map_headers(headers, key)
    if missing:
        raise LoadError([f"{key}: no column found for {', '.join(missing)}. Your columns: "
                         f"{', '.join(h for h in headers if h) or 'none'}. Rename those columns to match the template."])
    rows = []
    for raw in reader:
        row = {col: (raw[i].strip() if i < len(raw) else "") for i, col in mapping.items()}
        if split:
            d, t = (raw[i].strip() if i < len(raw) else "" for i in split)
            row[DATETIME_COL[key]] = f"{d} {t}".strip()
        if key == "bank_statement" and not row.get("amount"):
            continue                                   # debit lines in a Credit-column statement
        if any(row.get(c) for c in required):          # skip completely empty lines
            rows.append(row)
    if not rows and key not in OPTIONAL_FILES:
        raise LoadError([f"{key} has no data rows"])
    return rows


# ---------- build the database rows ----------

def build(files):
    """files: {key: csv_text}. Returns table rows per database, or raises LoadError."""
    errs = []
    missing = [k for k in FILES if k not in OPTIONAL_FILES and not files.get(k)]
    if missing:
        raise LoadError([f"Missing file: {k}.csv" for k in missing])
    data = {}
    for key in FILES:
        if files.get(key):
            try:
                data[key] = read_csv(files[key], key)
            except LoadError as e:
                errs += e.errors
        else:
            data[key] = []
    if errs:
        raise LoadError(errs)

    # station setup
    tanks, pumps = {}, {}
    for i, r in enumerate(data["station_setup"], 2):
        w = f"station_setup.csv line {i}"
        pid, tid, fuel = _clean_id(r["pump_id"]), _clean_id(r["tank_id"]), r["fuel_type"].strip().lower()
        cap = _num(r["tank_capacity_l"], errs, w, "tank_capacity_l")
        if pid in pumps:
            errs.append(f"{w}: pump {pid} listed twice")
        pumps[pid] = (pid, tid, fuel)
        if tid in tanks and tanks[tid][1] != fuel:
            errs.append(f"{w}: tank {tid} has two different fuels")
        tanks[tid] = (tid, fuel, cap)

    # shifts from the shift sheet
    shifts, assigns, readings, shift_key = [], [], [], {}
    for i, r in enumerate(data["shift_sheet"], 2):
        w = f"shift_sheet.csv line {i}"
        d = _date(r["shift_date"], errs, w, "shift_date")
        name = r["shift_name"].strip().upper()
        t0, t1 = _time(r["starts_at"], errs, w, "starts_at"), _time(r["ends_at"], errs, w, "ends_at")
        pid = _clean_id(r["pump_id"])
        o, c = _num(r["opening_meter_l"], errs, w, "opening_meter_l"), _num(r["closing_meter_l"], errs, w, "closing_meter_l")
        if pid not in pumps:
            errs.append(f"{w}: pump {pid} is not in station_setup.csv")
        if None in (d, t0, t1, o, c):
            continue
        if c < o:
            errs.append(f"{w}: closing meter is lower than opening meter")
        k = (d, name)
        if k not in shift_key:
            start = datetime.combine(d, t0)
            end = datetime.combine(d + timedelta(days=1) if t1 <= t0 else d, t1)   # overnight shifts
            shift_key[k] = len(shifts) + 1
            shifts.append((shift_key[k], d, name, start, end))
        sid = shift_key[k]
        if any(a[0] == sid and a[1] == pid for a in assigns):
            errs.append(f"{w}: pump {pid} appears twice for {d} {name}")
        assigns.append((sid, pid, r["attendant"].strip()))
        readings.append((sid, pid, o, c))
        if len(errs) > MAX_ERRORS:
            raise LoadError(errs)

    def shift_for(ts):
        for sid, d, name, start, end in shifts:
            if start <= ts < end:
                return sid
        return None

    sales = []
    for i, r in enumerate(data["pos_sales"], 2):
        w = f"pos_sales.csv line {i}"
        ts = _dt(r["sold_at"], errs, w, "sold_at")
        pid = _clean_id(r["pump_id"])
        litres, price, amount = (_num(r[c], errs, w, c) for c in ("litres", "unit_price", "amount"))
        pay = _word(r["payment_method"], PAY_WORDS)
        if pay not in PAYMENTS:
            errs.append(f"{w}: payment_method '{r['payment_method']}' must be cash, card or mobile")
        if pid not in pumps:
            errs.append(f"{w}: pump {pid} is not in station_setup.csv")
        if ts is not None:
            sid = shift_for(ts)
            if sid is None:
                errs.append(f"{w}: sale at {ts:%Y-%m-%d %H:%M} is not inside any shift in shift_sheet.csv")
            else:
                sales.append((len(sales) + 1, sid, pid, ts, litres, price, amount, pay))
        if len(errs) > MAX_ERRORS:
            raise LoadError(errs)

    dips = []
    for i, r in enumerate(data["tank_dips"], 2):
        w = f"tank_dips.csv line {i}"
        tid, ts = _clean_id(r["tank_id"]), _dt(r["dipped_at"], errs, w, "dipped_at")
        vol, dtype = _num(r["volume_l"], errs, w, "volume_l"), _word(r["dip_type"], DIP_WORDS)
        if tid not in tanks:
            errs.append(f"{w}: tank {tid} is not in station_setup.csv")
        if dtype not in DIP_TYPES:
            errs.append(f"{w}: dip_type '{r['dip_type']}' must be one of {', '.join(sorted(DIP_TYPES))}")
        dips.append((len(dips) + 1, tid, ts, vol, dtype))

    notes = []
    for i, r in enumerate(data["delivery_notes"], 2):
        w = f"delivery_notes.csv line {i}"
        tid = _clean_id(r["tank_id"])
        ts = _dt(r["delivered_at"], errs, w, "delivered_at")
        inv, cost = _num(r["invoiced_litres"], errs, w, "invoiced_litres"), _num(r["unit_cost"], errs, w, "unit_cost")
        if tid not in tanks:
            errs.append(f"{w}: tank {tid} is not in station_setup.csv")
        amount = _num(r["invoice_amount"], errs, w, "invoice_amount") if r.get("invoice_amount") else (
            round(inv * cost, 2) if inv is not None and cost is not None else None)
        fuel = (r.get("fuel_type") or (tanks.get(tid, ("", ""))[1])).strip().lower()
        notes.append((r["delivery_note"].strip(), r.get("supplier", ""), tid, fuel, ts, inv, cost, amount,
                      r.get("driver", ""), r.get("truck_reg", "")))

    bank = []
    for i, r in enumerate(data["bank_statement"], 2):
        w = f"bank_statement.csv line {i}"
        vd, amt = _date(r["value_date"], errs, w, "value_date"), _num(r["amount"], errs, w, "amount")
        ref = r.get("reference", "")
        if r.get("cash_for_shift_date"):
            sd = _date(r["cash_for_shift_date"], errs, w, "cash_for_shift_date")
            sn = (r.get("cash_for_shift_name") or "").strip().upper()
            if sd and (sd, sn) not in shift_key:
                errs.append(f"{w}: cash deposit for shift {sd} {sn} but that shift is not in shift_sheet.csv")
            if sd:
                ref = f"SF-{sd:%m%d}-{sn}"   # the link the agent uses to match cash to its shift
        bank.append((len(bank) + 1, vd, r["description"], ref, amt))

    calib = []
    for i, r in enumerate(data["calibration_log"], 2):
        w = f"calibration_log.csv line {i}"
        pid, ts = _clean_id(r["pump_id"]), _dt(r["tested_at"], errs, w, "tested_at")
        lit = _num(r["litres_dispensed"], errs, w, "litres_dispensed")
        if pid not in pumps:
            errs.append(f"{w}: pump {pid} is not in station_setup.csv")
        calib.append((pid, ts, lit, r.get("notes", ""), r.get("witnessed_by", "")))

    if errs:
        raise LoadError(errs[:MAX_ERRORS] + ([f"... and {len(errs) - MAX_ERRORS} more problems"] if len(errs) > MAX_ERRORS else []))

    return {
        "forecourt": [
            ("tanks", ["tank_id", "fuel_type", "capacity_l"], list(tanks.values())),
            ("pumps", ["pump_id", "tank_id", "fuel_type"], list(pumps.values())),
            ("shifts", ["shift_id", "shift_date", "shift_name", "starts_at", "ends_at"], shifts),
            ("shift_assignments", ["shift_id", "pump_id", "attendant"], assigns),
            ("pump_meter_readings", ["shift_id", "pump_id", "opening_meter_l", "closing_meter_l"], readings),
            ("pos_sales", ["sale_id", "shift_id", "pump_id", "sold_at", "litres", "unit_price", "amount", "payment_method"], sales),
            ("tank_dips", ["dip_id", "tank_id", "dipped_at", "volume_l", "dip_type"], dips),
            ("calibration_log", ["pump_id", "tested_at", "litres_dispensed", "notes", "witnessed_by"], calib),
        ],
        "supplier": [("delivery_notes", ["delivery_note", "supplier", "tank_id", "fuel_type", "delivered_at",
                                         "invoiced_litres", "unit_cost", "invoice_amount", "driver", "truck_reg"], notes)],
        "bank": [("bank_statement", ["txn_id", "value_date", "description", "reference", "amount"], bank)],
        "summary": {"pumps": len(pumps), "tanks": len(tanks), "shifts": len(shifts), "sales": len(sales),
                    "dips": len(dips), "deliveries": len(notes), "bank_lines": len(bank), "calibrations": len(calib),
                    "from": min((s[1] for s in shifts), default=None), "to": max((s[1] for s in shifts), default=None)},
    }


# ---------- write to the station database ----------

def _connect(dbname):
    import psycopg   # pip install "psycopg[binary]"
    return psycopg.connect(host=os.environ.get("STATION_DB_HOST", "127.0.0.1"),
                           port=int(os.environ.get("STATION_DB_PORT", "5433")),
                           user=os.environ.get("STATION_DB_USER", "station"),
                           password=os.environ.get("STATION_DB_PASSWORD", "StationDemo2026"),
                           dbname=dbname, connect_timeout=10)


def write(built):
    # Delete children before parents, insert parents before children; one transaction per database.
    for dbname in ("forecourt", "supplier", "bank"):
        tables = built[dbname]
        with _connect(dbname) as conn, conn.cursor() as cur:
            for table, _, _ in reversed(tables):
                cur.execute(f"DELETE FROM {table}")
            for table, cols, rows in tables:
                if rows:
                    ph = ", ".join(["%s"] * len(cols))
                    cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})", rows)


def station_scope(name, summary):
    """A short id that keeps each station's H-MEM memories separate."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "station"
    return f"{slug}:{summary.get('from')}:{summary.get('to')}"


def load(files, name):
    built = build(files)
    write(built)
    summary = {k: (str(v) if isinstance(v, date) else v) for k, v in built["summary"].items()}
    info = {"name": name.strip() or "My station", "summary": summary,
            "scope": station_scope(name, summary), "loaded_at": datetime.now().isoformat(timespec="seconds")}
    with open(STATION_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    return info


def sample_files():
    return {k: open(os.path.join(TEMPLATES, f"{k}.csv"), encoding="utf-8").read()
            for k in FILES if os.path.exists(os.path.join(TEMPLATES, f"{k}.csv"))}


def current_station():
    try:
        with open(STATION_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        name, summary = SAMPLE_NAME, {"from": "2026-10-01", "to": "2026-10-14"}
        return {"name": name, "scope": station_scope(name, summary), "summary": summary}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    args = sys.argv[1:]
    try:
        if not args or args[0] == "--sample":
            info = load(sample_files(), SAMPLE_NAME)
        else:
            folder = args[0]
            files = {}
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith(".csv"):
                    text = open(os.path.join(folder, fn), encoding="utf-8-sig").read()
                    key = detect(fn, (text.splitlines() or [""])[0])["key"]
                    print(f"  {fn} -> {key or 'not recognised, skipped'}")
                    if key:
                        files[key] = text
            info = load(files, args[1] if len(args) > 1 else os.path.basename(os.path.abspath(folder)))
        print("Loaded:", json.dumps(info, indent=2))
    except LoadError as e:
        print("Not loaded. Please fix:")
        for m in e.errors:
            print("  -", m)
        sys.exit(1)
