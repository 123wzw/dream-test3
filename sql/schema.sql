CREATE TABLE IF NOT EXISTS ods_events (
    event_id     TEXT NOT NULL UNIQUE,
    user_id      TEXT NOT NULL,
    email        TEXT,
    event_type   TEXT NOT NULL,
    amount_cents INTEGER,
    ts_utc       TEXT NOT NULL,
    dt           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dwd_events (
    event_id     TEXT UNIQUE,
    user_id      TEXT NOT NULL,
    email        TEXT,
    event_type   TEXT NOT NULL,
    amount_cents INTEGER,
    ts_utc       TEXT NOT NULL,
    dt           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dws_daily (
    dt        TEXT PRIMARY KEY,
    dau       INTEGER NOT NULL,
    orders    INTEGER NOT NULL,
    gmv_cents INTEGER NOT NULL
);
