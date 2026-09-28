"""Notifikasi Telegram.

Prinsip: sistem diam kalau tidak ada yang melewati ambang. Produk yang
berbunyi setiap hari tidak akan dibaca orang.
"""

import json

import requests

from . import config
from .db import now, today


def format_alert(symbol: str, company: str, detail: list, median_value,
                 days_to_exit, position: float) -> str:
    baris = [f"*{symbol}* — {company or ''}".strip(), ""]
    for d in detail:
        baris.append(f"• {d['alasan']}")
    baris.append("")
    if days_to_exit is None:
        if median_value in (None, 0):
            baris.append("*Tidak ada transaksi.* Posisi tidak bisa dilepas saat ini.")
        else:
            baris.append("Jam keluar tidak dapat dihitung.")
    else:
        rp = f"Rp{position:,.0f}".replace(",", ".")
        baris.append(f"Melepas posisi {rp} butuh sekitar "
                     f"*{days_to_exit:.0f} hari bursa* "
                     f"(maksimum 10% volume harian).")
    baris += ["", "_Informasi, bukan rekomendasi jual atau beli. "
                  "Status resmi ditetapkan oleh BEI._"]
    return "\n".join(baris)


def build_alerts(conn, asof: str | None = None) -> list[dict]:
    """Susun alert untuk watchlist yang melewati ambang. Tidak mengirim."""
    asof = asof or conn.execute("SELECT MAX(asof) FROM score_daily").fetchone()[0]
    if not asof:
        return []
    rows = conn.execute(
        "SELECT w.chat_id, w.symbol, w.position_value, c.company_name, "
        "       s.criteria_met, s.detail_json, e.median_value, e.days_to_exit_100m "
        "FROM watchlist w "
        "JOIN score_daily s ON s.symbol = w.symbol AND s.asof = ? "
        "LEFT JOIN company c    ON c.symbol = w.symbol "
        "LEFT JOIN exit_clock e ON e.symbol = w.symbol AND e.asof = s.asof "
        "WHERE s.criteria_met >= ?", (asof, config.ALERT_MIN_CRITERIA)).fetchall()

    out = []
    for r in rows:
        detail = json.loads(r["detail_json"] or "[]")
        pos = r["position_value"] or config.POSITION_DEFAULT
        dte = r["days_to_exit_100m"]
        if dte is not None and pos:
            dte = dte * pos / config.POSITION_DEFAULT
        level = "MERAH" if r["criteria_met"] >= 3 else "KUNING"
        out.append({
            "chat_id": r["chat_id"], "symbol": r["symbol"], "asof": asof,
            "level": level,
            "message": format_alert(r["symbol"], r["company_name"], detail,
                                    r["median_value"], dte, pos),
        })
    return out


def send(conn, dry_run: bool = True) -> int:
    alerts = build_alerts(conn)
    terkirim = 0
    for a in alerts:
        dup = conn.execute(
            "SELECT 1 FROM alert WHERE chat_id=? AND symbol=? AND asof=? AND level=?",
            (a["chat_id"], a["symbol"], a["asof"], a["level"])).fetchone()
        if dup:
            continue
        sent_at = None
        if not dry_run and config.TELEGRAM_TOKEN:
            r = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": a["chat_id"], "text": a["message"],
                      "parse_mode": "Markdown"}, timeout=30)
            if r.status_code == 200:
                sent_at = now()
                terkirim += 1
            else:
                print(f"  [tg {r.status_code}] {r.text[:120]}")
        conn.execute(
            "INSERT OR IGNORE INTO alert(chat_id,symbol,asof,level,message,sent_at) "
            "VALUES (?,?,?,?,?,?)",
            (a["chat_id"], a["symbol"], a["asof"], a["level"], a["message"], sent_at))
    conn.commit()
    print(f"  alert: {len(alerts)} memenuhi ambang, {terkirim} terkirim"
          f"{' (dry run)' if dry_run else ''}")
    return terkirim
