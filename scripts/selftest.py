#!/usr/bin/env python3
"""Uji mandiri tanpa API key.

Membuat database sementara berisi DATA UJI SINTETIS (bukan data pasar asli),
lalu menjalankan rules engine, papan risiko, dan lapis validasi.
Tujuannya membuktikan logika berjalan, bukan membuktikan hasil pasar.

    python scripts/selftest.py
"""

import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(tempfile.mkdtemp(), "selftest.db")
os.environ["SUAR_DB"] = DB
os.environ.setdefault("SECTORS_API_KEY", "dummy-untuk-uji")

from suar import backtest, config, report, rules          # noqa: E402
from suar.db import Run, init_db, now, today              # noqa: E402

config.DB_PATH = DB
ASOF = today()


def hari_bursa(n):
    out, d = [], date.fromisoformat(ASOF)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def seed(conn):
    days = hari_bursa(60)
    ts = now()

    # --- emiten uji (sintetis) ---
    profil = [
        # (kode, nama, mcap, ekuitas, free float, beku?, volume harian)
        ("ZZAA", "Uji Beku Total",      20e9,  -5e11, 0.30, True,  0),
        ("ZZBB", "Uji Ekuitas Negatif", 80e9,  -6e11, 0.28, False, 12_000),
        ("ZZCC", "Uji Free Float",     500e9,   9e11, 0.012, False, 400_000),
        ("ZZDD", "Uji Likuiditas",      30e9,   5e10, 0.45, False, 200),
        ("ZZEE", "Uji Sehat",         5000e9,   8e12, 0.35, False, 9_000_000),
    ]
    for kode, nama, mcap, eq, ff, beku, vol in profil:
        conn.execute("INSERT INTO company(symbol,company_name,market_cap,updated_at) "
                     "VALUES (?,?,?,?)", (kode, nama, int(mcap), ts))
        conn.execute("INSERT INTO snapshot_fundamental(symbol,asof,total_equity_mrq,"
                     "total_assets_mrq,total_liabilities_mrq,free_float) "
                     "VALUES (?,?,?,?,?,?)", (kode, ASOF, eq, abs(eq) * 3, abs(eq) * 2, ff))

        harga = 1000.0
        for i, d in enumerate(days):
            if not beku:
                harga = 1000 + (i % 7) * 25          # bergerak
            conn.execute("INSERT INTO close_daily(symbol,date,close) VALUES (?,?,?)",
                         (kode, d, harga))
            conn.execute(
                "INSERT INTO daily_bar(symbol,date,open,high,low,close,volume,value) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (kode, d, harga, harga, harga, harga, vol, harga * vol))

    # --- kuartal: ZZBB belum melaporkan Q4-2025 ---
    for kode, _, _, _, _, _, _ in profil:
        for q in ["Q4-2025", "Q1-2026"]:
            punya = 0 if (kode == "ZZBB" and q == "Q4-2025") else 1
            conn.execute("INSERT INTO quarter_presence(symbol,quarter,asof,has_data) "
                         "VALUES (?,?,?,?)", (kode, q, ASOF, punya))

    # --- ground truth sintetis ---
    conn.execute("INSERT INTO suspension(symbol,suspension_date,reason,category,fetched_at) "
                 "VALUES (?,?,?,?,?)",
                 ("ZZAA", days[-5], "Belum memenuhi ketentuan V.1.1. dan/atau V.1.2.",
                  "FREE_FLOAT", ts))
    conn.commit()


def main():
    print(f"database uji: {DB}\n")
    conn = init_db(DB)
    seed(conn)

    print("=" * 62)
    print("RULES ENGINE")
    print("=" * 62)
    with Run(conn, None, "selftest-score", "manual") as run:
        hasil = rules.score_all(conn, ASOF)
        run.rows = len(hasil)
    for r in hasil:
        kode = ", ".join(d["kode"] for d in r["detail"]) or "-"
        jam = "tertutup" if r["days_to_exit"] is None else f"{r['days_to_exit']:.0f} hari"
        print(f"  {r['symbol']}  {r['criteria_met']}x  {kode}")
        print(f"          jam keluar Rp100jt: {jam}")
        for d in r["detail"]:
            print(f"          - {d['alasan']}")

    print("\n" + "=" * 62)
    print("VALIDASI")
    print("=" * 62)
    hasil_v = backtest.run_all(conn)

    print("\n" + "=" * 62)
    print("PAPAN RISIKO")
    print("=" * 62)
    p = report.write_report(conn)
    print(report.text_summary(conn))

    # --- asersi ---
    idx = {r["symbol"]: r for r in hasil}
    cek = [
        ("ZZAA terdeteksi dorman",
         any(d["kode"] == "DORMAN" for d in idx["ZZAA"]["detail"])),
        ("ZZAA pintu keluar tertutup", idx["ZZAA"]["days_to_exit"] is None),
        ("ZZBB ekuitas negatif",
         any(d["kode"] == "EKUITAS_NEGATIF" for d in idx["ZZBB"]["detail"])),
        ("ZZBB telat lapor Q4-2025",
         any(d["kode"] == "BELUM_LAPOR" for d in idx["ZZBB"]["detail"])),
        ("ZZCC free float rendah",
         any(d["kode"] == "FREE_FLOAT_RENDAH" for d in idx["ZZCC"]["detail"])),
        ("ZZDD likuiditas rendah",
         any(d["kode"] == "LIKUIDITAS_RENDAH" for d in idx["ZZDD"]["detail"])),
        ("ZZEE bersih", idx.get("ZZEE", {"criteria_met": 0})["criteria_met"] == 0),
        ("uji unit rumus lolos", hasil_v["lapis1"]["gagal"] == 0),
        ("papan risiko terbentuk", os.path.getsize(p) > 1000),
    ]
    print("\n" + "=" * 62)
    gagal = 0
    for nama, ok in cek:
        print(f"  [{'OK ' if ok else 'GAGAL'}] {nama}")
        gagal += 0 if ok else 1
    print("=" * 62)
    print("SEMUA UJI LOLOS" if not gagal else f"{gagal} UJI GAGAL")
    return 1 if gagal else 0


if __name__ == "__main__":
    raise SystemExit(main())
