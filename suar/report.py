"""Papan risiko: halaman HTML statis + ringkasan teks dari SQLite.

Sengaja tanpa kerangka kerja apa pun — satu berkas HTML yang bisa dibuka
langsung atau ditaruh di GitHub Pages.
"""

import html
import json
import sqlite3
from datetime import datetime

from . import config
from .db import today

CSS = """
:root{--bg:#0d1117;--fg:#e6edf3;--dim:#8b949e;--line:#30363d;--warn:#d29922;
--bad:#f85149;--ok:#3fb950;--card:#161b22}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px} h2{font-size:17px;margin:32px 0 10px}
.sub{color:var(--dim);font-size:13px;margin-bottom:24px}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-bottom:8px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;
vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.04em}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tkr{font-weight:700}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
border:1px solid var(--line);margin:1px 3px 1px 0;white-space:nowrap}
.p-bad{color:var(--bad);border-color:var(--bad)}
.p-warn{color:var(--warn);border-color:var(--warn)}
.shut{color:var(--bad);font-weight:700}
.note{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:14px 16px;color:var(--dim);font-size:13px;margin:20px 0}
.why{color:var(--dim);font-size:12.5px}
@media(max-width:700px){body{padding:16px 12px}table{font-size:12.5px}
th,td{padding:6px 6px}}
"""

PILL = {
    "EKUITAS_NEGATIF": "p-bad", "FREE_FLOAT_RENDAH": "p-warn",
    "BELUM_LAPOR": "p-bad", "DORMAN": "p-bad", "LIKUIDITAS_RENDAH": "p-warn",
}


def _rp(x):
    return "—" if x is None else f"Rp{x:,.0f}".replace(",", ".")


def _exit(row):
    if row["days_to_exit_100m"] is None:
        if row["frozen_ratio"] is not None and row["frozen_ratio"] >= 0.99:
            return '<span class="shut">tertutup</span>'
        return "—"
    return f"{row['days_to_exit_100m']:.0f} hari"


def fetch_board(conn, asof: str | None = None, limit: int = 60):
    asof = asof or conn.execute("SELECT MAX(asof) FROM score_daily").fetchone()[0]
    rows = conn.execute(
        "SELECT s.symbol, c.company_name, s.criteria_met, s.is_suspended, s.detail_json,"
        "       e.median_value, e.frozen_ratio, e.frozen_streak, e.days_to_exit_100m "
        "FROM score_daily s "
        "LEFT JOIN company c    ON c.symbol = s.symbol "
        "LEFT JOIN exit_clock e ON e.symbol = s.symbol AND e.asof = s.asof "
        "WHERE s.asof = ? AND s.criteria_met > 0 "
        "ORDER BY s.criteria_met DESC, COALESCE(e.median_value, 0) ASC "
        "LIMIT ?", (asof, limit)).fetchall()
    return asof, rows


def render_html(conn, asof: str | None = None, limit: int = 60) -> str:
    asof, rows = fetch_board(conn, asof, limit)
    asof = asof or today()
    runs = conn.execute("SELECT * FROM v_run_summary").fetchall()
    credits = conn.execute("SELECT COALESCE(SUM(credits),0) FROM api_call").fetchone()[0]

    body = []
    for r in rows:
        det = json.loads(r["detail_json"] or "[]")
        pills = "".join(
            f'<span class="pill {PILL.get(d["kode"], "")}">{html.escape(d["kode"])}</span>'
            for d in det)
        why = "<br>".join(html.escape(d["alasan"]) for d in det)
        body.append(
            f'<tr><td class="tkr">{html.escape(r["symbol"])}</td>'
            f'<td>{html.escape(r["company_name"] or "")}<div class="why">{why}</div></td>'
            f'<td>{pills}</td>'
            f'<td class="num">{r["criteria_met"]}</td>'
            f'<td class="num">{_rp(r["median_value"])}</td>'
            f'<td class="num">{_exit(r)}</td></tr>')

    runrows = "".join(
        f'<tr><td>{html.escape(x["job"])}</td><td>{html.escape(x["trigger"])}</td>'
        f'<td class="num">{x["runs"]}</td><td class="num">{x["ok"]}</td>'
        f'<td class="num">{x["credits"]}</td>'
        f'<td>{html.escape(str(x["last_run"]))}</td></tr>' for x in runs)

    return f"""<!doctype html><html lang="id"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Suar — Papan Risiko IDX</title><style>{CSS}</style>
<div class="wrap">
<h1>Suar — Papan Risiko</h1>
<div class="sub">Jarak setiap emiten ke kriteria suspensi BEI &middot;
data per {html.escape(asof)} &middot; dibuat
{datetime.now(config.WIB).strftime('%Y-%m-%d %H:%M WIB')}</div>

<div class="note"><b>Ini informasi, bukan rekomendasi investasi.</b>
Suar tidak menetapkan status apa pun. Yang berwenang menetapkan suspensi dan
Papan Pemantauan Khusus adalah Bursa Efek Indonesia. Sistem ini hanya
menghitung jarak setiap emiten ke kriteria yang BEI terbitkan sendiri.</div>

<h2>Emiten dengan kriteria terpenuhi</h2>
<table><thead><tr><th>Kode</th><th>Perusahaan &amp; alasan</th><th>Kriteria</th>
<th class="num">Jml</th><th class="num">Transaksi/hari</th>
<th class="num">Jam keluar (Rp100jt)</th></tr></thead>
<tbody>{"".join(body) or '<tr><td colspan="6">belum ada data</td></tr>'}</tbody></table>
<div class="why">&ldquo;Jam keluar&rdquo; = hari bursa yang dibutuhkan untuk melepas
posisi Rp100 juta pada maksimum 10% volume harian.
&ldquo;Tertutup&rdquo; = harga tidak bergerak sama sekali; tidak ada transaksi
yang bisa menyerap penjualan.</div>

<h2>Jejak eksekusi</h2>
<table><thead><tr><th>Job</th><th>Pemicu</th><th class="num">Jalan</th>
<th class="num">OK</th><th class="num">Kredit</th><th>Terakhir</th></tr></thead>
<tbody>{runrows or '<tr><td colspan="6">belum ada</td></tr>'}</tbody></table>
<div class="why">Total kredit API terpakai: {credits}.</div>
</div></html>"""


def write_report(conn, path: str | None = None) -> str:
    config.OUT_DIR.mkdir(exist_ok=True)
    path = path or str(config.OUT_DIR / "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(conn))
    print(f"  papan risiko -> {path}")
    return path


def text_summary(conn, top: int = 15) -> str:
    asof, rows = fetch_board(conn, limit=top)
    out = [f"SUAR — papan risiko {asof}", ""]
    for r in rows:
        det = json.loads(r["detail_json"] or "[]")
        kode = ", ".join(d["kode"] for d in det)
        jam = ("tertutup" if r["days_to_exit_100m"] is None
               else f"{r['days_to_exit_100m']:.0f} hari")
        out.append(f"{r['symbol']:6s} {r['criteria_met']}x  {kode}  | keluar: {jam}")
    return "\n".join(out)
