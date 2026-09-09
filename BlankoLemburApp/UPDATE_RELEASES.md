# Pembaruan aplikasi melalui internet

Versi 1.0 sudah menyediakan tab **Info aplikasi** dan tombol **Cek untuk Update**.
Sumber pembaruan diarahkan ke repository publik `1310mythol-code/Blanko-Lembur`.
Jika repository belum mempunyai Release, tombol menjelaskan bahwa belum ada update.
Tidak ada data pegawai atau lembur yang dikirim ke layanan pembaruan.

## Konfigurasi yang digunakan

1. Repository harus tetap publik agar pengguna dapat mengunduh tanpa akun.
   Jangan menaruh token GitHub atau kata sandi di dalam EXE.
2. Kunci privat pengembang disimpan di luar repository dan dilindungi akun Windows:

   ```powershell
   %LOCALAPPDATA%\BlankoLemburOtomatisDeveloper\update-signing-key.dpapi
   ```

   Berkas tersebut hanya dapat dibuka oleh akun Windows yang membuatnya. Cadangkan profil
   Windows pengembang. Kehilangan kunci membuat EXE lama tidak dapat menerima rilis baru.
   Kunci privat tidak boleh masuk repository, folder distribusi, atau paket EXE.
3. `UPDATE_PUBLIC_KEY` dan `UPDATE_MANIFEST_URL` sudah ditanam di `app_metadata.py`:

   ```text
   https://github.com/1310mythol-code/Blanko-Lembur/releases/latest/download/update.json
   ```

4. Bagikan EXE 1.0 yang sudah berisi alamat dan kunci publik. Rilis selanjutnya dapat
   diperiksa dan dipasang melalui tombol di aplikasi.

## Menyiapkan rilis berikutnya

1. Ubah fitur dan tingkatkan `APP_VERSION` dalam `app_metadata.py`, misalnya dari `1.0`
   menjadi `1.1`. Gunakan 2–4 bagian angka, tanpa awalan `v` pada `APP_VERSION`.
2. Buat EXE satu berkas dan uji penggunaan, pembuatan Word, serta kompatibilitas data lama.
3. Siapkan tag GitHub seperti `v1.1` dan nama aset unduhan. URL EXE harus HTTPS dan menunjuk
   versi tertentu, bukan tautan `latest` yang dapat berpindah di tengah pengunduhan.
4. Buat catatan perubahan UTF-8, kemudian tandatangani EXE final:

   ```powershell
   & 'JALUR_PYTHON_BUILD' packaging\publish_update.py sign `
       --private-key "$env:LOCALAPPDATA\BlankoLemburOtomatisDeveloper\update-signing-key.dpapi" `
       --exe '..\Blanko Lembur Otomatis.exe' `
       --version '1.1' `
       --url 'https://github.com/1310mythol-code/Blanko-Lembur/releases/download/v1.1/BlankoLemburOtomatis.exe' `
       --notes-file 'catatan-rilis.txt' `
       --output 'update.json'
   ```

5. Unggah EXE dengan nama yang sama seperti URL, dan `update.json`, sebagai aset rilis
   GitHub yang sama. Publikasikan setelah kedua aset siap. Skrip penandatanganan tidak
   mengunggah atau memublikasikan apa pun.
6. Dari EXE versi sebelumnya, uji **Cek untuk Update**, catatan versi, konfirmasi pengguna,
   unduhan, penggantian aplikasi, pembukaan kembali, dan data lama.

Nomor versi pada manifest harus cocok dengan versi EXE yang dibuat. Jangan mengubah EXE
setelah manifest ditandatangani. Jika mengubah berkas, buat tanda tangan baru.

## Cara pemasangan dan batasan

Manifest memakai tanda tangan Ed25519. Aplikasi memeriksa tanda tangan menggunakan kunci
publik yang tertanam, kemudian memeriksa ukuran dan SHA-256 EXE hasil unduhan. Semua
koneksi dan pengalihan wajib HTTPS. Unduhan dibatasi 200 MiB dan waktu jaringan dibatasi.
Kunci ini terpisah dari sertifikat Windows Authenticode; fitur ini bukan penandatanganan
Windows SmartScreen.

Pengguna cukup membawa satu EXE. Saat memperbarui, aplikasi membuat berkas sementara di
`%LOCALAPPDATA%\BlankoLemburOtomatis\updates`. Program pembantu adalah salinan EXE lama
yang terpercaya, memeriksa ulang rilis, menunggu aplikasi ditutup, menyalin EXE baru ke
volume tujuan, lalu mengganti EXE secara atomik dan membukanya kembali. Folder aplikasi
harus dapat ditulis pengguna dan semua jendela aplikasi yang memakai EXE tersebut harus
ditutup. Tidak ada proses pengguna yang dimatikan secara paksa.

Data CSV tetap berada di lokasi penyimpanan pengguna dan tidak dihapus oleh updater.
Jika penggantian gagal, EXE lama dipertahankan. Jika EXE baru gagal dimulai, helper mencoba
mengembalikan EXE lama; jika pemulihan terhalang izin, lokasi cadangannya ditampilkan.
Berkas helper yang masih terkunci dapat dibersihkan saat aplikasi dibuka lagi. Updater
tidak dapat mendeteksi semua kegagalan fitur setelah proses versi baru berhasil dimulai;
pengujian kompatibilitas sebelum rilis tetap diperlukan.

Dokumentasi teknis:
[Ed25519 pada cryptography](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/),
[GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases),
[lingkungan proses PyInstaller](https://pyinstaller.org/en/stable/advanced-topics.html#environment-variables-used-by-frozen-applications).
