"""Layout for the Blanko Lembur tab."""

import re
import tkinter as tk
from tkinter import ttk

from core import MAX_JOB_ROWS, default_start_time, normalize_time_input
from ui.common import COLORS


def _metric_card(app, parent: ttk.Frame, column: int, label: str, color: str) -> tk.Label:
    card = tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["line"],
                    highlightthickness=1, padx=15, pady=11)
    card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 7, 0 if column == 2 else 7))
    copy = tk.Frame(card, bg=COLORS["surface"])
    copy.pack(fill="both", expand=True)
    label_row = tk.Frame(copy, bg=COLORS["surface"])
    label_row.pack(fill="x")
    tk.Label(label_row, text="●", bg=COLORS["surface"], fg=color,
             font=("Segoe UI", 7)).pack(side="left", padx=(0, 7))
    tk.Label(label_row, text=label.upper(), bg=COLORS["surface"], fg=COLORS["muted"],
             font=("Segoe UI Semibold", 8)).pack(side="left")
    value = tk.Label(copy, text="0", bg=COLORS["surface"], fg=COLORS["ink"],
                     font=("Segoe UI Semibold", 17))
    value.pack(anchor="w", pady=(3, 0))
    return value


def _entry_field(app, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int) -> ttk.Entry:
    holder = ttk.Frame(parent, style="Card.TFrame")
    holder.grid(row=0, column=column, sticky="ew", padx=5)
    ttk.Label(holder, text=label, style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
    entry = ttk.Entry(holder, textvariable=variable)
    entry.pack(fill="x")
    return entry


def _combo_field(app, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int) -> ttk.Combobox:
    holder = ttk.Frame(parent, style="Card.TFrame")
    holder.grid(row=0, column=column, sticky="ew", padx=5)
    ttk.Label(holder, text=label, style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
    app.date_combo = ttk.Combobox(holder, textvariable=variable, state="readonly")
    app.date_combo.pack(fill="x")
    app.date_combo.bind("<<ComboboxSelected>>", app._on_overtime_date_changed)
    return app.date_combo


def build(app) -> None:
    tab = app.blanko_tab
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(1, weight=1)

    metrics = ttk.Frame(tab, style="Card.TFrame")
    metrics.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    for index in range(3):
        metrics.columnconfigure(index, weight=1)
    app.metric_blanko = _metric_card(app, metrics, 0, "Blanko bulan ini", COLORS["blue"])
    app.metric_jobs = _metric_card(app, metrics, 1, "Total pekerjaan", COLORS["green"])
    app.metric_hours = _metric_card(app, metrics, 2, "Total jam lembur", "#F79009")

    panes = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
    panes.grid(row=1, column=0, sticky="nsew")
    input_card = tk.Frame(panes, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
    records_card = tk.Frame(panes, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
    panes.add(input_card, weight=3)
    panes.add(records_card, weight=2)
    _build_daily_input(app, input_card)
    _build_monthly_records(app, records_card)


def _build_daily_input(app, parent: tk.Frame) -> None:
    shell = ttk.Frame(parent, style="Card.TFrame", padding=16)
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(4, weight=1)

    heading = ttk.Frame(shell, style="Card.TFrame")
    heading.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    heading_copy = ttk.Frame(heading, style="Card.TFrame")
    heading_copy.pack(side="left", fill="x", expand=True)
    ttk.Label(heading_copy, text="Input blanko harian", style="Title.Card.TLabel").pack(anchor="w")
    ttk.Label(heading_copy, text="Pilih tanggal, atur jam, lalu tambahkan pekerjaan.",
              style="Muted.Card.TLabel", font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
    app.edit_mode_label = tk.Label(heading, text="BARU", bg=COLORS["soft_blue"], fg=COLORS["blue"],
                                   font=("Segoe UI Semibold", 8), padx=9, pady=5)
    app.edit_mode_label.pack(side="right")

    date_time = ttk.Frame(shell, style="Card.TFrame")
    date_time.grid(row=1, column=0, sticky="ew")
    date_time.columnconfigure(0, weight=2)
    date_time.columnconfigure(1, weight=1)
    date_time.columnconfigure(2, weight=1)
    app.overtime_date_var = tk.StringVar()
    app.start_time_var = tk.StringVar(value="16:00")
    app.end_time_var = tk.StringVar(value="18:00")
    _combo_field(app, date_time, "Tanggal lembur", app.overtime_date_var, 0)
    app.start_time_entry = _entry_field(app, date_time, "Jam mulai (contoh 1600)", app.start_time_var, 1)
    app.end_time_entry = _entry_field(app, date_time, "Jam selesai (contoh 1800)", app.end_time_var, 2)
    for entry, variable in ((app.start_time_entry, app.start_time_var), (app.end_time_entry, app.end_time_var)):
        entry.bind("<KeyRelease>", lambda _event, var=variable: app._format_time_as_typed(var))
        entry.bind("<FocusOut>", lambda _event, var=variable: app._normalize_time_var(var))

    tk.Frame(shell, bg=COLORS["line"], height=1).grid(row=2, column=0, sticky="ew", pady=12)
    item_editor = ttk.Frame(shell, style="Card.TFrame")
    item_editor.grid(row=3, column=0, sticky="ew")
    item_editor.columnconfigure(0, weight=5)
    item_editor.columnconfigure(1, weight=2)
    item_editor.columnconfigure(2, weight=3)
    app.job_var = tk.StringVar()
    app.quantity_var = tk.StringVar()
    app.note_var = tk.StringVar()
    app.job_entry = _entry_field(app, item_editor, "Pekerjaan", app.job_var, 0)
    app.quantity_entry = _entry_field(app, item_editor, "Kuantitas", app.quantity_var, 1)
    quantity_validation = (app.register(app._quantity_input_is_valid), "%P")
    app.quantity_entry.configure(validate="key", validatecommand=quantity_validation)
    _entry_field(app, item_editor, "Keterangan", app.note_var, 2)

    item_actions = ttk.Frame(item_editor, style="Card.TFrame")
    item_actions.grid(row=1, column=0, columnspan=3, sticky="ew", padx=5, pady=(8, 4))
    app.add_item_button = ttk.Button(item_actions, text="Tambah ke daftar", style="Accent.TButton",
                                     command=app._add_or_update_item)
    app.add_item_button.pack(side="left")
    ttk.Button(item_actions, text="Kosongkan", style="Secondary.TButton",
               command=app._clear_item_editor).pack(side="left", padx=(8, 0))
    app.item_counter_label = ttk.Label(item_actions, text=f"0 / {MAX_JOB_ROWS} baris", style="Muted.Card.TLabel")
    app.item_counter_label.pack(side="right")

    table_frame = ttk.Frame(shell, style="Card.TFrame")
    table_frame.grid(row=4, column=0, sticky="nsew", pady=(7, 0))
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)
    app.draft_tree = ttk.Treeview(table_frame, columns=("no", "pekerjaan", "kuantitas", "keterangan"),
                                  show="headings", height=6, selectmode="browse")
    for column, heading in (("no", "No."), ("pekerjaan", "Pekerjaan"), ("kuantitas", "Kuantitas"), ("keterangan", "Keterangan")):
        app.draft_tree.heading(column, text=heading)
    app.draft_tree.column("no", width=45, minwidth=40, anchor="center", stretch=False)
    app.draft_tree.column("pekerjaan", width=300, minwidth=180)
    app.draft_tree.column("kuantitas", width=105, minwidth=85, anchor="center")
    app.draft_tree.column("keterangan", width=180, minwidth=120)
    app.draft_tree.tag_configure("stripe", background=COLORS["surface_alt"])
    app.draft_tree.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=app.draft_tree.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    app.draft_tree.configure(yscrollcommand=scrollbar.set)
    app.draft_tree.bind("<Double-1>", lambda _event: app._edit_selected_item())

    row_actions = ttk.Frame(shell, style="Card.TFrame")
    row_actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
    ttk.Button(row_actions, text="Edit baris", style="Secondary.TButton",
               command=app._edit_selected_item).pack(side="left")
    ttk.Button(row_actions, text="Hapus baris", style="Danger.TButton",
               command=app._delete_selected_item).pack(side="left", padx=(8, 0))
    app.blanko_error = ttk.Label(shell, text="", style="Error.TLabel")
    app.blanko_error.grid(row=6, column=0, sticky="w", pady=(8, 0))
    save_actions = ttk.Frame(shell, style="Card.TFrame")
    save_actions.grid(row=7, column=0, sticky="ew", pady=(10, 0))
    app.cancel_edit_button = ttk.Button(save_actions, text="Batal edit", style="Secondary.TButton",
                                        command=app._reset_blanko_form)
    app.cancel_edit_button.pack(side="left")
    app.cancel_edit_button.pack_forget()
    app.save_blanko_button = ttk.Button(save_actions, text="Simpan blanko", style="Primary.TButton",
                                        command=app._save_blanko)
    app.save_blanko_button.pack(side="right")


def _build_monthly_records(app, parent: tk.Frame) -> None:
    shell = ttk.Frame(parent, style="Card.TFrame", padding=16)
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(2, weight=1)
    ttk.Label(shell, text="Blanko tersimpan", style="Title.Card.TLabel").grid(row=0, column=0, sticky="w")
    app.records_period_label = ttk.Label(shell, text="", style="Muted.Card.TLabel")
    app.records_period_label.grid(row=1, column=0, sticky="w", pady=(3, 10))

    table_frame = ttk.Frame(shell, style="Card.TFrame")
    table_frame.grid(row=2, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)
    app.records_tree = ttk.Treeview(table_frame, columns=("tanggal", "jam", "jumlah"),
                                    show="headings", selectmode="browse", height=11)
    for column, heading in (("tanggal", "Tanggal"), ("jam", "Jam"), ("jumlah", "Pekerjaan")):
        app.records_tree.heading(column, text=heading)
    app.records_tree.column("tanggal", width=115, minwidth=100)
    app.records_tree.column("jam", width=105, minwidth=90, anchor="center")
    app.records_tree.column("jumlah", width=95, minwidth=80, anchor="center")
    app.records_tree.tag_configure("stripe", background=COLORS["surface_alt"])
    app.records_tree.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=app.records_tree.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    app.records_tree.configure(yscrollcommand=scrollbar.set)
    app.records_tree.bind("<Double-1>", lambda _event: app._edit_selected_record())

    record_actions = ttk.Frame(shell, style="Card.TFrame")
    record_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    ttk.Button(record_actions, text="Edit", style="Secondary.TButton",
               command=app._edit_selected_record).pack(side="left")
    ttk.Button(record_actions, text="Hapus", style="Danger.TButton",
               command=app._delete_selected_record).pack(side="left", padx=(7, 0))
    info = tk.Frame(shell, bg=COLORS["soft_blue"], padx=12, pady=9)
    info.grid(row=4, column=0, sticky="ew", pady=(14, 10))
    tk.Label(info, text="Preview seluruh tanggal sebelum file Word disimpan.",
             bg=COLORS["soft_blue"], fg=COLORS["blue_dark"], font=("Segoe UI", 9),
             justify="left", wraplength=330).pack(anchor="w")
    app.generate_button = ttk.Button(shell, text="Rekap Harian", style="Success.TButton",
                                     command=app._preview_month)
    app.generate_button.grid(row=5, column=0, sticky="ew", pady=(0, 8))
    app.recap_button = ttk.Button(shell, text="Rekap Bulanan", style="Primary.TButton",
                                  command=app._save_monthly_recap)
    app.recap_button.grid(row=6, column=0, sticky="ew")
