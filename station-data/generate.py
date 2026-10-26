"""Generate fictional fuel-station data across three separate databases.

Station: Sunrise Fuels, Harare (fictional). Period: 1-14 October 2026.
Databases (deliberately separate, to mimic fragmented systems):
  forecourt  - pumps, tanks, shifts, pump meter readings, POS sales, tank dips, calibration log
  supplier   - fuel delivery notes / invoices
  bank       - bank statement lines

Planted problems (the answer key is kept out of this repository):
  A  Short delivery: DN-1043 diesel invoiced 10,000 L, tank only rose 9,620 L (8 Oct).
  B  Unrecorded sales: pump P3 meter > POS on evening shifts worked by Kuda N.
  C  Cash short: 11 Oct day-shift cash deposit $120 below POS cash.
  E  Red herring: 6 Oct petrol pump P2 calibration test, 40 L dispensed and returned to tank.
"""
import os
import random
import sys
from datetime import date, datetime, timedelta

random.seed(2026)
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

START = date(2026, 10, 1)
DAYS = 14
PRICE = {"diesel": 1.55, "petrol": 1.60}       # illustrative USD per litre
COST = {"diesel": 1.38, "petrol": 1.42}
TANKS = {"T1": ("diesel", 20000), "T2": ("petrol", 20000)}
PUMPS = {"P1": "T1", "P3": "T1", "P2": "T2", "P4": "T2"}
SHIFTS = [("DAY", 6, 14), ("EVE", 14, 22)]
# attendant rota: (day_shift_pair, evening_shift_pair) alternates by day
ROTA = {
    0: {"DAY": {"P1": "Tendai M", "P3": "Tendai M", "P2": "Rudo K", "P4": "Rudo K"},
        "EVE": {"P1": "Kuda N", "P3": "Kuda N", "P2": "Blessing T", "P4": "Blessing T"}},
    1: {"DAY": {"P1": "Blessing T", "P3": "Blessing T", "P2": "Rudo K", "P4": "Rudo K"},
        "EVE": {"P1": "Tendai M", "P3": "Tendai M", "P2": "Kuda N", "P4": "Kuda N"}},
}
# deliveries at 05:30 before opening: (day_index, tank, invoiced, actual)
DELIVERIES = [
    (2, "T1", 10000, 10000), (3, "T2", 10000, 10000),
    (5, "T1", 10000, 10000), (6, "T2", 10000, 10000),
    (7, "T1", 10000, 9620),                              # A: DN-1043 on 8 Oct
    (10, "T2", 10000, 10000), (11, "T1", 10000, 10000),
]
# B: unrecorded litres on P3 for evening shifts where Kuda N works P3
UNRECORDED = {}            # (day_index, 'EVE', 'P3') -> litres
CALIBRATION = {(5, "DAY", "P2"): 40.0}   # E: 6 Oct, returned to tank
CASH_SHORT = {(10, "DAY"): 120.00}       # C: 11 Oct day shift

def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.isoformat() + "'"
    return repr(round(v, 2)) if isinstance(v, float) else str(v)

def inserts(table, cols, rows):
    out = []
    for i in range(0, len(rows), 200):
        chunk = rows[i:i + 200]
        vals = ",\n".join("(" + ", ".join(q(v) for v in r) + ")" for r in chunk)
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{vals};")
    return "\n".join(out)

level = {"T1": 12500.0, "T2": 11000.0}
meter = {"P1": 1834210.0, "P3": 2011876.0, "P2": 1520044.0, "P4": 1498720.0}
dips, readings, sales, assigns, shifts, calib, notes, bank = [], [], [], [], [], [], [], []
sale_id, dip_id, shift_id, txn_id = 1, 1, 1, 1
checks = []  # for self-verification

for d in range(DAYS):
    day = START + timedelta(days=d)
    rota = ROTA[d % 2]
    # Kuda N works P3 on even-index-day evenings; plant B on three of them
    if d in (2, 6, 10):
        UNRECORDED[(d, "EVE", "P3")] = {2: 60.0, 6: 85.0, 10: 70.0}[d]
    # deliveries before opening
    for (di, tank, inv, act) in DELIVERIES:
        if di == d:
            pre = level[tank]
            if act == inv:   # normal deliveries: small temperature/measurement variation
                act = inv + round(random.uniform(-25, 10), 1)
            t_pre = datetime(day.year, day.month, day.day, 5, 20)
            dips.append((dip_id, tank, t_pre, round(pre, 1), "pre-delivery")); dip_id += 1
            level[tank] += act
            assert level[tank] <= TANKS[tank][1], (day, tank, level[tank])
            t_post = datetime(day.year, day.month, day.day, 5, 50)
            dips.append((dip_id, tank, t_post, round(level[tank], 1), "post-delivery")); dip_id += 1
            fuel = TANKS[tank][0]
            dn = f"DN-{1039 + len(notes)}"
            notes.append((dn, "Zuva Petroleum Supply (fictional)", tank, fuel,
                          datetime(day.year, day.month, day.day, 5, 30), float(inv),
                          COST[fuel], round(inv * COST[fuel], 2),
                          random.choice(["T. Moyo", "S. Banda", "P. Chari"]),
                          random.choice(["AFG 4410", "AEZ 2297", "AGB 8816"])))
    open_level = dict(level)
    for tank in TANKS:
        dips.append((dip_id, tank, datetime(day.year, day.month, day.day, 6, 0),
                     round(level[tank], 1), "opening")); dip_id += 1
    day_dispensed = {"T1": 0.0, "T2": 0.0}
    day_returned = {"T1": 0.0, "T2": 0.0}
    for (sname, h0, h1) in SHIFTS:
        sid = shift_id; shift_id += 1
        shifts.append((sid, day, sname, datetime(day.year, day.month, day.day, h0),
                       datetime(day.year, day.month, day.day, h1)))
        cash_total = 0.0
        for pump, tank in PUMPS.items():
            fuel = TANKS[tank][0]
            att = rota[sname][pump]
            assigns.append((sid, pump, att))
            target = random.uniform(700, 900) if fuel == "diesel" else random.uniform(560, 740)
            pos_l = 0.0
            while pos_l < target:
                l = round(random.choice([random.uniform(10, 40), random.uniform(40, 80),
                                         random.uniform(80, 160)]), 2)
                t = datetime(day.year, day.month, day.day, h0) + timedelta(
                    minutes=random.randint(0, (h1 - h0) * 60 - 1))
                pay = random.choices(["cash", "card", "mobile"], [0.55, 0.30, 0.15])[0]
                amt = round(l * PRICE[fuel], 2)
                sales.append((sale_id, sid, pump, t, l, PRICE[fuel], amt, pay)); sale_id += 1
                pos_l += l
                if pay == "cash":
                    cash_total += amt
            extra = UNRECORDED.get((d, sname, pump), 0.0)
            cal = CALIBRATION.get((d, sname, pump), 0.0)
            if cal:
                calib.append((pump, datetime(day.year, day.month, day.day, h0 + 2, 15), cal,
                              "Weights & measures 20 L can test x2, fuel returned to tank", "Rudo K"))
            dispensed = pos_l + extra + cal
            o = meter[pump]; meter[pump] += dispensed
            readings.append((sid, pump, round(o, 1), round(meter[pump], 1)))
            day_dispensed[tank] += dispensed
            day_returned[tank] += cal
        # cash deposit next morning
        dep = round(cash_total - CASH_SHORT.get((d, sname), 0.0), 2)
        bank.append((txn_id, day + timedelta(days=1), f"CASH DEPOSIT {day.strftime('%d%b').upper()} {sname}",
                     f"SF-{day.strftime('%m%d')}-{sname}", dep)); txn_id += 1
    # daily card + mobile settlements
    day_sales = [s for s in sales if s[3].date() == day]
    for meth, label in (("card", "CARD SETTLEMENT"), ("mobile", "MOBILE MONEY SETTLEMENT")):
        tot = round(sum(s[6] for s in day_sales if s[7] == meth), 2)
        fee = round(tot * (0.015 if meth == "card" else 0.01), 2)
        bank.append((txn_id, day + timedelta(days=1), f"{label} {day.strftime('%d%b').upper()}",
                     f"STL-{meth[:2].upper()}-{day.strftime('%m%d')}", round(tot - fee, 2))); txn_id += 1
    # closing level with normal evaporation / temperature noise
    for tank in TANKS:
        noise = -day_dispensed[tank] * random.uniform(0.0005, 0.0025)
        level[tank] = level[tank] - day_dispensed[tank] + day_returned[tank] + noise
        assert level[tank] > 1500, (day, tank, level[tank])
        dips.append((dip_id, tank, datetime(day.year, day.month, day.day, 22, 0),
                     round(level[tank], 1), "closing")); dip_id += 1
        checks.append((day, tank, open_level[tank], day_dispensed[tank], level[tank]))
    # bank noise: one supplier payment per delivery day, rent etc.
    if d in (4, 11):
        bank.append((txn_id, day, "EFT ZUVA PETROLEUM SUPPLY", "SUPPLIER-PMT", -27600.00)); txn_id += 1
    if d == 0:
        bank.append((txn_id, day, "RENT OCT 2026", "RENT-1026", -1800.00)); txn_id += 1

# ---------- write SQL ----------
H = "-- Generated by generate.py. Fictional data for Open Agent Hackathon 2026.\n"
with open(os.path.join(OUT, "00_databases.sql"), "w") as f:
    f.write(H + "CREATE DATABASE forecourt;\nCREATE DATABASE supplier;\nCREATE DATABASE bank;\n")

with open(os.path.join(OUT, "01_forecourt.sql"), "w") as f:
    f.write(H + "\\connect forecourt\n")
    f.write("""
CREATE TABLE tanks (tank_id TEXT PRIMARY KEY, fuel_type TEXT, capacity_l NUMERIC);
CREATE TABLE pumps (pump_id TEXT PRIMARY KEY, tank_id TEXT REFERENCES tanks, fuel_type TEXT);
CREATE TABLE shifts (shift_id INT PRIMARY KEY, shift_date DATE, shift_name TEXT, starts_at TIMESTAMP, ends_at TIMESTAMP);
CREATE TABLE shift_assignments (shift_id INT REFERENCES shifts, pump_id TEXT REFERENCES pumps, attendant TEXT, PRIMARY KEY (shift_id, pump_id));
CREATE TABLE pump_meter_readings (shift_id INT REFERENCES shifts, pump_id TEXT REFERENCES pumps, opening_meter_l NUMERIC, closing_meter_l NUMERIC, PRIMARY KEY (shift_id, pump_id));
CREATE TABLE pos_sales (sale_id INT PRIMARY KEY, shift_id INT REFERENCES shifts, pump_id TEXT REFERENCES pumps, sold_at TIMESTAMP, litres NUMERIC, unit_price NUMERIC, amount NUMERIC, payment_method TEXT);
CREATE TABLE tank_dips (dip_id INT PRIMARY KEY, tank_id TEXT REFERENCES tanks, dipped_at TIMESTAMP, volume_l NUMERIC, dip_type TEXT);
CREATE TABLE calibration_log (pump_id TEXT REFERENCES pumps, tested_at TIMESTAMP, litres_dispensed NUMERIC, notes TEXT, witnessed_by TEXT);
""")
    f.write(inserts("tanks", ["tank_id", "fuel_type", "capacity_l"],
                    [(k, v[0], v[1]) for k, v in TANKS.items()]) + "\n")
    f.write(inserts("pumps", ["pump_id", "tank_id", "fuel_type"],
                    [(p, t, TANKS[t][0]) for p, t in sorted(PUMPS.items())]) + "\n")
    f.write(inserts("shifts", ["shift_id", "shift_date", "shift_name", "starts_at", "ends_at"], shifts) + "\n")
    f.write(inserts("shift_assignments", ["shift_id", "pump_id", "attendant"], assigns) + "\n")
    f.write(inserts("pump_meter_readings", ["shift_id", "pump_id", "opening_meter_l", "closing_meter_l"], readings) + "\n")
    f.write(inserts("pos_sales", ["sale_id", "shift_id", "pump_id", "sold_at", "litres", "unit_price", "amount", "payment_method"], sales) + "\n")
    f.write(inserts("tank_dips", ["dip_id", "tank_id", "dipped_at", "volume_l", "dip_type"], dips) + "\n")
    f.write(inserts("calibration_log", ["pump_id", "tested_at", "litres_dispensed", "notes", "witnessed_by"], calib) + "\n")

with open(os.path.join(OUT, "02_supplier.sql"), "w") as f:
    f.write(H + "\\connect supplier\n")
    f.write("CREATE TABLE delivery_notes (delivery_note TEXT PRIMARY KEY, supplier TEXT, tank_id TEXT, fuel_type TEXT, delivered_at TIMESTAMP, invoiced_litres NUMERIC, unit_cost NUMERIC, invoice_amount NUMERIC, driver TEXT, truck_reg TEXT);\n")
    f.write(inserts("delivery_notes", ["delivery_note", "supplier", "tank_id", "fuel_type", "delivered_at", "invoiced_litres", "unit_cost", "invoice_amount", "driver", "truck_reg"], notes) + "\n")

with open(os.path.join(OUT, "03_bank.sql"), "w") as f:
    f.write(H + "\\connect bank\n")
    f.write("CREATE TABLE bank_statement (txn_id INT PRIMARY KEY, value_date DATE, description TEXT, reference TEXT, amount NUMERIC);\n")
    f.write(inserts("bank_statement", ["txn_id", "value_date", "description", "reference", "amount"], bank) + "\n")

print(f"sales={len(sales)} dips={len(dips)} shifts={len(shifts)} deliveries={len(notes)} bank={len(bank)}")
print("delivery notes:", [(n[0], n[4].date().isoformat(), n[2], n[5]) for n in notes])
print("planted B:", {(START + timedelta(days=k[0])).isoformat(): v for k, v in UNRECORDED.items()})
