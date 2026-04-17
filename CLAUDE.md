# Claude context — trading-bot

This file gives Claude complete working context for this project. Read it at the start of every session before touching any code.

---

## What this project is

BTCUSDT market-making bot on Binance testnet. Python, micro-spread strategy, single continuous run stored in SQLite. The user is Jonatan. The project is in a **development/testing pipeline** — currently in Phase 1 (DB migration), not yet profitable.

**Development pipeline order:**
1. DB migration (done — current state)
2. Multi-symbol support
3. Automated testing
4. Profitability analysis

---

## Phase 1 migration: what changed

The project was migrated from CSV-based session storage (`data/runs/paper_NNN/`) to a single SQLite database (`data/trading.db`). Key decisions:

- **No CSV migration** — started fresh, old CSV data is irrelevant
- **Single continuous run** instead of artificial 6-hour sessions
- **Section markers** written every hour (`period_1`, `period_2`, ...) for time-period analysis
- **DB read methods return `list[dict]` with all values as strings** — this preserves compatibility with analytics code that does `Decimal(row["price"])`, `int(row["order_id"])`, etc.
- **Boolean DB fields (0/1) converted to "True"/"False" strings** for analyzer compatibility
- `INSERT OR IGNORE` in `insert_execution` for idempotent deduplication

---

## Key source files

### Database layer (`src/db/`)
- `schema.py` — DDL for 8 tables: `sessions`, `section_markers`, `cycles`, `orders`, `executions`, `equity_snapshots`, `reconciled_orders`, `analysis_results`
- `database.py` — `Database` class with all read/write methods; `_row_to_csv()` helper converts DB rows to CSV-compatible string dicts
- `trade_journal.py` — `DbTradeJournal(db, session_id)` — duck-typed drop-in for old CSV journal; methods: `record_cycle`, `record_order`, `record_equity`
- `execution_journal.py` — `DbExecutionJournal(db, session_id)` — `record_execution`
- `section_marker_service.py` — daemon thread; opens `period_1` on `start()`, closes+reopens every `interval_seconds`, closes cleanly on `stop()`

### Engine (`src/engine/`)
- `market_making_engine.py` — accepts optional `journal=` param; defaults to `TradeJournal()` if not provided
- `cycle_recorder.py` — calls `journal.record_cycle(snapshot)` each cycle

### Entry points (`src/scripts/`)
- `run_market_maker.py` — wires DB + session + journals + section marker service; session ID from `RUN_SESSION_ID` env var or auto-generated
- `reconcile_orders.py` — reads orders from DB, calls `OrderReconciler`, writes results back to DB
- `reconcile_executions.py` — gets session start from DB, uses `DbExecutionJournal`, calls `TradeReconciler`
- `analyze_journal.py` — reads all 6 data dicts from DB, runs all analyzers with `data=` injection, stores JSON in `analysis_results`
- `compare_papers.py` — queries all sessions + analysis results, prints table, exports `paper_metrics_summary.csv`

### Analytics (`src/analytics/`)
All modules accept `data: dict | None = None` param injected by `analyze_journal.py`. When provided, skip CSV reads and use the passed dicts. Key modules: `execution_metrics`, `fill_quality`, `lifecycle_analytics`, `pnl_decomposition`, `execution_pnl_analysis`, `execution_ledger`.

### Reconciliation (`src/reconciliation/`)
- `order_reconciler.py` — `reconcile(symbol, orders_data)` returns `(ReconciliationSummary, list[dict])`, no CSV I/O
- `trade_reconciler.py` — uses `DbExecutionJournal` directly

---

## Known bugs fixed during Phase 1

1. **`InventoryBias` enum not serializable to SQLite** — `CycleSnapshot.inventory_bias` is typed as `str` but `risk_manager.inventory_bias()` returns an `InventoryBias` enum. CSV silently coerced it; SQLite binding rejected it. Fixed in `database.py:insert_cycle()`:
   ```python
   s.inventory_bias.value if hasattr(s.inventory_bias, 'value') else s.inventory_bias,
   ```

2. **`ExecutionLedger` BUY realized_delta discarded** — BUY side was `_, new_pos, new_avg = self._apply_buy(...)`, discarding realized delta when covering a short. Fixed to capture and add it to `realized_gross_pnl`.

3. **`_empty_summary` in `ExecutionPnlAnalyzer`** — missing `source_filename` first positional arg. Fixed to `ExecutionPnlSummary("", 0, 0, z, z, z, z, 0, 0, 0)`.

4. **`ImportError: get_journal_base_path`** — after gutting `run_paths.py`, old journal files still imported it. Fixed by hardcoding `"data/journals"` as default.

---

## Workflow

```
# Run bot
python3 -m src.scripts.run_market_maker
# (Ctrl+C to stop)

# Post-process
./run_papers.sh <session_id>
# Steps: reconcile_orders → reconcile_executions → analyze_journal → compare_papers
```

`run_papers.sh` usage: `./run_papers.sh <session_id>` — session ID is printed at MM startup.

---

## Shell scripts

- `run_market_maker.sh` — sets env vars, uses `exec` so SIGTERM reaches Python directly (important for systemd)
- `run_papers.sh` — takes `session_id` as required arg, runs all 4 post-processing steps

---

## What's NOT done yet (next phases)

- Multi-symbol support
- Automated test suite
- Profitability analysis improvements
- The bot runs on Binance **testnet** — not real money

---

## Python binary

Use `python3` (not `python`). Virtualenv at `venv/`. Activate with `source venv/bin/activate`.
