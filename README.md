# Fuel Reconciliation Investigator

An AI agent that answers a fuel-station manager's question ("Why was diesel short on 8 October?")
by investigating three separate systems (forecourt, supplier, bank) through **Zetaris**, reasoning
with **NVIDIA Nemotron** served by **Meterless Nightshift**, and replying with evidence.

Built for Open Agent Hackathon 2026, Track 02: The Agent That Can Explain Why.

It works on **any station's records**, not just the demo: a manager exports shift sheets, till sales,
dip sheet, delivery notes and bank statement as CSV, uploads them on the web page, and investigates.
A fictional sample station (Sunrise Fuels, Harare, 1-14 October 2026) is loaded by default.

## How it works

```
Manager's question
   -> Nemotron (via Nightshift) decides what to check and writes one SQL query
   -> Zetaris runs it across forecourt / supplier / bank
   -> result goes back to Nemotron, repeat (max 20 steps)
   -> final findings: confirmed losses, explained differences, evidence, US$ value, who was on duty
   -> findings saved to H-MEM: confirmed losses go to long-term memory, revised findings supersede old ones,
      every create/read/update is written to H-MEM's append-only trust ledger
   -> next investigation: H-MEM recalls relevant past findings first, the agent re-checks them with fresh queries
```

| File | Role |
|---|---|
| `agent/llm.py` | Power: Nightshift chat calls, keeps the compute receipt (which model really answered) |
| `agent/zetaris.py` | Data: one read-only SQL statement through the Zetaris REST API |
| `agent/prompts.py` | Data map + a reconciliation clerk's playbook + SQL rules |
| `agent/station.py` | Reads the loaded station's real dates, tank/pump IDs and shift names from Zetaris for the prompt |
| `agent/loader.py`, `agent/templates/` | Checks a station's CSV files and loads them into the station database Zetaris reads |
| `agent/investigator.py` | The agent loop, JSON action parsing, SQL-error retry, trace files |
| `agent/memory.py` | Memory: calls the **Meterless H-MEM** engine through `hmem/bridge.ts` |
| `hmem/` | Official H-MEM reference engine (Apache-2.0) + conformance suite + the JSON bridge |
| `agent/main.py` | Command-line interface |
| `agent/web.py`, `agent/web.html` | Demo web page: live step-by-step investigation, findings, H-MEM panel, Nightshift receipts |
| `check_setup.py` | Checks Zetaris, station data, Nightshift and the upload path before you run the agent |
| `station-data/` | Docker Postgres with the three fictional source systems + Zetaris registration SQL |
| `examples/avondale-test-station/` | A second fictional station to test uploads |

## Run it yourself

You need: Docker, the Zetaris hackathon platform running, Meterless Nightshift with an NVIDIA Nemotron lane,
Python 3.11+ and Node.js 20+.

1. **Station data.** In a Linux/WSL terminal: `cd station-data && docker compose up -d`, then register the
   three sources in the Zetaris SQL Editor with `station-data/zetaris_register.sql` (one statement at a time).
   See `station-data/README.md`.
2. **Config.** Copy `.env.example` to `.env` and fill in your Zetaris API key and Nightshift runtime token.
3. **Install once:** `python -m pip install -r requirements.txt`, then `cd hmem`, `npm install`, `cd ..`
4. **Check:** `python check_setup.py` -> four PASS lines (Zetaris, station data, Nightshift -> Nemotron, upload path).
5. **Web app:** `python -m agent.web`, open http://localhost:5050
   (or the command line: `python -m agent.main "Is any pump losing fuel?"`).

Try it on a station it has never seen: click **Upload your records** and drop in the six CSV files from
`examples/avondale-test-station` (a second fictional station with different pump IDs, shift names, an
overnight shift and three planted problems).

## Use your own station's records

1. Click **Upload your records** on the web page.
2. Export your records as CSV (Excel: *Save As -> CSV*; commas or semicolons both work). Your own file
   names and column names are fine: each file is identified from its columns, and common alternatives
   are recognised ("Pump No", "Qty (L)", "Cashier", "Narration", "Credit", separate Date and Time
   columns, dd/mm/yyyy dates, "$" amounts, EcoCash/Swipe/InnBucks, Open/Close dips...). The window shows
   how each file was read and lets you correct the file type. If a column can't be matched, rename it
   to the name in the templates (download them from the same window). All amounts are in US dollars.
3. Type the station name and click **Check and load records**. Every file is checked first (missing
   columns, bad dates or numbers, a pump that isn't in the station setup, a sale outside every shift...).
   Nothing is replaced unless all files pass.
4. Ask questions. **Restore the sample data** puts the demo station back.

`examples/avondale-messy-export` is the Avondale test station exported with different file names,
column names and formats, to show this working.

Command line alternative (from the project folder): `python -m agent.loader <folder> "Station name"` or `python -m agent.loader --sample`.
For cash checks, fill `cash_for_shift_date` and `cash_for_shift_name` on each cash deposit line of the bank
statement, so the agent can match each deposit to the shift that took the cash. Shifts may run past midnight.
Each station gets its own H-MEM memory store (`memory/stations/...`), so findings never leak between stations.

Memory tools: `python -m agent.memory stats`, `python -m agent.memory ledger`,
`python -m agent.memory feedback <memory-id> helpful|not_helpful|wrong`.
H-MEM conformance: `cd hmem` then `npm run conformance` (13/13 checks).

Each run writes a full trace (every query, result and Nightshift receipt) to `runs/`.

## Meterless Engine: H-MEM

- The engine in `hmem/reference` is Meterless's official reference implementation and passes the
  official conformance suite (13/13, `npm run conformance`).
- Hybrid retrieval ranking and domain-grouped reinjection into the agent's prompt; recall threshold tuned
  to 0.08 for this domain (spec section 13 allows tuning; the reference embedder is a deterministic mock).
- Confirmed losses stored in the long-term tier, others in working; a re-investigated finding supersedes
  the old one (kept, ranked lower, never deleted).
- Trust ledger: every create, read, update and feedback is logged append-only in `memory/hmem/ledger.jsonl`.
- Manager feedback (helpful / not_helpful / wrong) adjusts confidence by exactly +0.05 / -0.03 / -0.20.

## Reliability safeguards

- Standard check queries (pumps, deliveries, cash) return only exceptions, so the model never reasons from a partial list.
- Results larger than the model can see are flagged as INCOMPLETE and must be re-queried.
- Read-only SQL only; Zetaris errors are fed back so the agent repairs its own query.
- Temporary Nightshift/NVIDIA failures are retried; findings from a run where Zetaris was unreachable are never stored.
- Only proven findings (confirmed loss, or a gap the data explains) become H-MEM memories.
