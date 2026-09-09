"""Layout for the Profil tab.

State and validation stay on the application object so this module is safe to
edit for visual changes only.
"""

import tkinter as tk
from tkinter import ttk

from core import MONTH_NAMES
from ui.common import COLORS


def build(app) -> None:
    tab = app.profile_tab
    tab.columnconfigure(0, weight=3)
    tab.columnconfigure(1, weight=2)
    tab.rowconfigure(1, weight=1)

    intro = app._section_intro(
        tab,
        "01",
        "Profil pegawai dan periode",
        "Isi sekali. Data ini otomatis dipakai pada semua blanko.",
    )
    intro.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))

    form_card = tk.Frame(tab, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
    form_card.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
    form = ttk.Frame(form_card, style="Card.TFrame", padding=20)
    form.pack(fill="both", expand=True)
    form.columnconfigure(0, weight=1)
    form.columnconfigure(1, weight=1)

    app.profile_name_var = tk.StringVar()
    app.profile_nip_var = tk.StringVar()
    app.profile_unit_var = tk.StringVar()
    app.profile_month_var = tk.StringVar()
    app.profile_year_var = tk.StringVar()

    app.profile_name_entry = app._labeled_entry(form, "Nama pegawai", app.profile_name_var, 0, 0, 2)
    app._labeled_entry(form, "NIP", app.profile_nip_var, 1, 0, 2)
    app._labeled_entry(form, "Unit kerja", app.profile_unit_var, 2, 0, 2)

    month_holder = ttk.Frame(form, style="Card.TFrame")
    month_holder.grid(row=3, column=0, sticky="ew", padx=7, pady=7)
    ttk.Label(month_holder, text="Bulan", style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
    app.profile_month_combo = ttk.Combobox(
        month_holder,
        textvariable=app.profile_month_var,
        values=MONTH_NAMES,
        state="readonly",
    )
    app.profile_month_combo.pack(fill="x")

    year_holder = ttk.Frame(form, style="Card.TFrame")
    year_holder.grid(row=3, column=1, sticky="ew", padx=7, pady=7)
    ttk.Label(year_holder, text="Tahun", style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
    ttk.Spinbox(year_holder, from_=2000, to=2100, textvariable=app.profile_year_var).pack(fill="x")

    app.profile_error = ttk.Label(form, text="", style="Error.TLabel")
    app.profile_error.grid(row=4, column=0, columnspan=2, sticky="w", padx=7, pady=(5, 0))
    ttk.Button(form, text="Simpan Profil", style="Primary.TButton", command=app._save_profile).grid(
        row=5, column=0, columnspan=2, sticky="e", padx=7, pady=(18, 4)
    )

    aside = tk.Frame(
        tab,
        bg=COLORS["surface_alt"],
        padx=24,
        pady=24,
        highlightbackground=COLORS["line"],
        highlightthickness=1,
    )
    aside.grid(row=1, column=1, sticky="nsew")
    tk.Label(aside, text="TERHUBUNG OTOMATIS", bg=COLORS["surface_alt"], fg=COLORS["blue"],
             font=("Segoe UI Semibold", 8)).pack(anchor="w")
    tk.Label(aside, text="Satu profil untuk\nsemua blanko", bg=COLORS["surface_alt"], fg=COLORS["ink"],
             font=("Segoe UI Semibold", 18), justify="left").pack(anchor="w", pady=(8, 18))
    for text in ("Nama dan NIP pegawai", "Unit kerja", "Bulan dan tahun aktif", "Filter rekap bulanan"):
        row = tk.Frame(aside, bg=COLORS["surface_alt"])
        row.pack(fill="x", pady=7)
        tk.Label(row, text="●", bg=COLORS["surface_alt"], fg=COLORS["blue"],
                 font=("Segoe UI", 7)).pack(side="left", padx=(0, 10))
        tk.Label(row, text=text, bg=COLORS["surface_alt"], fg="#344054",
                 font=("Segoe UI", 10)).pack(side="left")
    tk.Frame(aside, bg=COLORS["line"], height=1).pack(fill="x", pady=20)
    tk.Label(aside, text="Mengganti bulan tidak menghapus data bulan sebelumnya.",
             bg=COLORS["surface_alt"], fg=COLORS["muted"], font=("Segoe UI", 9),
             justify="left", wraplength=280).pack(anchor="w")
