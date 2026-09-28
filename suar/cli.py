"""Titik masuk tunggal: python -m suar <perintah>"""

import argparse
import sys

from . import announcements, backtest, config, ingest, notify, report, rules
from .db import Run, connect, init_db, today


def _api(conn):
    from .client import SectorsClient
    return SectorsClient(conn)


def cmd_init(a):
    init_db()
    print(f"database siap: {config.DB_PATH}")


def cmd_bootstrap(a):
    """Sekali jalan: isi semua yang dibutuhkan sistem. ~150-250 kredit."""
    conn = init_db()
    api = _api(conn)
    with Run(conn, api, "bootstrap", a.trigger) as run:
        ingest.job_companies(conn, api, run)
        ingest.job_suspensions(conn, api, run)
        ingest.job_fundamentals(conn, api, run)
        ingest.job_quarter_presence(conn, api, run)
        ingest.job_close_backfill(conn, api, run, days=a.close_days)
        ingest.job_backfill_bars(conn, api, run, max_tickers=a.tickers)
    cmd_score(a, conn)


def cmd_daily(a):
    conn = connect()
    api = _api(conn)
    with Run(conn, api, "daily", a.trigger) as run:
        ingest.job_close(conn, api, run, a.date)
        ingest.job_suspensions(conn, api, run)
    cmd_score(a, conn)


def cmd_weekly(a):
    conn = connect()
    api = _api(conn)
    with Run(conn, api, "weekly", a.trigger) as run:
        ingest.job_companies(conn, api, run)
        ingest.job_fundamentals(conn, api, run)
        ingest.job_quarter_presence(conn, api, run)
    cmd_score(a, conn)


def cmd_bars(a):
    conn = connect()
    api = _api(conn)
    with Run(conn, api, "bars", a.trigger) as run:
        ingest.job_backfill_bars(conn, api, run, max_tickers=a.tickers,
                                 tickers=a.only.split(",") if a.only else None)


def cmd_poll(a):
    """Job ringan: cek pengumuman suspensi baru. ~3 kredit."""
    conn = connect()
    api = _api(conn)
    with Run(conn, api, "poll", a.trigger) as run:
        baru = ingest.job_poll(conn, api, run)
    if baru:
        cmd_score(a, conn)


def cmd_parse(a):
    conn = connect()
    with Run(conn, None, "parse", a.trigger) as run:
        announcements.job_parse_announcements(conn, run, limit=a.limit)


def cmd_score(a, conn=None):
    conn = conn or connect()
    with Run(conn, None, "score", getattr(a, "trigger", "manual")) as run:
        rows = rules.score_all(conn, getattr(a, "date", None) or today())
        run.rows = len(rows)
        kena = [r for r in rows if r["criteria_met"] > 0]
        print(f"  {len(kena)} emiten dengan kriteria terpenuhi")
        for r in kena[:10]:
            kode = ", ".join(d["kode"] for d in r["detail"])
            print(f"    {r['symbol']:6s} {r['criteria_met']}x  {kode}")
    report.write_report(conn)
    notify.send(conn, dry_run=not getattr(a, "send", False))


def cmd_validate(a):
    backtest.run_all(connect())


def cmd_watch(a):
    conn = connect()
    from .db import now
    for t in a.symbols.split(","):
        conn.execute("INSERT OR REPLACE INTO watchlist"
                     "(chat_id,symbol,position_value,created_at) VALUES (?,?,?,?)",
                     (a.chat, t.strip().upper(), a.position, now()))
    conn.commit()
    print(f"  watchlist {a.chat}: {a.symbols}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="suar")
    p.add_argument("--trigger", default="manual", choices=["manual", "cron"])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    b = sub.add_parser("bootstrap", help="sekali jalan, isi semua data")
    b.add_argument("--tickers", type=int, default=config.BACKFILL_TICKERS)
    b.add_argument("--close-days", type=int, default=45)
    b.set_defaults(fn=cmd_bootstrap)

    d = sub.add_parser("daily")
    d.add_argument("--date", default=None)
    d.add_argument("--send", action="store_true")
    d.set_defaults(fn=cmd_daily)

    w = sub.add_parser("weekly")
    w.add_argument("--send", action="store_true")
    w.set_defaults(fn=cmd_weekly)

    ba = sub.add_parser("bars", help="tarik volume harian untuk kandidat")
    ba.add_argument("--tickers", type=int, default=config.BACKFILL_TICKERS)
    ba.add_argument("--only", default=None, help="daftar ticker dipisah koma")
    ba.set_defaults(fn=cmd_bars)

    po = sub.add_parser("poll", help="cek suspensi baru, ringan")
    po.add_argument("--send", action="store_true")
    po.set_defaults(fn=cmd_poll)

    pa = sub.add_parser("parse", help="unduh & parse pengumuman BEI")
    pa.add_argument("--limit", type=int, default=40)
    pa.set_defaults(fn=cmd_parse)

    s = sub.add_parser("score", help="hitung ulang skor dari SQLite, tanpa API")
    s.add_argument("--date", default=None)
    s.add_argument("--send", action="store_true")
    s.set_defaults(fn=lambda a: cmd_score(a))

    sub.add_parser("validate").set_defaults(fn=cmd_validate)

    wa = sub.add_parser("watch")
    wa.add_argument("--chat", required=True)
    wa.add_argument("--symbols", required=True)
    wa.add_argument("--position", type=float, default=config.POSITION_DEFAULT)
    wa.set_defaults(fn=cmd_watch)

    a = p.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
