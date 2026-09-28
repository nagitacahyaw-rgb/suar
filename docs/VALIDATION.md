# Validasi berjenjang

`python -m suar validate` → `out/validation.json`

Urutannya dari terkendali ke operasional. Lapis yang lebih awal harus lulus
sebelum lapis berikutnya bermakna.

## Lapis 1 — uji unit rumus

Rumus jam keluar diuji terhadap kasus yang jawabannya bisa dihitung tangan:

| Nilai transaksi harian | Posisi | Partisipasi | Harapan |
|---|---|---|---|
| Rp10 juta | Rp100 juta | 10% | 100 hari |
| Rp100 juta | Rp100 juta | 10% | 10 hari |
| Rp73.842.300 | Rp100 juta | 10% | 13,5 hari |
| Rp0 | Rp100 juta | 10% | tidak ada pintu keluar |

Baris ketiga memakai nilai transaksi ACST yang sebenarnya.

## Lapis 2 — kalibrasi proksi dormansi

Membandingkan proporsi hari harga beku terhadap volume asli, untuk emiten yang
punya keduanya di database.

Pengukuran awal pada 15 emiten campuran (9 beku, 6 likuid):

| | hari beku / hari | volume nol |
|---|---|---|
| FASW, SMCB, PLIN, ABBA, BATA, CMPP, ARTI, MTSM, KBRI | 1,000 | 20 dari 20 |
| ACST | 0,158 | 0 |
| ANTM | 0,105 | 0 |
| BBCA, TLKM, ASII, BBRI | 0,053 | 0 |

Korelasi 0,998. Presisi dan recall pada ambang 0,50 dilaporkan ulang setiap kali
validasi dijalankan.

## Lapis 3 — rekonstruksi status berjalan

Pertanyaannya: apakah sistem menandai emiten yang **memang sudah** disuspensi?

Ini uji reproduksi, bukan prediksi. Lapis ini lebih penting daripada lapis 4 —
kalau sistem tidak bisa mereproduksi status hari ini dari data mentah, klaim apa
pun tentang peringatan dini tidak punya dasar.

Keluaran: jumlah suspensi non-harga 12 bulan terakhir, berapa yang tertangkap,
berapa yang lolos, dan daftar contoh yang lolos.

## Lapis 4 — ground truth eksternal

38 emiten dari Peng-S-00027/BEI.PLP/10-2025 (31 Oktober 2025), ditranskrip dari
PDF publik ke `data/ground_truth_freefloat_2025-10-31.csv`.

Recall pada lapis ini **tidak akan** mendekati 1, dan itu bukan bug: kriteria
V.1.2 tidak tersedia di API. Angka ini dilaporkan apa adanya beserta
penjelasannya.

## Yang tidak diklaim

* Tidak ada angka "akurasi" tunggal.
* Tidak ada klaim lead time dari backtest lintas waktu, karena snapshot
  historis free float dan fundamental tidak tersedia. Riwayat itu baru mulai
  terbangun sejak sistem ini dijalankan.
* Sampel kecil: 125 event non-harga pada 52 emiten unik.
