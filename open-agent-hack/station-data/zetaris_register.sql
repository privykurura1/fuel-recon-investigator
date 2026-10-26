-- Run these in the Zetaris SQL Editor (http://localhost:3000), ONE statement at a time.
-- Zetaris splits on semicolons, so select and run each block separately.

-- 1. Forecourt system (pumps, shifts, POS sales, tank dips, calibration log)
CREATE DATASOURCE forecourt DESCRIBE BY "Sunrise Fuels forecourt system" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://station-db:5432/forecourt",
  username "station",
  password "StationDemo2026"
)

REGISTER DATASOURCE TABLES FROM forecourt

-- 2. Fuel supplier (delivery notes / invoices)
CREATE DATASOURCE supplier DESCRIBE BY "Fuel supplier delivery notes" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://station-db:5432/supplier",
  username "station",
  password "StationDemo2026"
)

REGISTER DATASOURCE TABLES FROM supplier

-- 3. Bank statement
CREATE DATASOURCE bank DESCRIBE BY "Station bank statement" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://station-db:5432/bank",
  username "station",
  password "StationDemo2026"
)

REGISTER DATASOURCE TABLES FROM bank

-- 4. Checks
SHOW DATASOURCES

SELECT * FROM forecourt.tank_dips LIMIT 5

-- Cross-source test: invoiced litres (supplier) vs measured tank rise (forecourt).
-- Expect DN-1043 on 2026-10-08 to show about -380 L.
SELECT d.delivery_note, d.tank_id, d.invoiced_litres,
       MAX(CASE WHEN t.dip_type = 'post-delivery' THEN t.volume_l END)
     - MAX(CASE WHEN t.dip_type = 'pre-delivery'  THEN t.volume_l END) AS measured_rise_l
FROM supplier.delivery_notes d
JOIN forecourt.tank_dips t
  ON t.tank_id = d.tank_id AND to_date(t.dipped_at) = to_date(d.delivered_at)
 AND t.dip_type IN ('pre-delivery', 'post-delivery')
GROUP BY d.delivery_note, d.tank_id, d.invoiced_litres
ORDER BY d.delivery_note
