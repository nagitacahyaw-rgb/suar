"""Klien Sectors API: rate-limited, mencatat setiap panggilan ke api_call.

Aturan billing Sectors v2 (dari dokumentasi resmi):
  2xx dan 404 -> memotong kredit sesuai biaya endpoint
  400/401/403/429/5xx -> gratis
Klien ini mencatatnya persis begitu supaya anggaran kredit bisa diaudit.
"""

import json
import time

import requests

from . import config
from .db import now


class SectorsClient:
    def __init__(self, conn, api_key: str | None = None):
        self.conn = conn
        self.key = api_key or config.SECTORS_KEY
        if not self.key:
            raise RuntimeError("SECTORS_API_KEY belum diset")
        self.headers = {"Authorization": self.key}
        self.run_id = None
        self.credits = 0

    # ---------------------------------------------------------------- core
    def get(self, path: str, params: dict | None = None, cost: int = 1):
        params = params or {}
        for attempt in range(config.MAX_RETRY):
            t0 = time.time()
            try:
                r = requests.get(f"{config.SECTORS_BASE}{path}",
                                 headers=self.headers, params=params, timeout=45)
            except requests.RequestException as e:
                print(f"  [net] {e}")
                time.sleep(3 * (attempt + 1))
                continue

            billed = cost if (r.status_code < 300 or r.status_code == 404) else 0
            self.credits += billed
            self.conn.execute(
                "INSERT INTO api_call(run_id,endpoint,params,status_code,credits,"
                "latency_ms,called_at) VALUES (?,?,?,?,?,?,?)",
                (self.run_id, path, json.dumps(params, sort_keys=True),
                 r.status_code, billed, int((time.time() - t0) * 1000), now()),
            )

            if r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  [429] tunggu {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 300:
                print(f"  [{r.status_code}] {path} {r.text[:150]}")
                return None

            time.sleep(config.SLEEP_BETWEEN_CALLS)
            return r.json()

        print(f"  [gagal] {path} setelah {config.MAX_RETRY} percobaan")
        return None

    def paginate(self, path: str, params: dict, cost: int = 1, max_pages: int = 40):
        out, offset, pages = [], 0, 0
        while pages < max_pages:
            d = self.get(path, dict(params, limit=config.PAGE_SIZE, offset=offset), cost)
            if not d:
                break
            out += d.get("results", [])
            pg = d.get("pagination", {})
            if not pg.get("has_next"):
                break
            offset = pg.get("next_offset")
            pages += 1
        return out

    # ------------------------------------------------------------ endpoints
    def companies(self, where: str, order_by: str | None = None, values: bool = True):
        p = {"where": where, "include_query_values": "true" if values else "false"}
        if order_by:
            p["order_by"] = order_by
        return self.paginate("/companies/", p)

    def close_on(self, on: str):
        return self.paginate("/close/", {"date": on})

    def suspensions(self):
        return self.paginate("/suspensions/", {})

    def daily(self, ticker: str, start: str, end: str):
        d = self.get(f"/daily/{ticker}/", {"start": start, "end": end})
        if d is None:
            return []
        return d if isinstance(d, list) else d.get("results", d.get("data", []))
