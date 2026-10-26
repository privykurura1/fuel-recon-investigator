"""Second, fictional test station with different IDs, shift names (incl. overnight) and planted problems."""
import csv, os, random, sys
from datetime import date, datetime, timedelta
out = sys.argv[1]; random.seed(7)
PUMPS = {"PUMP-01": ("D1", "diesel"), "PUMP-02": ("U1", "petrol"), "PUMP-03": ("U1", "petrol")}
PRICE = {"diesel": 1.58, "petrol": 1.62}; COST = {"diesel": 1.40, "petrol": 1.45}
SHIFTS = [("MORNING", "05:00", "13:00"), ("AFTERNOON", "13:00", "21:00"), ("NIGHT", "21:00", "05:00")]
STAFF = ["Farai N", "Chipo M", "Kuda T", "Nyasha P", "Tatenda R", "Blessing S"]
days = [date(2026, 3, 2) + timedelta(d) for d in range(7)]
W = lambda n, h, rows: (lambda f: (csv.writer(f).writerow(h), csv.writer(f).writerows(rows)))(open(os.path.join(out, n + ".csv"), "w", newline=""))
W("station_setup", ["pump_id", "tank_id", "fuel_type", "tank_capacity_l"], [[p, t, f, 30000] for p, (t, f) in PUMPS.items()])
meter = {"PUMP-01": 500000.0, "PUMP-02": 720000.0, "PUMP-03": 610000.0}
tank = {"D1": 18000.0, "U1": 21000.0}
shift_rows, sales, dips, cash = [], [], [], {}
LEAK = (date(2026, 3, 5), "AFTERNOON", "PUMP-02", 85.0)
DELIV = {date(2026, 3, 4): ("DN-7701", "U1", "petrol", 15000, 15000), date(2026, 3, 5): ("DN-7702", "D1", "diesel", 15000, 14550)}
deliveries = []
for d in days:
    for t in tank: dips.append([t, f"{d} 05:00", round(tank[t], 1), "opening"])
    for si, (name, a, b) in enumerate(SHIFTS):
        start = datetime.combine(d, datetime.strptime(a, "%H:%M").time())
        end = datetime.combine(d + timedelta(1) if b <= a else d, datetime.strptime(b, "%H:%M").time())
        if d in DELIV and name == "MORNING":   # delivery at 05:30 within morning shift, dips around it
            dn, t, fuel, inv, rise = DELIV[d]
            dips.append([t, f"{d} 05:30", round(tank[t], 1), "pre-delivery"])
            tank[t] += rise
            dips.append([t, f"{d} 06:10", round(tank[t], 1), "post-delivery"])
            deliveries.append([dn, "Kopje Fuel Distributors (fictional)", t, fuel, f"{d} 05:30", inv, COST[fuel], round(inv * COST[fuel], 2), "L. Banda", "AEZ 4410"])
        for p, (t, fuel) in PUMPS.items():
            n = random.randint(18, 28) if name != "NIGHT" else random.randint(4, 8)
            total = 0.0
            for _ in range(n):
                ts = start + timedelta(minutes=random.randint(0, int((end - start).total_seconds() // 60) - 1))
                lit = round(random.uniform(10, 60), 2); total += lit
                pay = random.choice(["cash", "cash", "card", "mobile"])
                sales.append([ts.strftime("%Y-%m-%d %H:%M"), p, lit, PRICE[fuel], round(lit * PRICE[fuel], 2), pay])
                if pay == "cash": cash[(d, name)] = cash.get((d, name), 0) + round(lit * PRICE[fuel], 2)
            pumped = total + (LEAK[3] if (d, name, p) == LEAK[:3] else 0)
            o = meter[p]; meter[p] += pumped; tank[t] -= pumped
            att = STAFF[(si * 3 + list(PUMPS).index(p) + d.day) % len(STAFF)]
            if (d, name, p) == LEAK[:3]: att = "Farai N"
            shift_rows.append([d, name, a, b, p, att, round(o, 1), round(meter[p], 1)])
    for t in tank: dips.append([t, f"{d + timedelta(1)} 04:59", round(tank[t], 1), "closing"])
sales.sort()
W("shift_sheet", ["shift_date", "shift_name", "starts_at", "ends_at", "pump_id", "attendant", "opening_meter_l", "closing_meter_l"], shift_rows)
W("pos_sales", ["sold_at", "pump_id", "litres", "unit_price", "amount", "payment_method"], sales)
W("tank_dips", ["tank_id", "dipped_at", "volume_l", "dip_type"], dips)
W("delivery_notes", ["delivery_note", "supplier", "tank_id", "fuel_type", "delivered_at", "invoiced_litres", "unit_cost", "invoice_amount", "driver", "truck_reg"], deliveries)
bank = []
for (d, name), amt in sorted(cash.items()):
    if (d, name) == (date(2026, 3, 6), "NIGHT"): amt -= 200
    bank.append([d + timedelta(1), f"CASH DEPOSIT {d:%d%b}".upper() + f" {name}", round(amt, 2), d, name, f"SF-{d:%m%d}-{name}"])
W("bank_statement", ["value_date", "description", "amount", "cash_for_shift_date", "cash_for_shift_name", "reference"], bank)
print("ok", len(sales), "sales;", "leak pump-02 afternoon 5 Mar 85 L =", round(85 * 1.62, 2), "; DN-7702 short 450 L =", 450 * 1.40, "; SF-0306-NIGHT short 200")
