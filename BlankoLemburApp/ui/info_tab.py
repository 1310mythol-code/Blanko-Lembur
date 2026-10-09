"""Layout for the Info aplikasi tab."""

import tkinter as tk
from tkinter import ttk

from app_metadata import APP_VERSION
from ui.common import COLORS
import updater


def build(app) -> None:
    intro = app._section_intro(
        app.info_tab,
        "04",
        "Info aplikasi",
        "Tentang Aplikasi Blanko Lembur Otomatis.",
    )
    intro.pack(fill="x", pady=(0, 24))
    card = tk.Frame(app.info_tab, bg=COLORS["surface_alt"], padx=28, pady=26,
                    highlightbackground=COLORS["line"], highlightthickness=1)
    card.pack(fill="x")
    for text, font in (
        ("Aplikasi Ini dibuat oleh NAM", ("Segoe UI Semibold", 15)),
        (f"Versi aplikasi: {APP_VERSION}", ("Segoe UI", 11)),
        ("Aplikasi ini dibuat untuk pegawai RSUP Dr M Djamil", ("Segoe UI", 11)),
    ):
        tk.Label(card, text=text, bg=COLORS["surface_alt"], fg=COLORS["ink"],
                 font=font, anchor="w", justify="left", wraplength=900).pack(anchor="w", pady=(0, 14))
    actions = tk.Frame(card, bg=COLORS["surface_alt"])
    actions.pack(fill="x", pady=(10, 12))
    app.check_update_button = ttk.Button(actions, text="Cek untuk Update", style="Primary.TButton",
                                         command=app._check_for_updates)
    app.check_update_button.pack(side="left")
    app.publisher_email_button = ttk.Button(
        actions, text="Kirim Email ke NAM", style="Secondary.TButton",
        command=app._email_publisher,
    )
    app.publisher_email_button.pack(side="left", padx=(10, 0))
    app.install_update_button = ttk.Button(actions, text="Unduh & Perbarui", style="Success.TButton",
                                           command=app._download_available_update)
    app.update_status_var = tk.StringVar(value=(
        "Tekan tombol untuk memeriksa pembaruan." if updater.is_configured()
        else "Pembaruan online belum diaktifkan. Aplikasi tetap dapat digunakan."
    ))
    tk.Label(card, textvariable=app.update_status_var, bg=COLORS["surface_alt"],
             fg=COLORS["muted"], font=("Segoe UI", 10), justify="left",
             wraplength=900).pack(anchor="w")
