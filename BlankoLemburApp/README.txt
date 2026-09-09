BLANKO LEMBUR OTOMATIS
======================

Aplikasi desktop lokal untuk mencatat lembur dan membuat satu file Word
siap print tanpa mengedit blanko secara manual.

CARA MENJALANKAN
----------------
1. Salin hanya "Blanko Lembur Otomatis.exe" ke PC Windows 10/11 64-bit.
2. Klik dua kali file EXE tersebut.

Tidak perlu menginstal Python, paket tambahan, atau Microsoft Word untuk
menjalankan aplikasi dan menghasilkan dokumen. Tidak memerlukan internet.
Template Word, Python, dan Tkinter sudah berada di dalam satu EXE.
Folder sumber BlankoLemburApp dan seluruh isinya tidak perlu ikut disalin.
Saat dibuka, komponen internal diekstrak otomatis ke folder sementara Windows
dan dibersihkan saat aplikasi ditutup normal.

Untuk membaca, mengedit, atau mencetak hasil DOCX, gunakan aplikasi pembaca
Word yang tersedia di perangkat.

ALUR PENGGUNAAN
---------------
1. Buka tab Profil, lengkapi Nama, NIP, Unit Kerja, Bulan, dan Tahun.
2. Buka tab Pejabat, lengkapi nama Manajer dan Asisten Manajer.
   NIP keduanya opsional dan boleh kosong untuk pejabat non-ASN.
   Nilai awal bidang/unit jabatan mengikuti Unit Kerja dari Profil, tetapi
   kolomnya selalu bisa langsung diganti manual, lalu simpan.
   Contoh: Manajer Pelayanan dan Asisten Manajer Keperawatan.
3. Buka tab Blanko Lembur.
4. Pilih tanggal dan isi jam mulai serta jam selesai.
5. Isi Pekerjaan, Kuantitas, dan Keterangan, lalu klik
   "Tambah ke daftar". Maksimal tujuh pekerjaan per tanggal.
6. Klik "Simpan blanko".
7. Klik "Rekap Harian" untuk preview blanko per tanggal.
   Periksa preview, klik "Simpan sebagai Word", lalu pilih lokasi file.
8. Setelah data harian selesai disimpan, klik "Rekap Bulanan".
   Pilih lokasi file Word rekap bulanan yang terpisah dari blanko harian.
   Rekap hanya menggunakan data tersimpan pada bulan aktif di Profil.

INPUT JAM DAN KUANTITAS
----------------------
- Jam dapat diketik tanpa tanda titik dua: 2000 otomatis menjadi 20:00,
  1630 menjadi 16:30, dan 700 menjadi 07:00.
- Jam mulai otomatis mengikuti hari yang dipilih: Senin-Kamis 16:00,
  Jumat 16:30, serta Sabtu-Minggu 07:00. Nilainya tetap bisa diubah.
- Kuantitas hanya menerima angka.

DATA CSV
--------
Versi EXE menyimpan data otomatis di:
    %LOCALAPPDATA%\BlankoLemburOtomatis

Folder ini berisi:

- profil.csv          : Nama, NIP, Unit Kerja, dan bulan aktif.
- pejabat.csv         : Nama/NIP dan pilihan jabatan Manajer/Asmen.
- lembur_records.csv  : Seluruh tanggal, jam, pekerjaan, kuantitas,
                        dan keterangan.

File memakai UTF-8 dan pemisah titik koma agar mudah dibuka di Excel.
Untuk membuat cadangan, cukup salin ketiga file CSV tersebut.
Data tersimpan per akun Windows dan tetap ada setelah EXE ditutup/dipindahkan.
Menyalin EXE ke PC lain tidak membawa profil atau riwayat yang sudah diisi.
Data CSV dari versi Python tetap ada di folder "data" sumber.
Jika ingin memindahkan data lama, tutup aplikasi lalu salin ketiga CSV ke
folder penyimpanan EXE di atas (cadangkan data tujuan sebelum menggantinya).
Tidak perlu menaruh CSV atau template di sebelah EXE.

CATATAN WORD
------------
- Rekap harian: satu tanggal dibuat menjadi satu halaman.
- Semua halaman digabung dalam satu file Word dan dipisahkan page break.
- Format berasal dari template yang sudah tertanam di dalam EXE.
- Kolom Hasil Output Ada/Tidak tetap kosong untuk dicentang manual.
- Kolom Keterangan diisi dari aplikasi.
- NIP pejabat yang kosong tidak menampilkan tulisan NIP pada Word.
- Rekap bulanan mengikuti template REKAP LEMBUR BULAN yang tertanam.
  Satu baris untuk setiap pekerjaan; tanggal dan jam diulang bila sama.
  Baris diurutkan per tanggal, lalu urutan pekerjaan harian.
  Sorotan kuning template dibersihkan dari dokumen hasil.
  Nama jabatan otomatis/manual berlaku pada harian dan bulanan.

Jika file Word gagal disimpan, pastikan file tujuan tidak sedang dibuka
di Microsoft Word, lalu coba lagi.

INFO APLIKASI DAN PEMBARUAN
--------------------------
Versi aplikasi: 1.1.1. Dibuat oleh NAM untuk pegawai RSUP Dr M Djamil.
Tab Info aplikasi memuat tombol "Cek untuk Update".
Tombol memeriksa rilis resmi di repository GitHub Blanko-Lembur. Jika belum
ada rilis baru, aplikasi menjelaskan bahwa versi saat ini sudah terbaru.
Jika versi baru tersedia, aplikasi mengunduh pembaruan yang terverifikasi dan
memasangnya setelah pengguna menyimpan pekerjaan serta menyetujui penutupan.
Data CSV tetap disimpan lokal.
Internet hanya dibutuhkan saat memeriksa atau mengunduh pembaruan.
Panduan penerbitan untuk pengembang tersedia di UPDATE_RELEASES.md.

UNTUK PENGEMBANG
----------------
Kode sumber tetap disimpan agar aplikasi dapat diperbarui.
Versi sumber: Python 3.10+ dengan Tkinter, jalankan blanko_lembur.py atau BAT.
Versi sumber membutuhkan blanko_template.docx dan REKAP LEMBUR BULAN.docx,
serta menggunakan data/.
Versi sumber membutuhkan cryptography untuk verifikasi pembaruan.
Build ulang EXE pada Windows dengan Python 64-bit dan Tkinter:
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Python "C:\lokasi\python.exe"
Kebutuhan build dipasang hanya pada subfolder .build proyek.
Output satu EXE berada di folder induk BlankoLemburApp.
Panduan pengemasan: https://pyinstaller.org/en/stable/operating-mode.html
