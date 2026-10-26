# Station database (Sunrise Fuels sample, fictional)

Three separate databases that mimic the fragmented systems a fuel station really has:

| Database | Tables | Real-world equivalent |
|---|---|---|
| forecourt | tanks, pumps, shifts, shift_assignments, pump_meter_readings, pos_sales, tank_dips, calibration_log | Forecourt controller + POS + dip sheets |
| supplier | delivery_notes | Supplier invoices / delivery notes |
| bank | bank_statement | Bank statement export |

Period: 1-14 October 2026. Names, prices and companies are invented.

## Setup (Linux / WSL terminal, with Docker and Zetaris running)

    cd station-data
    docker compose up -d
    docker logs station-db --tail 20      # wait for "database system is ready to accept connections"

The compose file joins the Zetaris Docker network (`zetaris_default`) so Zetaris reaches it at host
`station-db`. Then open the Zetaris SQL Editor and run `zetaris_register.sql` one statement at a time.

Stop: `docker compose stop`. Reset completely: `docker compose down -v` then `docker compose up -d`.
`generate.py` regenerates the SQL in `init/` (`python3 generate.py init`).
