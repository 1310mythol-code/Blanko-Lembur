# Struktur UI

Layout tampilan aktif dipisahkan per tab:

- `profile_tab.py` — tab Profil.
- `officials_tab.py` — tab Pejabat.
- `blanko_tab.py` — input blanko, daftar pekerjaan, dan rekap.
- `info_tab.py` — informasi aplikasi dan tombol update.
- `common.py` — warna dan konstanta visual bersama.

`blanko_lembur.py` tetap menjadi coordinator aplikasi: memuat data, validasi,
handler tombol, penyimpanan CSV, ekspor Word, dan updater. Fungsi `build()`
di setiap modul UI hanya membuat widget dan menghubungkan callback ke coordinator.

Untuk mengubah label, warna lokal, ukuran, atau susunan widget, edit file tab
yang sesuai. Untuk mengubah aturan data atau proses ekspor, edit `core.py`,
`recap.py`, atau handler di `blanko_lembur.py`.
