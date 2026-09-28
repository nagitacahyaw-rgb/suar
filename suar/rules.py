"""Rules engine.

Membaca SQLite, tidak pernah memanggil API. Konsekuensinya: perhitungan live
dan backtest historis memakai fungsi yang sama persis — jadi angka backtest
tidak bisa "curang" dengan memakai jalur kode yang berbeda.

Setiap kriteria mengembalikan alasan dalam bahasa manusia, karena produk ini
harus bisa menjelaskan dirinya ke investor ritel, bukan hanya memberi skor.
"""

import json
import statistics
from datetime import date, datetime, timedelta

from . import config
from .db import today
from .ingest import quarter_end

# ------------------------------------------------------------------ utils


def _d(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def latest_snapshot_asof(conn, asof: str) -> str | None:
    r = conn.execute(
        "SELECT MAX(asof) FROM snapshot_fundamental WHERE asof <= ?", (asof,)).fetchone()
    return r[0] if r else None


# ------------------------------------------------------- dormansi & likuiditas


def frozen_stats(conn, asof: str, window: int = None) -> dict[str, dict]:
    """Statistik harga beku dari close_daily, untuk SELURUH bursa.

    Harga penutupan yang tidak berubah berarti tidak ada transaksi.
    Proksi ini terkalibrasi terhadap volume asli (korelasi 0,998) dan membuat
    pemantauan 962 emiten jadi ~190x lebih murah daripada menarik volume
    satu per satu. Lihat docs/VALIDATION.md.
    """
    window = window or config.WINDOW_DAYS
    start = str(_d(asof) - timedelta(days=window))
    rows = conn.execute(
        "SELECT symbol, date, close FROM close_daily "
        "WHERE date > ? AND date <= ? ORDER BY symbol, date", (start, asof)).fetchall()

    series: dict[str, list] = {}
    for r in rows:
        series.setdefault(r["symbol"], []).append(r["close"])

    out = {}
    for t, xs in series.items():
        if len(xs) < 5:
            continue
        unchanged = sum(1 for a, b in zip(xs, xs[1:]) if a == b)
        streak = 0
        for a, b in zip(reversed(xs[:-1]), reversed(xs[1:])):
            if a == b:
                streak += 1
            else:
                break
        out[t] = {
            "n_days": len(xs),
            "frozen_ratio": round(unchanged / (len(xs) - 1), 4),
            "frozen_streak": streak,
        }
    return out


def value_stats(conn, asof: str, window: int = None) -> dict[str, dict]:
    """Nilai transaksi harian dari daily_bar (hanya emiten kandidat)."""
    window = window or config.WINDOW_DAYS
    start = str(_d(asof) - timedelta(days=window))
    rows = conn.execute(
        "SELECT symbol, value FROM daily_bar WHERE date > ? AND date <= ?",
        (start, asof)).fetchall()
    series: dict[str, list] = {}
    for r in rows:
        series.setdefault(r["symbol"], []).append(r["value"] or 0.0)
    return {t: {"median_value": statistics.median(v), "n_days": len(v)}
            for t, v in series.items() if v}


def exit_days(median_value: float, position: float = None,
              participation: float = None) -> float | None:
    """Hari bursa untuk melikuidasi posisi tanpa menekan harga sendiri.

    days = posisi / (partisipasi x nilai transaksi harian median)
    Partisipasi dibatasi 10% volume harian; di atas itu penjualannya sendiri
    yang menggerakkan harga.
    """
    position = position or config.POSITION_DEFAULT
    participation = participation or config.PARTICIPATION
    if not median_value or median_value <= 0:
        return None                      # tidak ada pintu keluar sama sekali
    return round(position / (participation * median_value), 1)


# ------------------------------------------------------------------ kriteria


def evaluate(conn, symbol: str, asof: str, snap, frozen, values,
             late_quarters, prose_flags, suspended_recent) -> dict:
    """Kumpulkan kriteria yang terpenuhi untuk satu emiten pada satu tanggal."""
    met = []

    if snap and snap["total_equity_mrq"] is not None and snap["total_equity_mrq"] < 0:
        met.append({
            "kode": "EKUITAS_NEGATIF",
            "alasan": f"Ekuitas negatif: Rp{snap['total_equity_mrq']:,.0f}",
            "rujukan": "Peraturan I-X ketentuan ekuitas negatif",
        })

    if snap and snap["free_float"] is not None and snap["free_float"] < config.FREE_FLOAT_MIN:
        met.append({
            "kode": "FREE_FLOAT_RENDAH",
            "alasan": f"Free float {snap['free_float']*100:.2f}% "
                      f"(ambang {config.FREE_FLOAT_MIN*100:.1f}%)",
            "rujukan": "Peraturan I-A ketentuan V.1.1",
        })

    for q in late_quarters:
        met.append({
            "kode": "BELUM_LAPOR",
            "alasan": f"Laporan {q} belum terbit, "
                      f"{(_d(asof) - quarter_end(q)).days} hari setelah tutup buku",
            "rujukan": "Kewajiban pelaporan berkala",
        })

    f = frozen.get(symbol)
    if f and (f["frozen_ratio"] >= config.FROZEN_RATIO_WARN
              or f["frozen_streak"] >= config.FROZEN_STREAK_WARN):
        met.append({
            "kode": "DORMAN",
            "alasan": f"Harga tidak bergerak {f['frozen_ratio']*100:.0f}% hari bursa "
                      f"({f['frozen_streak']} hari beruntun terakhir)",
            "rujukan": "Proksi likuiditas terkalibrasi",
        })

    v = values.get(symbol)
    if v and v["median_value"] < config.LOW_VALUE_IDR:
        met.append({
            "kode": "LIKUIDITAS_RENDAH",
            "alasan": f"Nilai transaksi harian median Rp{v['median_value']:,.0f} "
                      f"(ambang Rp{config.LOW_VALUE_IDR:,.0f})",
            "rujukan": "Kriteria likuiditas Papan Pemantauan Khusus",
        })

    for pf in prose_flags.get(symbol, []):
        met.append({
            "kode": pf["criterion"],
            "alasan": f"Terdeteksi dari pengumuman BEI",
            "rujukan": pf["source"] or "",
        })

    jam = None
    if v:
        jam = exit_days(v["median_value"])
    elif f and f["frozen_ratio"] >= 0.99:
        jam = None                        # pintu sudah tertutup

    return {
        "symbol": symbol,
        "asof": asof,
        "criteria_met": len(met),
        "is_suspended": 1 if symbol in suspended_recent else 0,
        "detail": met,
        "frozen": f,
        "value": v,
        "days_to_exit": jam,
    }


def score_all(conn, asof: str | None = None, write: bool = True) -> list[dict]:
    """Hitung skor seluruh emiten untuk satu tanggal. Tanpa panggilan API."""
    asof = asof or today()
    snap_asof = latest_snapshot_asof(conn, asof)

    snaps = {}
    if snap_asof:
        snaps = {r["symbol"]: r for r in conn.execute(
            "SELECT * FROM snapshot_fundamental WHERE asof = ?", (snap_asof,))}

    frozen = frozen_stats(conn, asof)
    values = value_stats(conn, asof)

    # kuartal yang sudah lewat tenggat tapi belum terbit
    qp_asof = conn.execute(
        "SELECT MAX(asof) FROM quarter_presence WHERE asof <= ?", (asof,)).fetchone()[0]
    late: dict[str, list] = {}
    if qp_asof:
        for r in conn.execute(
                "SELECT symbol, quarter FROM quarter_presence "
                "WHERE asof = ? AND has_data = 0", (qp_asof,)):
            if (_d(asof) - quarter_end(r["quarter"])).days > config.LATE_DAYS:
                late.setdefault(r["symbol"], []).append(r["quarter"])

    prose: dict[str, list] = {}
    for r in conn.execute(
            "SELECT symbol, criterion, source FROM criterion_flag "
            "WHERE asof <= ? AND value = 1", (asof,)):
        prose.setdefault(r["symbol"], []).append(dict(r))

    cutoff = str(_d(asof) - timedelta(days=180))
    suspended = {r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM suspension "
        "WHERE suspension_date BETWEEN ? AND ? AND category != 'HARGA'", (cutoff, asof))}

    universe = {r[0] for r in conn.execute("SELECT symbol FROM company")}
    universe |= set(snaps) | set(frozen) | set(values) | set(late)

    out = []
    for t in sorted(universe):
        res = evaluate(conn, t, asof, snaps.get(t), frozen, values,
                       late.get(t, []), prose, suspended)
        if res["criteria_met"] == 0 and not res["frozen"] and not res["value"]:
            continue
        out.append(res)

    if write:
        for r in out:
            conn.execute(
                "INSERT OR REPLACE INTO score_daily"
                "(symbol,asof,criteria_met,is_suspended,detail_json) VALUES (?,?,?,?,?)",
                (r["symbol"], asof, r["criteria_met"], r["is_suspended"],
                 json.dumps(r["detail"], ensure_ascii=False)))
            f, v = r["frozen"], r["value"]
            if f or v:
                conn.execute(
                    "INSERT OR REPLACE INTO exit_clock"
                    "(symbol,asof,median_value,frozen_ratio,frozen_streak,days_to_exit_100m) "
                    "VALUES (?,?,?,?,?,?)",
                    (r["symbol"], asof, v["median_value"] if v else None,
                     f["frozen_ratio"] if f else None,
                     f["frozen_streak"] if f else None, r["days_to_exit"]))
        conn.commit()

    out.sort(key=lambda x: (-x["criteria_met"],
                            x["value"]["median_value"] if x["value"] else 0))
    return out
