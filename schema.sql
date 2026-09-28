-- ============================================================
-- SUAR — schema SQLite
--   tabel "fakta pasar" : kunci (symbol, date)  -> tanggal peristiwa
--   tabel "snapshot"    : kunci (symbol, asof)  -> tanggal KITA MENGAMATI.
--                         kolom asof inilah yang mengubah API point-in-time
--                         menjadi deret waktu yang tidak disediakan API.
--   tabel "jejak"       : run_log / api_call -> audit eksekusi + anggaran kredit
-- ============================================================

PRAGMA journal_mode = WAL;

-- ---------- 1. REFERENSI ----------

CREATE TABLE IF NOT EXISTS company (
    symbol          TEXT PRIMARY KEY,
    company_name    TEXT,
    sector          TEXT,
    sub_sector      TEXT,
    listing_board   TEXT,
    market_cap      INTEGER,
    updated_at      TEXT NOT NULL
);

-- ---------- 2. FAKTA PASAR ----------

CREATE TABLE IF NOT EXISTS close_daily (
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,
    close   REAL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS ix_close_date ON close_daily(date);

CREATE TABLE IF NOT EXISTS daily_bar (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    market_cap  INTEGER,
    value       REAL,          -- close * volume, diisi saat ingest
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS ix_bar_date ON daily_bar(date);

-- ---------- 3. SNAPSHOT ----------

CREATE TABLE IF NOT EXISTS snapshot_fundamental (
    symbol                  TEXT NOT NULL,
    asof                    TEXT NOT NULL,
    total_equity_mrq        REAL,
    total_assets_mrq        REAL,
    total_liabilities_mrq   REAL,
    free_float              REAL,
    PRIMARY KEY (symbol, asof)
);

-- has_data = 0 pada kuartal lama  ->  emiten belum melaporkan.
-- Ketiadaan data ADALAH pengukurannya.
CREATE TABLE IF NOT EXISTS quarter_presence (
    symbol    TEXT NOT NULL,
    quarter   TEXT NOT NULL,      -- 'Q4-2025'
    asof      TEXT NOT NULL,
    has_data  INTEGER NOT NULL CHECK (has_data IN (0,1)),
    PRIMARY KEY (symbol, quarter, asof)
);

-- ---------- 4. GROUND TRUTH ----------

CREATE TABLE IF NOT EXISTS suspension (
    symbol           TEXT NOT NULL,
    suspension_date  TEXT NOT NULL,
    reason           TEXT NOT NULL DEFAULT '',
    pdf_url          TEXT,
    category         TEXT,
    fetched_at       TEXT NOT NULL,
    PRIMARY KEY (symbol, suspension_date, reason)
);
CREATE INDEX IF NOT EXISTS ix_sus_date ON suspension(suspension_date);
CREATE INDEX IF NOT EXISTS ix_sus_cat  ON suspension(category);

CREATE TABLE IF NOT EXISTS announcement (
    pdf_url     TEXT PRIMARY KEY,
    fetched_at  TEXT,
    parsed_at   TEXT,
    n_chars     INTEGER,
    raw_text    TEXT
);

-- roster lengkap per pengumuman (regex tabel IDX)
CREATE TABLE IF NOT EXISTS announcement_company (
    pdf_url       TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    company_name  TEXT,
    status        TEXT,
    PRIMARY KEY (pdf_url, symbol)
);

-- kriteria yang hanya hidup dalam prosa (going concern, PKPU, ganti auditor)
CREATE TABLE IF NOT EXISTS criterion_flag (
    symbol      TEXT NOT NULL,
    asof        TEXT NOT NULL,
    criterion   TEXT NOT NULL,
    value       INTEGER NOT NULL CHECK (value IN (0,1)),
    source      TEXT,
    confidence  REAL,
    PRIMARY KEY (symbol, asof, criterion)
);

-- ---------- 5. HASIL RULES ENGINE (tanpa panggilan API) ----------

CREATE TABLE IF NOT EXISTS score_daily (
    symbol        TEXT NOT NULL,
    asof          TEXT NOT NULL,
    criteria_met  INTEGER NOT NULL,
    is_suspended  INTEGER NOT NULL DEFAULT 0,
    detail_json   TEXT NOT NULL,
    PRIMARY KEY (symbol, asof)
);
CREATE INDEX IF NOT EXISTS ix_score_asof ON score_daily(asof);

CREATE TABLE IF NOT EXISTS exit_clock (
    symbol             TEXT NOT NULL,
    asof               TEXT NOT NULL,
    median_value       REAL,     -- nilai transaksi harian median (IDR)
    frozen_ratio       REAL,     -- proporsi hari harga tidak berubah
    frozen_streak      INTEGER,  -- hari beku berturut-turut terakhir
    days_to_exit_100m  REAL,     -- hari bursa untuk keluar dari Rp100 juta @10%
    PRIMARY KEY (symbol, asof)
);

-- ---------- 6. PENGGUNA ----------

CREATE TABLE IF NOT EXISTS watchlist (
    chat_id         TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    position_value  REAL DEFAULT 100000000,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (chat_id, symbol)
);

CREATE TABLE IF NOT EXISTS alert (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  TEXT NOT NULL,
    symbol   TEXT NOT NULL,
    asof     TEXT NOT NULL,
    level    TEXT NOT NULL,
    message  TEXT NOT NULL,
    sent_at  TEXT,
    UNIQUE (chat_id, symbol, asof, level)
);

-- ---------- 7. JEJAK EKSEKUSI ----------

CREATE TABLE IF NOT EXISTS run_log (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    job           TEXT NOT NULL,
    trigger       TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT,
    rows_written  INTEGER DEFAULT 0,
    credits       INTEGER DEFAULT 0,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS api_call (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER,
    endpoint     TEXT NOT NULL,
    params       TEXT,
    status_code  INTEGER,
    credits      INTEGER DEFAULT 0,
    latency_ms   INTEGER,
    called_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_call_run ON api_call(run_id);

-- ---------- VIEW ----------

CREATE VIEW IF NOT EXISTS v_run_summary AS
SELECT job, trigger, COUNT(*) AS runs,
       SUM(status = 'ok')  AS ok,
       SUM(credits)        AS credits,
       MIN(started_at)     AS first_run,
       MAX(started_at)     AS last_run
FROM run_log GROUP BY job, trigger;

CREATE VIEW IF NOT EXISTS v_credit_usage AS
SELECT DATE(called_at) AS tanggal, COUNT(*) AS panggilan, SUM(credits) AS kredit
FROM api_call GROUP BY DATE(called_at) ORDER BY tanggal;

CREATE VIEW IF NOT EXISTS v_papan_risiko AS
SELECT s.asof, s.symbol, c.company_name, s.criteria_met, s.is_suspended,
       e.median_value, e.frozen_ratio, e.days_to_exit_100m, s.detail_json
FROM score_daily s
LEFT JOIN company    c ON c.symbol = s.symbol
LEFT JOIN exit_clock e ON e.symbol = s.symbol AND e.asof = s.asof
WHERE s.asof = (SELECT MAX(asof) FROM score_daily)
ORDER BY s.criteria_met DESC, e.median_value ASC;
