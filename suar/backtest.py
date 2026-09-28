"""Validasi berjenjang.

Lapis 1  uji unit rumus jam keluar terhadap kasus berjawaban diketahui
Lapis 2  kalibrasi proksi dormansi terhadap volume asli
Lapis 3  rekonstruksi: apakah sistem bisa menandai emiten yang SUDAH disuspensi
Lapis 4  ground truth eksternal: 38 emiten Peng-S-00027/BEI.PLP/10-2025

Lapis 3 lebih penting daripada lapis 4. Kalau sistem tidak bisa mereproduksi
status hari ini dari data mentah, ia tidak berhak bicara soal prediksi.
"""

import csv
import json
import statistics

from . import config
from .db import today
from .rules import frozen_stats, exit_days, value_stats

GT_FILE = config.DATA_DIR / "ground_truth_freefloat_2025-10-31.csv"


# ------------------------------------------------------------------ lapis 1

def layer1_unit() -> dict:
    """Rumus jam keluar terhadap kasus yang jawabannya bisa dihitung tangan."""
    cases = [
        # (nilai transaksi harian, posisi, partisipasi, jawaban benar)
        (10_000_000, 100_000_000, 0.10, 100.0),
        (100_000_000, 100_000_000, 0.10, 10.0),
        (73_842_300, 100_000_000, 0.10, 13.5),
        (0, 100_000_000, 0.10, None),
    ]
    fails = []
    for mv, pos, part, want in cases:
        got = exit_days(mv, pos, part)
        if want is None:
            ok = got is None
        else:
            ok = got is not None and abs(got - want) <= 0.15
        if not ok:
            fails.append({"median_value": mv, "harapan": want, "hasil": got})
    return {"lapis": 1, "nama": "uji unit rumus", "kasus": len(cases),
            "gagal": len(fails), "detail": fails}


# ------------------------------------------------------------------ lapis 2

def layer2_calibration(conn, asof: str | None = None) -> dict:
    """Proksi harga beku vs volume asli, untuk emiten yang punya keduanya."""
    asof = asof or today()
    fr = frozen_stats(conn, asof)
    va = value_stats(conn, asof)
    both = sorted(set(fr) & set(va))
    if len(both) < 3:
        return {"lapis": 2, "nama": "kalibrasi proksi dormansi",
                "status": "data kurang", "n": len(both)}

    rows = []
    for t in both:
        zero_ish = 1 if va[t]["median_value"] <= 0 else 0
        rows.append((t, fr[t]["frozen_ratio"], va[t]["median_value"], zero_ish))

    x = [r[1] for r in rows]
    y = [r[3] for r in rows]
    corr = None
    if len(set(x)) > 1 and len(set(y)) > 1:
        mx, my = statistics.mean(x), statistics.mean(y)
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
        corr = round(num / den, 4) if den else None

    tp = sum(1 for r in rows if r[1] >= config.FROZEN_RATIO_WARN and r[3] == 1)
    fp = sum(1 for r in rows if r[1] >= config.FROZEN_RATIO_WARN and r[3] == 0)
    fn = sum(1 for r in rows if r[1] < config.FROZEN_RATIO_WARN and r[3] == 1)
    return {"lapis": 2, "nama": "kalibrasi proksi dormansi", "n": len(rows),
            "korelasi": corr, "true_positive": tp, "false_positive": fp,
            "false_negative": fn,
            "presisi": round(tp / (tp + fp), 3) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 3) if (tp + fn) else None}


# ------------------------------------------------------------------ lapis 3

def layer3_reconstruct(conn, asof: str | None = None) -> dict:
    """Apakah sistem menandai emiten yang memang sudah disuspensi?

    Ini uji reproduksi, bukan prediksi: kalau gagal di sini, klaim apa pun
    tentang peringatan dini tidak punya dasar.
    """
    asof = asof or conn.execute("SELECT MAX(asof) FROM score_daily").fetchone()[0]
    if not asof:
        return {"lapis": 3, "status": "score_daily kosong"}

    sus = {r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM suspension "
        "WHERE category != 'HARGA' AND suspension_date >= date(?, '-365 day')", (asof,))}
    scored = {r["symbol"]: r["criteria_met"] for r in conn.execute(
        "SELECT symbol, criteria_met FROM score_daily WHERE asof = ?", (asof,))}
    if not scored:
        return {"lapis": 3, "status": "belum ada skor"}

    ditandai = {t for t, n in scored.items() if n >= 1}
    tertangkap = sorted(sus & ditandai)
    lolos = sorted(sus - ditandai)
    return {
        "lapis": 3, "nama": "rekonstruksi status berjalan", "asof": asof,
        "suspensi_non_harga_12bln": len(sus),
        "tertangkap": len(tertangkap),
        "lolos": len(lolos),
        "recall": round(len(tertangkap) / len(sus), 3) if sus else None,
        "contoh_lolos": lolos[:10],
    }


# ------------------------------------------------------------------ lapis 4

def load_ground_truth() -> list[dict]:
    if not GT_FILE.exists():
        return []
    with open(GT_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def layer4_external(conn, asof: str | None = None) -> dict:
    """38 emiten dari pengumuman resmi BEI 31 Oktober 2025."""
    gt = load_ground_truth()
    if not gt:
        return {"lapis": 4, "status": "berkas ground truth tidak ada"}
    asof = asof or conn.execute("SELECT MAX(asof) FROM score_daily").fetchone()[0]
    tickers = {g["symbol"] for g in gt}

    scored = {r["symbol"]: r["criteria_met"] for r in conn.execute(
        "SELECT symbol, criteria_met FROM score_daily WHERE asof = ?", (asof,))}
    in_api = {r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM suspension WHERE category = 'FREE_FLOAT'")}

    ditandai = sorted(t for t in tickers if scored.get(t, 0) >= 1)
    return {
        "lapis": 4, "nama": "ground truth pengumuman BEI", "asof": asof,
        "total_ground_truth": len(tickers),
        "tercatat_di_api_suspensi": len(tickers & in_api),
        "ditandai_sistem": len(ditandai),
        "recall": round(len(ditandai) / len(tickers), 3),
        "tidak_ditandai": sorted(tickers - set(ditandai))[:15],
        "catatan": "Kriteria jumlah pemegang saham (V.1.2) tidak tersedia di API, "
                   "sehingga sebagian emiten pada daftar ini memang tidak bisa "
                   "dijelaskan oleh data yang ada. Lihat docs/LIMITATIONS.md.",
    }


# ------------------------------------------------------------------ runner

def run_all(conn, asof: str | None = None) -> dict:
    hasil = {
        "dijalankan": today(),
        "lapis1": layer1_unit(),
        "lapis2": layer2_calibration(conn, asof),
        "lapis3": layer3_reconstruct(conn, asof),
        "lapis4": layer4_external(conn, asof),
    }
    config.OUT_DIR.mkdir(exist_ok=True)
    p = config.OUT_DIR / "validation.json"
    p.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(hasil, indent=2, ensure_ascii=False))
    print(f"\n  -> {p}")
    return hasil
