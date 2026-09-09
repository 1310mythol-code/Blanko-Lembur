"""Layout for the Pejabat tab."""

import tkinter as tk
from tkinter import ttk

from ui.common import COLORS


def _role_input_row(app, parent, row, follow_variable, role_variable):
    block = ttk.Frame(parent, style="Card.TFrame")
    block.grid(row=row, column=0, columnspan=2, sticky="ew", padx=7, pady=(0, 6))
    ttk.Checkbutton(block, text="Gunakan Unit Kerja", variable=follow_variable).pack(side="left", padx=(0, 16))
    entry = ttk.Entry(block, textvariable=role_variable)
    entry.pack(side="left", fill="x", expand=True)
    return entry


def build(app) -> None:
    tab = app.officials_tab
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(1, weight=1)

    intro = app._section_intro(
        tab,
        "02",
        "Data pejabat penandatangan",
        "Nama dan jabatan otomatis tampil di Word. NIP boleh kosong untuk pejabat non-ASN.",
    )
    intro.grid(row=0, column=0, sticky="ew", pady=(0, 16))

    form_card = tk.Frame(tab, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
    form_card.grid(row=1, column=0, sticky="nsew")
    form = ttk.Frame(form_card, style="Card.TFrame", padding=16)
    form.pack(fill="both", expand=True)
    form.columnconfigure(0, weight=1)
    form.columnconfigure(1, weight=1)

    app.manager_name_var = tk.StringVar()
    app.manager_nip_var = tk.StringVar()
    app.asmen_name_var = tk.StringVar()
    app.asmen_nip_var = tk.StringVar()
    app.manager_role_var = tk.StringVar()
    app.asmen_role_var = tk.StringVar()
    app.manager_follow_unit_var = tk.BooleanVar(value=True)
    app.asmen_follow_unit_var = tk.BooleanVar(value=True)

    manager_header = tk.Frame(form, bg=COLORS["surface_alt"], padx=14, pady=10)
    manager_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=7, pady=(0, 8))
    app.manager_title_label = tk.Label(manager_header, text="Manajer", bg=COLORS["surface_alt"],
                                       fg=COLORS["blue"], font=("Segoe UI Semibold", 9),
                                       wraplength=950, justify="left")
    app.manager_title_label.pack(anchor="w")
    app.manager_role_entry = _role_input_row(app, form, 1, app.manager_follow_unit_var, app.manager_role_var)
    app._labeled_entry(form, "Nama manajer", app.manager_name_var, 2, 0)
    app._labeled_entry(form, "NIP manajer (opsional)", app.manager_nip_var, 2, 1)

    asmen_header = tk.Frame(form, bg=COLORS["surface_alt"], padx=14, pady=10)
    asmen_header.grid(row=3, column=0, columnspan=2, sticky="ew", padx=7, pady=(10, 6))
    app.asmen_title_label = tk.Label(asmen_header, text="Asisten Manajer", bg=COLORS["surface_alt"],
                                     fg=COLORS["blue"], font=("Segoe UI Semibold", 9),
                                     wraplength=950, justify="left")
    app.asmen_title_label.pack(anchor="w")
    app.asmen_role_entry = _role_input_row(app, form, 4, app.asmen_follow_unit_var, app.asmen_role_var)
    app._labeled_entry(form, "Nama asisten manajer", app.asmen_name_var, 5, 0)
    app._labeled_entry(form, "NIP asisten manajer (opsional)", app.asmen_nip_var, 5, 1)

    app.officials_error = ttk.Label(form, text="", style="Error.TLabel")
    app.officials_error.grid(row=6, column=0, columnspan=2, sticky="w", padx=7, pady=(10, 0))
    action = ttk.Frame(form, style="Card.TFrame")
    action.grid(row=7, column=0, columnspan=2, sticky="ew", padx=7, pady=(10, 0))
    ttk.Label(action, text="Hilangkan centang untuk mengisi nama bidang/unit jabatan secara manual.",
              style="Muted.Card.TLabel").pack(side="left")
    ttk.Button(action, text="Simpan Data Pejabat", style="Primary.TButton",
               command=app._save_officials).pack(side="right")

    for variable in (app.manager_role_var, app.asmen_role_var,
                     app.manager_follow_unit_var, app.asmen_follow_unit_var):
        variable.trace_add("write", app._refresh_officials_titles)
