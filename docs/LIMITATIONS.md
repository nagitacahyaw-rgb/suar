# Batasan

Ditulis sendiri, bukan ditemukan juri. Setiap batasan di bawah ini berasal dari
pengujian terhadap API sebelum kode produk ditulis.

## 1. Ini bukan prediksi harga

Suar memprediksi **tindakan regulator**, bukan arah harga. Emiten yang memenuhi
banyak kriteria bisa saja harganya naik, dan sebaliknya. Klaim sistem terbatas
pada: kriteria mana yang terpenuhi, dan berapa lama posisi masih bisa dilepas.

## 2. Kriteria jumlah pemegang saham tidak tersedia

Peraturan I-A ketentuan V.1.1 **dan/atau** V.1.2 adalah dua syarat terpisah.
Sectors menyediakan `free_float` (persentase), tidak menyediakan jumlah
pemegang saham.

Akibatnya terukur: dari 37 emiten dalam pengumuman 31 Oktober 2025 yang datanya
bisa dicocokkan, hanya **8** yang free float-nya di bawah 7,5%. Sisanya
kemungkinan melanggar V.1.2 — dan itu tidak terlihat sama sekali dari data yang
ada.

Sebaran free float ke-37 emiten itu: minimum 0,22%, median 27,5%, maksimum
94,2%. Distribusinya tumpang tindih dengan emiten yang tidak disuspensi
(median 23,1%). **Free float saja tidak memisahkan keduanya.**

## 3. Riwayat suspensi di API tidak lengkap

Endpoint `/v2/suspensions/` memuat 592 record. Untuk batch 31 Oktober 2025 yang
berisi 38 emiten, hanya **11** yang tercatat.

Karena itu ground truth dilengkapi dari pengumuman PDF, dan angka recall apa pun
yang dihitung dari endpoint saja akan bias ke atas.

## 4. Free float tidak punya riwayat

`/v2/free-float/` hanya menerima filter sektor, tidak ada parameter tanggal.
Nilai yang tersedia adalah nilai hari ini.

Konsekuensinya: free float **tidak bisa dipakai untuk backtest**. Emiten dengan
free float tinggi yang disuspensi tahun lalu mungkin sudah memperbaiki
float-nya setelah sanksi. Sistem ini hanya memakai free float secara maju, dan
mulai membangun riwayatnya sendiri lewat `snapshot_fundamental.asof`.

## 5. Tanggal pelaporan tidak tersedia

`/v2/companies/quarterly-financial-dates/` mengembalikan **tanggal tutup buku**
(2026-06-30 untuk Q2), bukan tanggal emiten melapor. Diverifikasi: FASW, SMCB,
dan BBCA punya daftar tanggal yang identik sampai ke hari.

Karena itu sensor keterlambatan tidak dibangun dari selisih tanggal, melainkan
dari **ketiadaan data**: kuartal yang belum terbit lebih dari 120 hari setelah
tutup buku. Pendekatan ini tidak bisa mengukur keterlambatan ringan.

## 6. Data kuartalan lagging

Emiten yang memburuk cepat bisa disuspensi sebelum laporan keuangannya terbit.
Untuk kasus seperti itu, Suar tidak memberi peringatan lebih dulu.

## 7. Proksi dormansi adalah kesetaraan mekanis

Harga penutupan yang tidak berubah memang berarti tidak ada transaksi — itu
tautologi, bukan penemuan. Korelasi 0,998 terhadap volume nol mengonfirmasi
hal yang sudah pasti secara definisi.

Nilainya murni ekonomi: memantau 962 emiten dengan ~5 kredit per tanggal alih-alih
962. Jangan membacanya sebagai temuan ilmiah.

## 8. Sampel event kecil

Dari 592 record suspensi, 467 adalah cooling-down dan lonjakan harga — bukan
tekanan regulatori, dan bukan yang diprediksi Suar. Yang relevan tersisa
**125 event pada 52 emiten unik**.

Karena itu keluaran validasi melaporkan median dan sebaran, bukan angka akurasi
tunggal.

## 9. Ambang batas belum final

Ambang 7,5% free float, 50% hari beku, dan Rp5 juta nilai transaksi diturunkan
dari data dan dari kriteria Papan Pemantauan Khusus fase awal. Peraturan I-X
telah direvisi; ambang resmi yang berlaku perlu diverifikasi ulang terhadap
dokumen BEI terkini sebelum sistem ini dipakai sungguhan.
