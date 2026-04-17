from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from src.db.schema import SCHEMA_SQL

_BOOL_COLS_CYCLES = {"bid_placeable", "ask_placeable"}
_BOOL_COLS_EXEC = {"is_maker"}


def _row_to_csv(row: dict, bool_cols: set[str] | None = None) -> dict:
    """Convert a DB row dict to CSV-compatible string values."""
    out = {}
    for k, v in row.items():
        if bool_cols and k in bool_cols:
            out[k] = "True" if v else "False"
        elif v is None:
            out[k] = ""
        else:
            out[k] = str(v)
    return out
from src.domain.execution import Execution
from src.domain.models import CycleSnapshot, InventoryPnL, OrderPlacementRecord

DB_PATH = "data/trading.db"


class Database:
    def __init__(self, path: str = DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA_SQL)

    # ── Sessions ──────────────────────────────────────────────────────────────

    def open_session(
        self,
        session_id: str,
        started_at: str,
        mode: str,
        account_name: str,
        binance_testnet: bool,
        enabled_symbols: list[str],
        config_snapshot: dict,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions
                    (session_id, started_at, mode, account_name,
                     binance_testnet, enabled_symbols, config_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    started_at,
                    mode,
                    account_name,
                    int(binance_testnet),
                    json.dumps(enabled_symbols),
                    json.dumps(config_snapshot),
                ),
            )

    def close_session(self, session_id: str, ended_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
                (ended_at, session_id),
            )

    # ── Section markers ───────────────────────────────────────────────────────

    def insert_section_marker(
        self,
        session_id: str,
        label: str,
        marker_type: str,
        started_at: str,
        metadata: dict | None = None,
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO section_markers (session_id, label, marker_type, started_at, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, label, marker_type, started_at, json.dumps(metadata) if metadata else None),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def close_section_marker(self, marker_id: int, ended_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE section_markers SET ended_at = ? WHERE id = ?",
                (ended_at, marker_id),
            )

    # ── Journal writes ────────────────────────────────────────────────────────

    def insert_cycle(self, session_id: str, s: CycleSnapshot) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO cycles (
                    session_id, timestamp, symbol,
                    best_bid, best_ask, spread, mid_price,
                    mid_return_1s_bps, mid_return_3s_bps, mid_return_5s_bps, volatility_5s_bps,
                    base_free, base_locked, base_total,
                    quote_free, quote_locked, quote_total,
                    inventory_bias, participation_mode,
                    proposed_bid, proposed_ask, proposed_bid_qty, proposed_ask_qty,
                    bid_placeable, ask_placeable, bid_block_reason, ask_block_reason,
                    canceled_orders, placed_count, canceled_buy, canceled_sell, decision_reason
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    session_id, s.timestamp, s.symbol,
                    float(s.best_bid), float(s.best_ask), float(s.spread), float(s.mid_price),
                    float(s.mid_return_1s_bps), float(s.mid_return_3s_bps),
                    float(s.mid_return_5s_bps), float(s.volatility_5s_bps),
                    float(s.base_free), float(s.base_locked), float(s.base_total),
                    float(s.quote_free), float(s.quote_locked), float(s.quote_total),
                    s.inventory_bias.value if hasattr(s.inventory_bias, 'value') else s.inventory_bias,
                    s.participation_mode,
                    float(s.proposed_bid) if s.proposed_bid is not None else None,
                    float(s.proposed_ask) if s.proposed_ask is not None else None,
                    float(s.proposed_bid_qty), float(s.proposed_ask_qty),
                    int(s.bid_placeable), int(s.ask_placeable),
                    s.bid_block_reason, s.ask_block_reason,
                    s.canceled_orders, s.placed_count, s.canceled_buy, s.canceled_sell,
                    s.decision_reason,
                ),
            )

    def insert_order(self, session_id: str, o: OrderPlacementRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO orders (
                    session_id, timestamp, symbol, side, order_id, client_order_id,
                    status, price, quantity, executed_quantity, placed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, o.timestamp, o.symbol, o.side, o.order_id, o.client_order_id,
                    o.status, float(o.price), float(o.quantity), float(o.executed_quantity),
                    o.placed_at,
                ),
            )

    def insert_equity(self, session_id: str, e: InventoryPnL) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO equity_snapshots (
                    session_id, timestamp, symbol,
                    base_free, base_locked, base_total,
                    quote_free, quote_locked, quote_total,
                    mid_price, mark_to_market_equity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, e.timestamp, e.symbol,
                    float(e.base_free), float(e.base_locked), float(e.base_total),
                    float(e.quote_free), float(e.quote_locked), float(e.quote_total),
                    float(e.mid_price), float(e.mark_to_market_equity),
                ),
            )

    def insert_execution(self, session_id: str, ex: Execution) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO executions (
                    session_id, exchange, account, symbol, trade_id, order_id,
                    client_order_id, side, price, qty, quote_qty,
                    commission, commission_asset, commission_in_quote,
                    commission_fx_rate, commission_fx_symbol, commission_fx_timestamp,
                    is_maker, executed_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, ex.exchange, ex.account, ex.symbol, ex.trade_id, ex.order_id,
                    ex.client_order_id, ex.side, float(ex.price), float(ex.qty), float(ex.quote_qty),
                    float(ex.commission), ex.commission_asset,
                    float(ex.commission_in_quote) if ex.commission_in_quote is not None else None,
                    float(ex.commission_fx_rate) if ex.commission_fx_rate is not None else None,
                    ex.commission_fx_symbol, ex.commission_fx_timestamp,
                    int(ex.is_maker), ex.executed_at, ex.source,
                ),
            )

    # ── Reconciled orders ─────────────────────────────────────────────────────

    def reset_reconciled_orders(self, session_id: str, symbol: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM reconciled_orders WHERE session_id = ? AND symbol = ?",
                (session_id, symbol),
            )

    def insert_reconciled_order(
        self,
        session_id: str,
        reconciled_at: str,
        updated_at: str,
        symbol: str,
        order_id: int,
        side: str,
        status: str,
        price: float,
        orig_qty: float,
        executed_qty: float,
        cumulative_quote_qty: float,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO reconciled_orders
                    (session_id, reconciled_at, updated_at, symbol, order_id, side,
                     status, price, orig_qty, executed_qty, cumulative_quote_qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, reconciled_at, updated_at, symbol, order_id, side,
                 status, price, orig_qty, executed_qty, cumulative_quote_qty),
            )

    # ── Analysis results ──────────────────────────────────────────────────────

    def insert_analysis_result(self, session_id: str, generated_at: str, payload: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM analysis_results WHERE session_id = ?", (session_id,)
            )
            self._conn.execute(
                "INSERT INTO analysis_results (session_id, generated_at, payload) VALUES (?, ?, ?)",
                (session_id, generated_at, json.dumps(payload)),
            )

    # ── Read queries (return CSV-compatible dicts) ────────────────────────────

    def get_session_started_at(self, session_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT started_at FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row[0] if row else None

    def get_all_sessions(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT session_id, started_at, ended_at, mode, account_name FROM sessions ORDER BY started_at"
        ).fetchall()
        return [
            {
                "session_id": r[0],
                "started_at": r[1] or "",
                "ended_at": r[2] or "",
                "mode": r[3] or "",
                "account_name": r[4] or "",
            }
            for r in rows
        ]

    def get_analysis_result(self, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT payload FROM analysis_results WHERE session_id = ?", (session_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def get_cycles_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM cycles WHERE session_id = ? ORDER BY timestamp", (session_id,)
        ).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM cycles LIMIT 0").description]
        return [_row_to_csv(dict(zip(cols, r)), _BOOL_COLS_CYCLES) for r in rows]

    def get_orders_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE session_id = ? ORDER BY timestamp", (session_id,)
        ).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM orders LIMIT 0").description]
        return [_row_to_csv(dict(zip(cols, r))) for r in rows]

    def get_equity_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM equity_snapshots WHERE session_id = ? ORDER BY timestamp", (session_id,)
        ).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM equity_snapshots LIMIT 0").description]
        return [_row_to_csv(dict(zip(cols, r))) for r in rows]

    def get_executions_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM executions WHERE session_id = ? ORDER BY executed_at", (session_id,)
        ).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM executions LIMIT 0").description]
        return [_row_to_csv(dict(zip(cols, r)), _BOOL_COLS_EXEC) for r in rows]

    def get_reconciled_orders_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM reconciled_orders WHERE session_id = ? ORDER BY order_id", (session_id,)
        ).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM reconciled_orders LIMIT 0").description]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            d["timestamp"] = d.get("reconciled_at", "")
            result.append(_row_to_csv(d))
        return result

    def close(self) -> None:
        self._conn.close()
