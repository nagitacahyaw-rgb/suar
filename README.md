# Suar

**Hitung mundur ke kriteria suspensi BEI, untuk investor ritel IDX.**

> Untuk investor ritel IDX, Suar menghitung seberapa dekat setiap emiten dengan
> kriteria suspensi BEI dan berapa lama posisi masih bisa dilikuidasi — supaya
> yang memegang tahu batas waktunya, dan yang akan membeli tahu apa yang dibelinya.

Sectors Hackathon 2026 · Track 2 — Automation & Workflows
Sumber data inti: **Sectors REST API v2**

---

## Masalah

Investor saham Indonesia menembus 10 juta SID, 54% di bawah 30 tahun, dan ritel
kini menyumbang 51,1% nilai transaksi bursa. Kerugian terbesar mereka bukan
harga turun, melainkan **saham berhenti bisa dijual**.

31 Oktober 2025, satu pengumuman BEI (Peng-S-00027/BEI.PLP/10-2025) menyuspensi
**38 emiten** sekaligus — termasuk Plaza Indonesia Realty, Solusi Bangun
Indonesia, Trikomsel, Fajar Surya Wisesa.

Kriteria yang mereka langgar dipublikasikan dan mekanis. Tapi BEI mengevaluasi
**secara berkala**, dan mengumumkan setelah keputusan dibuat. Di antara
"kriteria terpenuhi" dan "pengumuman terbit" ada jeda berminggu-minggu di mana
pemegang saham masih bisa keluar tapi tidak tahu harus keluar.

Informasinya sudah publik. Yang tidak ada adalah yang menghitungnya lebih dulu.

## Dua emiten, satu pertanyaan

| | FASW | ACST |
|---|---|---|
| Kondisi | disuspensi free float | ekuitas negatif 2 tahun (−Rp604 miliar) |
| Harga | beku di Rp5.275 | bergerak |
| Volume 20 hari terakhir | **nol** | aktif |
| Transaksi harian median | Rp0 | Rp73,8 juta |
| Jam keluar posisi Rp100 juta | **tertutup** | ±14 hari bursa |

Suar menghitung jarak antara keduanya, untuk 962 emiten, setiap hari bursa.

---

## Cara kerja

```
Sectors API v2
      │
  INGESTION ──────────► SQLite (suar.db) ──────┬──► RULES ENGINE
  (hanya menulis)        · fakta pasar         │    (hanya membaca)
                         · snapshot ber-asof   │
                         · ground truth        ├──► PAPAN RISIKO (HTML)
                         · jejak eksekusi      ├──► ALERT TELEGRAM
                                               └──► VALIDASI BERJENJANG
```

Aturan rumahnya satu kalimat: **ingestion tidak pernah menghitung, rules engine
tidak pernah memanggil API.** Karena itu perhitungan live dan backtest historis
melewati fungsi yang sama persis — angka validasi tidak bisa "curang" lewat
jalur kode yang berbeda.

### Kenapa SQLite, bukan sekadar cache

1. **Hemat kredit** — tanggal yang sudah ada tidak pernah ditarik ulang.
2. **Membangun riwayat yang API-nya tidak punya.** `free_float` dan
   `total_equity_mrq` hanya tersedia sebagai nilai terkini. Dengan kolom `asof`
   di setiap snapshot, sistem ini merekam *apa yang diketahui pada tanggal
   berapa* — deret waktu yang tidak bisa diambil ulang dari API mana pun.
3. **Jejak yang bisa diaudit** — `run_log` dan `api_call` mencatat setiap
   eksekusi dan setiap kredit yang terpakai.

### Kriteria yang dihitung

| Kode | Dasar | Sumber data |
|---|---|---|
| `EKUITAS_NEGATIF` | ekuitas < 0 | `total_equity_mrq` |
| `FREE_FLOAT_RENDAH` | free float < 7,5% | `free_float` |
| `BELUM_LAPOR` | kuartal belum terbit > 120 hari setelah tutup buku | ketiadaan `total_assets_q[Q]` |
| `DORMAN` | harga tidak bergerak ≥ 50% hari bursa | `close_daily` |
| `LIKUIDITAS_RENDAH` | nilai transaksi harian median < Rp5 juta | `daily_bar` |
| prosa | going concern, PKPU, ganti auditor | pengumuman BEI + LLM |

### Jam keluar

```
hari = posisi / (partisipasi × nilai transaksi harian median)
```

Partisipasi dibatasi 10% volume harian; di atas itu, penjualannya sendiri yang
menggerakkan harga. Kalau nilai transaksi nol, tidak ada pintu keluar sama
sekali — sistem menulis "tertutup", bukan angka besar.

### Dua sensor yang datanya dibuang orang lain

**Harga penutupan yang tidak berubah.** Direkam untuk chart; yang dibuang adalah
*ketiadaan perubahannya*. Harga beku berarti tidak ada transaksi — terkalibrasi
terhadap volume asli dengan korelasi 0,998. Hasilnya: memantau likuiditas 962
emiten jadi ~190× lebih murah daripada menarik volume satu per satu.

**Ketiadaan data kuartalan.** Setiap pengguna API memperlakukan nilai kosong
sebagai data hilang yang dilewati. Padahal itu sinyalnya: 101 emiten belum punya
data Q4-2025 pada September 2026.

### Peran LLM

Pembagian kerjanya sengaja jujur:

* **Roster emiten dari pengumuman → regex.** Tabel BEI formatnya teratur, regex
  lebih akurat dan gratis. Ini melengkapi ground truth yang tidak lengkap di
  endpoint `/suspensions/` (11 dari 38 emiten pada batch Oktober 2025).
* **Kriteria dalam prosa → LLM.** Opini going concern, PKPU, pergantian auditor
  hidup sebagai kalimat bahasa Indonesia baku, bukan sebagai field. Cabut lapis
  ini dan kriteria tersebut hilang sepenuhnya dari sistem.

---

## Menjalankan

```bash
pip install -r requirements.txt
cp .env.example .env          # isi SECTORS_API_KEY
export $(grep -v '^#' .env | xargs)

python -m suar init           # buat database
python -m suar bootstrap      # sekali jalan, ~200 kredit
python -m suar validate       # lapis validasi
open out/index.html           # papan risiko
```

Operasi terjadwal:

```bash
python -m suar poll           # ~3 kredit, tiap 3 jam — cek suspensi baru
python -m suar daily          # ~8 kredit, sore hari bursa
python -m suar weekly         # ~35 kredit, Senin
python -m suar parse          # unduh & parse pengumuman BEI (tanpa kredit Sectors)
python -m suar score          # hitung ulang dari SQLite, 0 kredit
```

Watchlist dan notifikasi:

```bash
python -m suar watch --chat 12345678 --symbols ACST,BATA --position 100000000
python -m suar daily --send
```

Tanpa API key sekalipun, pipeline bisa diuji:

```bash
python scripts/selftest.py    # data sintetis, memeriksa seluruh jalur
```

### Otomasi

Tiga workflow berjalan tanpa intervensi manusia per siklus:

| Workflow | Jadwal (WIB) | Isi | Kredit |
|---|---|---|---|
| `poll.yml` | 08 / 11 / 14 / 17 / 20, hari kerja | cek pengumuman suspensi baru | ~3 |
| `daily.yml` | 17:00, hari kerja | sapuan harga + skor ulang + alert | ~8 |
| `weekly.yml` | Senin 08:30 | snapshot fundamental + presence kuartal + validasi | ~35 |

Setiap eksekusi tercatat di `run_log` dengan `trigger='cron'`, dan riwayatnya
terlihat publik di tab Actions lengkap dengan timestamp. Tidak ada satu pun
siklus yang butuh manusia menekan tombol.

`poll` ada karena BEI menerbitkan pengumuman di tengah hari, sementara pipeline
harian baru menangkapnya sore — bukan untuk memperbanyak log.

Secrets yang perlu diset: `SECTORS_API_KEY`, opsional `TELEGRAM_BOT_TOKEN`.

### Anggaran kredit

| Job | Frekuensi | Kredit |
|---|---|---|
| `bootstrap` | sekali | ~200 |
| `poll` | 5× hari bursa | ~3 |
| `daily` | hari bursa | ~8 |
| `weekly` | Senin | ~35 |
| `score` | kapan saja | 0 |

Pemakaian nyata bisa dilihat kapan saja:

```sql
SELECT * FROM v_credit_usage;
SELECT * FROM v_run_summary;
```

---

## Validasi

Empat lapis, dari terkendali ke operasional. Jalankan `python -m suar validate`;
hasilnya ditulis ke `out/validation.json`.

1. **Uji unit** rumus jam keluar terhadap kasus berjawaban diketahui.
2. **Kalibrasi** proksi dormansi terhadap volume asli.
3. **Rekonstruksi** — apakah sistem menandai emiten yang memang sudah
   disuspensi. *Lapis ini lebih penting daripada lapis 4:* kalau sistem tidak
   bisa mereproduksi status hari ini dari data mentah, ia tidak berhak bicara
   soal prediksi.
4. **Ground truth eksternal** — 38 emiten dari pengumuman resmi BEI
   (`data/ground_truth_freefloat_2025-10-31.csv`, ditranskrip dari PDF publik).

Rincian: [`docs/VALIDATION.md`](docs/VALIDATION.md)

## Batasan

Ditulis sendiri, bukan disembunyikan. Rincian:
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md)

* Bukan prediksi harga, melainkan prediksi **tindakan regulator**.
* Kriteria jumlah pemegang saham (I-A V.1.2) tidak tersedia di API, sehingga
  hanya 8 dari 37 suspensi free float bisa dijelaskan oleh data yang ada.
* Riwayat suspensi di API tidak lengkap (11 dari 38 pada satu batch).
* `free_float` tidak punya riwayat — hanya dipakai maju, tidak untuk backtest.
* Data kuartalan lagging; emiten yang jatuh mendadak lolos.
* Proksi dormansi adalah kesetaraan mekanis. Nilainya efisiensi biaya, bukan
  temuan ilmiah.
* Sampel event kecil (125 suspensi non-harga). Laporkan median dan sebaran,
  jangan klaim akurasi.

## Batas otoritas

Suar tidak menetapkan status apa pun. Yang berwenang menetapkan suspensi dan
Papan Pemantauan Khusus adalah **Bursa Efek Indonesia**. Sistem ini hanya
menghitung jarak setiap emiten ke kriteria yang BEI terbitkan sendiri, dan
mencantumkan rujukan peraturannya di setiap keluaran.

**Ini informasi, bukan rekomendasi investasi.** Sistem tidak pernah mengeluarkan
kata jual atau beli, dan tidak melakukan eksekusi transaksi apa pun.

## Struktur

```
schema.sql              16 tabel + 3 view
suar/
  config.py             semua ambang batas terpusat
  db.py                 koneksi + Run (jejak eksekusi)
  client.py             klien Sectors: rate limit + catatan kredit
  ingest.py             menulis ke SQLite, tidak menghitung
  rules.py              menghitung dari SQLite, tidak memanggil API
  announcements.py      regex roster + ekstraksi prosa via LLM
  report.py             papan risiko HTML
  notify.py             alert Telegram
  backtest.py           validasi 4 lapis
  cli.py                python -m suar <perintah>
data/                   ground truth dari pengumuman BEI
scripts/selftest.py     uji end-to-end tanpa API key
```

## Lisensi

MIT.
