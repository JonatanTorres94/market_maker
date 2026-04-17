SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    UNIQUE NOT NULL,
    started_at      TEXT    NOT NULL,
    ended_at        TEXT,
    mode            TEXT    NOT NULL DEFAULT 'paper',
    account_name    TEXT,
    binance_testnet INTEGER,
    enabled_symbols TEXT,
    config_snapshot TEXT
);

CREATE TABLE IF NOT EXISTS section_markers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    label        TEXT NOT NULL,
    marker_type  TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    metadata     TEXT
);

CREATE TABLE IF NOT EXISTS cycles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL,
    timestamp           TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    best_bid            REAL,
    best_ask            REAL,
    spread              REAL,
    mid_price           REAL,
    mid_return_1s_bps   REAL,
    mid_return_3s_bps   REAL,
    mid_return_5s_bps   REAL,
    volatility_5s_bps   REAL,
    base_free           REAL,
    base_locked         REAL,
    base_total          REAL,
    quote_free          REAL,
    quote_locked        REAL,
    quote_total         REAL,
    inventory_bias      TEXT,
    participation_mode  TEXT,
    proposed_bid        REAL,
    proposed_ask        REAL,
    proposed_bid_qty    REAL,
    proposed_ask_qty    REAL,
    bid_placeable       INTEGER,
    ask_placeable       INTEGER,
    bid_block_reason    TEXT,
    ask_block_reason    TEXT,
    canceled_orders     INTEGER,
    placed_count        INTEGER,
    canceled_buy        INTEGER,
    canceled_sell       INTEGER,
    decision_reason     TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT    NOT NULL,
    timestamp         TEXT    NOT NULL,
    symbol            TEXT    NOT NULL,
    side              TEXT    NOT NULL,
    order_id          INTEGER NOT NULL,
    client_order_id   TEXT,
    status            TEXT,
    price             REAL,
    quantity          REAL,
    executed_quantity REAL,
    placed_at         TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT    NOT NULL,
    exchange                TEXT    NOT NULL,
    account                 TEXT    NOT NULL,
    symbol                  TEXT    NOT NULL,
    trade_id                INTEGER NOT NULL,
    order_id                INTEGER NOT NULL,
    client_order_id         TEXT,
    side                    TEXT,
    price                   REAL,
    qty                     REAL,
    quote_qty               REAL,
    commission              REAL,
    commission_asset        TEXT,
    commission_in_quote     REAL,
    commission_fx_rate      REAL,
    commission_fx_symbol    TEXT,
    commission_fx_timestamp TEXT,
    is_maker                INTEGER,
    executed_at             TEXT    NOT NULL,
    source                  TEXT,
    UNIQUE(exchange, account, symbol, trade_id)
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT NOT NULL,
    timestamp            TEXT NOT NULL,
    symbol               TEXT NOT NULL,
    base_free            REAL,
    base_locked          REAL,
    base_total           REAL,
    quote_free           REAL,
    quote_locked         REAL,
    quote_total          REAL,
    mid_price            REAL,
    mark_to_market_equity REAL
);

CREATE TABLE IF NOT EXISTS reconciled_orders (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id            TEXT    NOT NULL,
    reconciled_at         TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    symbol                TEXT    NOT NULL,
    order_id              INTEGER NOT NULL,
    side                  TEXT    NOT NULL,
    status                TEXT    NOT NULL,
    price                 REAL,
    orig_qty              REAL,
    executed_qty          REAL,
    cumulative_quote_qty  REAL,
    UNIQUE(session_id, order_id)
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    generated_at TEXT    NOT NULL,
    payload      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cycles_session       ON cycles(session_id);
CREATE INDEX IF NOT EXISTS idx_cycles_timestamp     ON cycles(timestamp);
CREATE INDEX IF NOT EXISTS idx_orders_session       ON orders(session_id);
CREATE INDEX IF NOT EXISTS idx_executions_session   ON executions(session_id);
CREATE INDEX IF NOT EXISTS idx_equity_session       ON equity_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_markers_session      ON section_markers(session_id);
CREATE INDEX IF NOT EXISTS idx_reconciled_session   ON reconciled_orders(session_id);
CREATE INDEX IF NOT EXISTS idx_analysis_session     ON analysis_results(session_id);
"""
