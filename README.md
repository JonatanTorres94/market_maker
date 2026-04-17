# Crypto Market Maker Bot

BTCUSDT market-making bot for Binance (testnet), written in Python. Micro-spread strategy with inventory management, volatility gating (Drift Gate), and full execution tracking.

---

## Architecture

- **Engine** — main loop orchestrator; builds `CycleState` and executes `ExecutionPlan`
- **Coordinator** — atomic placement/cancel against exchange, REST fallback for state validation
- **StateStore** — short-term tracking of active BUY/SELL orders
- **Maintenance** — background service for order reconciliation, fill reconciliation, REST state cleanup
- **Database** — single SQLite file (`data/trading.db`), WAL mode, stores all session data permanently

---

## Running the bot

```bash
# Activate venv
source venv/bin/activate

# Start market maker (runs until Ctrl+C or SIGTERM)
python3 -m src.scripts.run_market_maker

# Or via shell wrapper (sets env vars, logs to file)
./run_market_maker.sh
```

The session ID is auto-generated (`paper_YYYYMMDDTHHMMSSZ`) or set via:
```bash
RUN_SESSION_ID=my_session python3 -m src.scripts.run_market_maker
```

### systemd service
```bash
systemctl --user start market-maker-loop.service
systemctl --user stop market-maker-loop.service
journalctl --user -u market-maker-loop.service -f
```

---

## Post-processing a session

Run after stopping the bot. Replace `<session_id>` with the ID printed at startup.

```bash
./run_papers.sh <session_id>
```

This runs four steps in sequence:
1. **reconcile_orders** — fetches open order statuses from Binance, writes to `reconciled_orders` table
2. **reconcile_executions** — fetches all fills since session start, writes to `executions` table
3. **analyze_journal** — runs all analytics, stores JSON result in `analysis_results` table
4. **compare_papers** — prints summary table across all sessions, exports `paper_metrics_summary.csv`

---

## Inspecting the database

```bash
# List sessions
python3 -c "
import sqlite3
conn = sqlite3.connect('data/trading.db')
rows = conn.execute('SELECT session_id, started_at, ended_at FROM sessions ORDER BY started_at DESC LIMIT 10').fetchall()
for r in rows: print(r)
"

# Row counts per table
python3 -c "
import sqlite3
conn = sqlite3.connect('data/trading.db')
for t in ['sessions','section_markers','cycles','orders','equity_snapshots','executions','reconciled_orders','analysis_results']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n}')
"
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `RUN_SESSION_ID` | auto-generated | Session identifier |
| `DRIFT_GATE_LOOKBACK_SECONDS` | — | Lookback window for drift gate |
| `DRIFT_GATE_THRESHOLD_BPS` | — | Drift threshold in basis points |

---

## Key paths

| Path | Purpose |
|---|---|
| `data/trading.db` | All session data (single SQLite file) |
| `data/journals/` | Legacy CSV fallback (not used in normal operation) |
| `logs/` | Log files when running via shell wrapper |
| `src/db/` | Database layer: schema, Database class, DB-backed journals, section marker service |
| `src/engine/` | Market making engine, order coordinator, cycle recorder |
| `src/analytics/` | Post-run analytics modules |
| `src/scripts/` | Entry points: run_market_maker, reconcile_*, analyze_journal, compare_papers |
| `src/reconciliation/` | Order and execution reconcilers |
