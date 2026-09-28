"""Konfigurasi terpusat. Semua ambang batas ada di sini, bukan tersebar di kode."""

import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("SUAR_DB", str(ROOT / "suar.db"))
SCHEMA_PATH = ROOT / "schema.sql"
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"

WIB = timezone(timedelta(hours=7))

# ---- API ----
SECTORS_BASE = "https://api.sectors.app/v2"
SECTORS_KEY = os.environ.get("SECTORS_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

PAGE_SIZE = 200
SLEEP_BETWEEN_CALLS = 1.2     # tanpa ini muncul 429
MAX_RETRY = 4

# ---- Ambang kriteria ----
# Angka free float 7,5% diturunkan dari data: 8 dari 37 emiten yang disuspensi
# karena V.1.1/V.1.2 berada di bawah angka ini. Lihat docs/VALIDATION.md.
FREE_FLOAT_MIN = 0.075

# Dorman: proporsi hari bursa dengan harga penutupan tidak berubah.
# Terkalibrasi terhadap volume asli, korelasi 0,998 (docs/VALIDATION.md).
FROZEN_RATIO_WARN = 0.50
FROZEN_STREAK_WARN = 10

# Likuiditas rendah: nilai transaksi harian median di bawah ambang ini.
LOW_VALUE_IDR = 5_000_000

# Telat lapor: kuartal dianggap telat kalau belum terbit N hari setelah tutup buku.
LATE_DAYS = 120

# Jam keluar
POSITION_DEFAULT = 100_000_000      # Rp100 juta
PARTICIPATION = 0.10                # maksimum 10% volume harian

# Jendela analisis
WINDOW_DAYS = 90
BACKFILL_TICKERS = 67               # kandidat berdasarkan market cap terkecil

# Ambang alert
ALERT_MIN_CRITERIA = 2
