"""Ekstraksi pengumuman BEI.

Pembagian kerja yang jujur:

  * ROSTER emiten  -> regex. Tabel pengumuman BEI formatnya teratur
    (No. | Kode | Nama Perusahaan | Status), jadi regex lebih akurat
    dan gratis dibanding LLM. Ini melengkapi ground truth yang tidak
    lengkap di endpoint /suspensions/ (11 dari 38 pada satu batch).

  * KRITERIA DALAM PROSA -> LLM. Opini going concern, PKPU, pergantian
    auditor, penundaan RUPS hidup sebagai kalimat bahasa Indonesia baku,
    bukan sebagai field. Pencocokan kata kunci gagal di register seformal
    itu. Tanpa lapis ini, kriteria tersebut hilang sepenuhnya dari sistem.

Kalau ANTHROPIC_API_KEY tidak diset, bagian LLM dilewati dan sistem tetap
jalan dengan kriteria numerik saja.
"""

import json
import re

import requests

from . import config
from .db import now, sym, today

PROSE_CRITERIA = [
    "GOING_CONCERN",     # keraguan atas kelangsungan usaha
    "PKPU_PAILIT",       # PKPU / kepailitan
    "GANTI_AUDITOR",     # pergantian akuntan publik
    "RUPS_TERTUNDA",     # penundaan RUPS
    "EKUITAS_NEGATIF",   # disebut eksplisit di pengumuman
]

PROMPT = """Kamu membaca pengumuman resmi Bursa Efek Indonesia (BEI).

Tugas: tentukan kriteria pengawasan mana yang DISEBUTKAN SECARA EKSPLISIT
dalam teks. Jangan menyimpulkan, jangan menebak. Kalau teks tidak
menyebutkannya, nilainya 0.

Kriteria yang dicari:
- GOING_CONCERN: keraguan/ketidakpastian atas kelangsungan usaha
- PKPU_PAILIT: PKPU, penundaan kewajiban pembayaran utang, atau kepailitan
- GANTI_AUDITOR: pergantian akuntan publik / kantor akuntan
- RUPS_TERTUNDA: penundaan atau pembatalan RUPS
- EKUITAS_NEGATIF: ekuitas negatif disebut eksplisit

Balas HANYA JSON dengan bentuk:
{"flags": {"GOING_CONCERN": 0, "PKPU_PAILIT": 0, "GANTI_AUDITOR": 0,
"RUPS_TERTUNDA": 0, "EKUITAS_NEGATIF": 0}, "kutipan": "potongan kalimat pendukung atau kosong"}

Teks pengumuman:
---
%s
---"""

# Baris tabel IDX: "1. ALMI PT Alumindo Light Metal Industry Tbk Suspensi di ..."
ROW_RE = re.compile(
    r"^\s*(\d{1,3})[.)]?\s+([A-Z]{4})\s+(.+?)\s+(Suspensi[^\n]*)$",
    re.MULTILINE)


# ------------------------------------------------------------------ ambil

def fetch_pdf_text(url: str) -> str | None:
    """Unduh PDF pengumuman dan ambil teksnya."""
    try:
        import pdfplumber
    except ImportError:
        print("  [!] pdfplumber belum terpasang: pip install pdfplumber")
        return None
    import io
    try:
        r = requests.get(url, timeout=60,
                         headers={"User-Agent": "Mozilla/5.0 (Suar research bot)"})
        if r.status_code != 200:
            print(f"  [{r.status_code}] {url[:80]}")
            return None
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:                          # noqa: BLE001
        print(f"  [pdf] {e}")
        return None


def parse_roster(text: str) -> list[dict]:
    """Regex tabel emiten. Deterministik, tidak perlu LLM."""
    out = []
    for _, kode, nama, status in ROW_RE.findall(text or ""):
        out.append({"symbol": kode.strip(),
                    "company_name": nama.strip(),
                    "status": status.strip()})
    return out


# ------------------------------------------------------------------ LLM

def extract_prose_flags(text: str) -> dict | None:
    """Kriteria yang hanya hidup dalam prosa. Butuh ANTHROPIC_API_KEY."""
    if not config.ANTHROPIC_KEY:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": config.ANTHROPIC_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-5",
                  "max_tokens": 400,
                  "messages": [{"role": "user",
                                "content": PROMPT % (text or "")[:12000]}]},
            timeout=90)
        if r.status_code != 200:
            print(f"  [llm {r.status_code}] {r.text[:150]}")
            return None
        body = r.json()["content"][0]["text"]
        m = re.search(r"\{.*\}", body, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:                          # noqa: BLE001
        print(f"  [llm] {e}")
        return None


# ------------------------------------------------------------------ job

def job_parse_announcements(conn, run, limit: int = 40,
                            categories=("FREE_FLOAT", "LAPKEU", "GOING_CONCERN",
                                        "PPK_1TH", "BIAYA", "LAIN")):
    """Unduh + parse pengumuman untuk kategori non-harga. Tidak pakai kredit Sectors."""
    qs = ",".join("?" * len(categories))
    urls = [r[0] for r in conn.execute(
        f"SELECT DISTINCT pdf_url FROM suspension "
        f"WHERE pdf_url IS NOT NULL AND category IN ({qs}) "
        f"ORDER BY suspension_date DESC LIMIT ?", (*categories, limit))]
    print(f"  {len(urls)} pengumuman")

    asof = today()
    for i, u in enumerate(urls, 1):
        done = conn.execute("SELECT parsed_at FROM announcement WHERE pdf_url=?",
                            (u,)).fetchone()
        if done and done[0]:
            continue
        text = fetch_pdf_text(u)
        if not text:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO announcement(pdf_url,fetched_at,parsed_at,"
            "n_chars,raw_text) VALUES (?,?,?,?,?)",
            (u, now(), now(), len(text), text[:200000]))

        roster = parse_roster(text)
        for c in roster:
            conn.execute(
                "INSERT OR REPLACE INTO announcement_company"
                "(pdf_url,symbol,company_name,status) VALUES (?,?,?,?)",
                (u, sym(c["symbol"]), c["company_name"], c["status"]))
            run.rows += 1

        flags = extract_prose_flags(text)
        if flags and roster:
            for crit, val in (flags.get("flags") or {}).items():
                if not val:
                    continue
                for c in roster:
                    conn.execute(
                        "INSERT OR REPLACE INTO criterion_flag"
                        "(symbol,asof,criterion,value,source,confidence) "
                        "VALUES (?,?,?,1,?,?)",
                        (sym(c["symbol"]), asof, crit, u, 0.8))
                    run.rows += 1

        conn.commit()
        print(f"  {i}/{len(urls)} {len(roster)} emiten"
              f"{' + flag prosa' if flags else ''}")
