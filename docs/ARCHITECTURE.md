# Arsitektur

## Aturan rumah

**Ingestion tidak pernah menghitung. Rules engine tidak pernah memanggil API.**

Konsekuensinya: perhitungan live dan backtest historis melewati fungsi yang sama
persis. Tidak ada jalur kode terpisah yang bisa membuat angka validasi terlihat
lebih baik daripada yang sebenarnya.

Satu pengecualian yang disengaja: `ingest.categorize()` mengklasifikasi alasan
suspensi saat menulis, karena kategori itu dipakai hampir semua query dan lebih
murah disimpan sekali.

## Lapisan

```
Sectors API v2
      │
      ▼
 client.py        rate limit, retry 429, catat setiap panggilan ke api_call
      │
      ▼
 ingest.py        hanya INSERT/REPLACE
      │
      ▼
   SQLite (suar.db)
      │
      ├── rules.py        skor kriteria + jam keluar
      ├── announcements.py regex roster + LLM prosa
      ├── report.py       papan risiko HTML
      ├── notify.py       alert Telegram
      └── backtest.py     validasi 4 lapis
```

## Pola `asof`

Tabel fakta pasar berkunci `(symbol, date)` — tanggal peristiwa.
Tabel snapshot berkunci `(symbol, asof)` — **tanggal kita mengamati**.

Ini bukan detail gaya. API Sectors menyediakan `free_float` dan
`total_equity_mrq` hanya sebagai nilai terkini, tanpa riwayat. Dengan kolom
`asof`, sistem merekam apa yang diketahui pada tanggal berapa, dan dalam
beberapa minggu memiliki deret waktu yang tidak bisa diambil ulang dari API
mana pun.

Efek sampingnya: `rules.score_all(conn, asof)` bisa dijalankan untuk tanggal
lampau memakai data yang tersedia pada tanggal itu.

## Anggaran kredit

Aturan billing Sectors v2: 2xx dan 404 memotong kredit, 400/401/403/429/5xx
gratis. `client.py` mencatatnya persis begitu di tabel `api_call`.

| Job | Frekuensi | Kredit |
|---|---|---|
| bootstrap | sekali | ~200 |
| poll | 5× hari bursa | ~3 |
| daily | hari bursa | ~8 |
| weekly | Senin | ~35 |
| score | kapan saja | 0 |

Arsitektur dua tingkat dipilih karena kendala nyata: `/v2/close/` memberi 962
emiten dalam ~5 kredit tapi **tanpa volume**, sedangkan `/v2/daily/{ticker}/`
memberi volume tapi 1 kredit per emiten. Karena itu:

* **Tingkat 1** (seluruh pasar, harian) — harga penutupan, dormansi dari harga beku
* **Tingkat 2** (kandidat, mingguan) — volume asli, nilai transaksi, jam keluar

Tingkat 2 dijalankan mingguan, bukan harian, karena jendela kriteria likuiditas
memang 6 bulan. Menghitung ulang tiap hari akan jadi teater.

## Jejak eksekusi

`run_log` satu baris per job (mulai, selesai, status, baris ditulis, kredit).
`api_call` satu baris per panggilan HTTP.

Dua view siap pakai:

```sql
SELECT * FROM v_run_summary;    -- ringkasan eksekusi per job
SELECT * FROM v_credit_usage;   -- kredit per hari
SELECT * FROM v_papan_risiko;   -- papan risiko terkini
```
