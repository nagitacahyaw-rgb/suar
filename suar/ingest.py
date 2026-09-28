"""Ingestion: HANYA menulis ke SQLite, tidak pernah menghitung skor.

Pemisahan ini disengaja — rules engine membaca SQLite saja, sehingga
backtest historis dan perhitungan live memakai jalur kode yang sama persis.
"""

from datetime import date, timedelta

from . import config
from .db import now, sym, today

# ---------------------------------------------------------------- kategori


def categorize(reason: str | None) -> str:
    """Kategori suspensi. Satu-satunya 'perhitungan' di ingestion, disengaja:
    dipakai hampir semua query, lebih murah disimpan sekali."""
    r = (reason or "").lower()
    if "cooling down" in r or "harga kumulatif" in r:
        return "HARGA"
    if "laporan keuangan" in r:
        return "LAPKEU"
    if "v.1.1" in r or "v.1.2" in r:
        return "FREE_FLOAT"
    if "papan pemantauan khusus" in r:
        return "PPK_1TH"
    if "kelangsungan usaha" in r:
        return "GOING_CONCERN"
    if "biaya pencatatan" in r:
        return "BIAYA"
    return "LAIN"


def recent_quarters(n: int = 4, ref: date | None = None) -> list[str]:
    ref = ref or date.today()
    y, q = ref.year, (ref.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        q -= 1
        if q == 0:
            q, y = 4, y - 1
        out.append(f"Q{q}-{y}")
    return out


def quarter_end(q: str) -> date:
    qn, yr = q.split("-")
    m = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}[qn]
    d = {3: 31, 6: 30, 9: 30, 12: 31}[m]
    return date(int(yr), m, d)


# ------------------------------------------------------------------- jobs


def job_companies(conn, api, run):
    """Daftar emiten + market cap + papan pencatatan. ~5-10 kredit."""
    merged: dict[str, dict] = {}
    for field, where in [
        ("market_cap", "market_cap > 0"),
        ("listing_board", "listing_board like '%'"),
    ]:
        for r in api.companies(where, order_by="-market_cap" if field == "market_cap" else None):
            t = sym(r.get("symbol"))
            e = merged.setdefault(t, {"company_name": r.get("company_name")})
            e[field] = (r.get("query_values") or {}).get(field)

    ts = now()
    for t, v in merged.items():
        conn.execute(
            "INSERT INTO company(symbol,company_name,market_cap,listing_board,updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
            "company_name=excluded.company_name, market_cap=excluded.market_cap, "
            "listing_board=COALESCE(excluded.listing_board, company.listing_board), "
            "updated_at=excluded.updated_at",
            (t, v.get("company_name"), v.get("market_cap"), v.get("listing_board"), ts))
        run.rows += 1
    conn.commit()
    print(f"  company: {len(merged)} emiten")


def job_close(conn, api, run, on: str | None = None):
    """Harga penutupan seluruh bursa untuk satu tanggal. ~5 kredit."""
    on = on or str(date.today() - timedelta(days=1))
    rows = api.close_on(on)
    if not rows:
        print(f"  close {on}: kosong (kemungkinan libur bursa)")
        return 0
    for r in rows:
        conn.execute("INSERT OR REPLACE INTO close_daily(symbol,date,close) VALUES (?,?,?)",
                     (sym(r.get("symbol")), r.get("date"), r.get("close")))
        run.rows += 1
    conn.commit()
    print(f"  close {on}: {len(rows)} emiten")
    return len(rows)


def job_close_backfill(conn, api, run, days: int = 30):
    """Sapuan harga mundur N hari kalender. ~5 kredit per hari bursa.

    Ini yang membangun deret harga untuk deteksi dormansi seluruh pasar.
    """
    end = date.today() - timedelta(days=1)
    n = 0
    for i in range(days):
        d = end - timedelta(days=i)
        if d.weekday() >= 5:          # lewati akhir pekan
            continue
        have = conn.execute("SELECT COUNT(*) FROM close_daily WHERE date=?",
                            (str(d),)).fetchone()[0]
        if have > 100:                # sudah ada, jangan bayar dua kali
            continue
        n += job_close(conn, api, run, str(d))
    return n


def job_suspensions(conn, api, run):
    """Riwayat suspensi = ground truth. ~3 kredit."""
    rows = api.suspensions()
    ts = now()
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO suspension"
            "(symbol,suspension_date,reason,pdf_url,category,fetched_at) VALUES (?,?,?,?,?,?)",
            (sym(r.get("symbol")), r.get("suspension_date"), r.get("reason") or "",
             r.get("pdf_url"), categorize(r.get("reason")), ts))
        run.rows += 1
    conn.commit()
    print(f"  suspension: {len(rows)} record")


FUNDAMENTAL_FIELDS = [
    ("total_assets_mrq",      "total_assets_mrq > 0"),
    ("total_equity_mrq",      "total_equity_mrq != 0"),
    ("total_liabilities_mrq", "total_liabilities_mrq > 0"),
    ("free_float",            "free_float < 1"),
]


def job_fundamentals(conn, api, run):
    """Snapshot fundamental bertanggal. ~20 kredit.

    query_values hanya mengembalikan field yang disebut di klausa where,
    jadi satu query per field lalu digabung di sini.
    """
    asof = today()
    merged: dict[str, dict] = {}
    for field, where in FUNDAMENTAL_FIELDS:
        rows = api.companies(where)
        for r in rows:
            merged.setdefault(sym(r.get("symbol")), {})[field] = \
                (r.get("query_values") or {}).get(field)
        print(f"  {field}: {len(rows)} emiten")

    for t, v in merged.items():
        conn.execute(
            "INSERT OR REPLACE INTO snapshot_fundamental"
            "(symbol,asof,total_equity_mrq,total_assets_mrq,total_liabilities_mrq,free_float) "
            "VALUES (?,?,?,?,?,?)",
            (t, asof, v.get("total_equity_mrq"), v.get("total_assets_mrq"),
             v.get("total_liabilities_mrq"), v.get("free_float")))
        run.rows += 1
    conn.commit()
    print(f"  snapshot {asof}: {len(merged)} emiten")


def job_quarter_presence(conn, api, run, quarters: list[str] | None = None):
    """Kuartal mana yang sudah terbit per emiten. ~5 kredit per kuartal."""
    asof = today()
    quarters = quarters or recent_quarters(4)
    semua = {r[0] for r in conn.execute("SELECT symbol FROM company")}
    if not semua:
        print("  [!] tabel company kosong — jalankan job_companies dulu")
        return
    for q in quarters:
        rows = api.companies(f"total_assets_q[{q}] > 0", values=False)
        punya = {sym(r.get("symbol")) for r in rows}
        for t in semua:
            conn.execute(
                "INSERT OR REPLACE INTO quarter_presence(symbol,quarter,asof,has_data) "
                "VALUES (?,?,?,?)", (t, q, asof, 1 if t in punya else 0))
            run.rows += 1
        conn.commit()
        print(f"  {q}: {len(punya)} lapor / {len(semua) - len(punya)} belum")


def job_backfill_bars(conn, api, run, max_tickers: int | None = None,
                      days: int | None = None, tickers: list[str] | None = None):
    """Volume harian untuk kandidat. 1 kredit per emiten per 90 hari."""
    days = days or config.WINDOW_DAYS
    end = date.today()
    start = end - timedelta(days=days - 1)

    if tickers is None:
        tickers = [r[0] for r in conn.execute(
            "SELECT symbol FROM company WHERE market_cap > 0 "
            "ORDER BY market_cap ASC LIMIT ?", (max_tickers or config.BACKFILL_TICKERS,))]
    print(f"  {len(tickers)} kandidat x {days} hari")

    for i, t in enumerate(tickers, 1):
        for b in api.daily(t, str(start), str(end)):
            close, vol = b.get("close"), b.get("volume")
            conn.execute(
                "INSERT OR REPLACE INTO daily_bar"
                "(symbol,date,open,high,low,close,volume,market_cap,value) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (sym(b.get("symbol")), b.get("date"), b.get("open"), b.get("high"),
                 b.get("low"), close, vol, b.get("market_cap"),
                 (close or 0) * (vol or 0)))
            run.rows += 1
        if i % 10 == 0:
            conn.commit()
            print(f"  {i}/{len(tickers)} — {api.credits} kredit")
    conn.commit()


def job_poll(conn, api, run):
    """Cek pengumuman suspensi baru. ~3 kredit.

    BEI menerbitkan pengumuman di tengah hari; pipeline harian baru
    menangkapnya sore. Job ringan ini menutup jeda itu dan mengembalikan
    daftar emiten yang baru muncul.
    """
    sebelum = {(r[0], r[1]) for r in conn.execute(
        "SELECT symbol, suspension_date FROM suspension")}
    job_suspensions(conn, api, run)
    sesudah = {(r[0], r[1]) for r in conn.execute(
        "SELECT symbol, suspension_date FROM suspension")}
    baru = sorted(sesudah - sebelum)
    if baru:
        print(f"  BARU: {len(baru)} suspensi")
        for t, d in baru:
            print(f"    {t}  {d}")
    else:
        print("  tidak ada suspensi baru")
    return baru
