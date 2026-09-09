from __future__ import annotations

import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from recap import generate_monthly_recap
from app_metadata import APP_VERSION
import updater

from core import (
    MAX_JOB_ROWS,
    MONTH_NAMES,
    DataStore,
    JobItem,
    Officials,
    OvertimeRecord,
    Profile,
    default_start_time,
    duration_minutes,
    format_date_id,
    format_date_short,
    format_duration,
    generate_word,
    normalize_time_input,
    parse_period,
    period_dates,
    period_label,
    records_for_period,
    safe_filename,
    validate_record,
)
from ui.blanko_tab import build as build_blanko_tab_ui
from ui.info_tab import build as build_info_tab_ui
from ui.officials_tab import build as build_officials_tab_ui
from ui.profile_tab import build as build_profile_tab_ui


SOURCE_DIR = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))

if IS_FROZEN:
    # Keep the distributed application as one clean EXE. User data belongs in
    # Windows' per-user application-data location, not beside the executable.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        DATA_DIR = Path(local_app_data) / "BlankoLemburOtomatis"
    else:
        DATA_DIR = Path.home() / "AppData" / "Local" / "BlankoLemburOtomatis"
else:
    DATA_DIR = SOURCE_DIR / "data"

TEMPLATE_PATH = RESOURCE_DIR / "blanko_template.docx"
RECAP_TEMPLATE_PATH = RESOURCE_DIR / "REKAP LEMBUR BULAN.docx"

COLORS = {
    "navy": "#0F172A",
    "navy_2": "#172033",
    "blue": "#2563EB",
    "blue_dark": "#1D4ED8",
    "green": "#059669",
    "green_soft": "#ECFDF5",
    "red": "#DC2626",
    "red_soft": "#FEF2F2",
    "ink": "#101828",
    "muted": "#667085",
    "line": "#E4E7EC",
    "surface": "#FFFFFF",
    "surface_alt": "#F9FAFB",
    "background": "#F5F7FA",
    "soft_blue": "#EFF6FF",
    "amber": "#B54708",
    "amber_soft": "#FFFAEB",
}


class BlankoLemburApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Blanko Lembur Otomatis")
        self.geometry("1240x800")
        self.minsize(1080, 700)
        self.configure(bg=COLORS["background"])
        self._center_window()
        self._configure_styles()

        try:
            self.store = DataStore(DATA_DIR)
            self.profile = self.store.load_profile()
            self.officials = self.store.load_officials()
            self.records = self.store.load_records()
        except Exception as exc:
            messagebox.showerror(
                "Data tidak dapat dibuka",
                f"Aplikasi tidak dapat membaca penyimpanan data.\n\n{exc}",
            )
            raise

        self.draft_items: list[JobItem] = []
        self.editing_record_id: str | None = None
        self.editing_item_index: int | None = None
        self.date_display_to_iso: dict[str, str] = {}
        self.delete_target_id: str | None = None
        self._update_busy = False
        self._available_update = None
        self._downloaded_update: Path | None = None

        self._build_header()
        self._build_notebook()
        self._build_statusbar()
        self.profile_unit_var.trace_add("write", self._refresh_officials_titles)
        self._load_forms()
        self._refresh_period_dependent_ui()
        self.notebook.select(self.blanko_tab)
        self.after(100, self._focus_daily_form)

    def _center_window(self) -> None:
        self.update_idletasks()
        width, height = 1240, 800
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        # Tcl/Tk 9 (bundled with Python 3.14) requires font family names that
        # contain spaces to be grouped. Without braces, "UI" is parsed as the
        # font size and creating the first widget raises a TclError.
        self.option_add("*Font", "{Segoe UI} 10")
        self.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")

        style.configure("TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("Soft.TFrame", background=COLORS["surface_alt"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["ink"])
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["ink"])
        style.configure("Muted.Card.TLabel", background=COLORS["surface"], foreground=COLORS["muted"])
        style.configure("Title.Card.TLabel", background=COLORS["surface"], foreground=COLORS["ink"], font=("Segoe UI Semibold", 13))
        style.configure("Section.TLabel", background=COLORS["background"], foreground=COLORS["ink"], font=("Segoe UI Semibold", 11))
        style.configure("Error.TLabel", background=COLORS["surface"], foreground=COLORS["red"], font=("Segoe UI", 9))

        style.configure(
            "TNotebook",
            background=COLORS["background"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["background"],
            foreground=COLORS["muted"],
            padding=(22, 10),
            font=("Segoe UI Semibold", 10),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["surface"]), ("active", "#EAECF0")],
            foreground=[("selected", COLORS["blue"]), ("active", COLORS["ink"])],
        )

        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            padding=(10, 8),
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", COLORS["blue"])],
            lightcolor=[("focus", COLORS["blue"])],
            darkcolor=[("focus", COLORS["blue"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            padding=(9, 7),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLORS["surface"]), ("focus", COLORS["surface"])],
            bordercolor=[("focus", COLORS["blue"])],
            lightcolor=[("focus", COLORS["blue"])],
            darkcolor=[("focus", COLORS["blue"])],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            padding=(9, 7),
        )
        style.map(
            "TSpinbox",
            bordercolor=[("focus", COLORS["blue"])],
            lightcolor=[("focus", COLORS["blue"])],
            darkcolor=[("focus", COLORS["blue"])],
        )

        style.configure(
            "Primary.TButton",
            background=COLORS["blue"],
            foreground="white",
            borderwidth=0,
            padding=(16, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["blue_dark"]), ("pressed", COLORS["blue_dark"]), ("disabled", "#A6B8CA")],
            foreground=[("disabled", "#EFF4F8")],
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["soft_blue"],
            foreground=COLORS["blue"],
            borderwidth=0,
            padding=(13, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#DBEAFE"), ("pressed", "#BFDBFE")],
            foreground=[("active", COLORS["blue_dark"])],
        )
        style.configure(
            "Success.TButton",
            background=COLORS["green"],
            foreground="white",
            borderwidth=0,
            padding=(16, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Success.TButton", background=[("active", "#087C5E"), ("pressed", "#087C5E"), ("disabled", "#A6B8CA")])
        style.configure(
            "Secondary.TButton",
            background="#F2F4F7",
            foreground=COLORS["ink"],
            borderwidth=0,
            padding=(13, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map("Secondary.TButton", background=[("active", "#EAECF0"), ("pressed", "#D0D5DD")])
        style.configure(
            "Danger.TButton",
            background=COLORS["red_soft"],
            foreground=COLORS["red"],
            borderwidth=0,
            padding=(13, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map("Danger.TButton", background=[("active", "#FFE1E4"), ("pressed", "#FFD4D8")])

        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            rowheight=33,
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#F2F4F7",
            foreground="#475467",
            borderwidth=0,
            padding=(8, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map("Treeview", background=[("selected", "#E8F0FE")], foreground=[("selected", COLORS["ink"])])
        style.configure(
            "Vertical.TScrollbar",
            background="#D0D5DD",
            troughcolor="#F2F4F7",
            bordercolor="#F2F4F7",
            lightcolor="#D0D5DD",
            darkcolor="#D0D5DD",
            arrowsize=12,
        )

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLORS["surface"], height=76)
        header.pack(fill="x")
        header.pack_propagate(False)

        brand = tk.Frame(header, bg=COLORS["surface"])
        brand.pack(side="left", padx=(24, 0), pady=14)
        mark = tk.Label(
            brand,
            text="B",
            bg=COLORS["blue"],
            fg="white",
            font=("Segoe UI Semibold", 14),
            width=3,
            height=2,
        )
        mark.pack(side="left", padx=(0, 12))
        title_box = tk.Frame(brand, bg=COLORS["surface"])
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="Blanko Lembur",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="Kelola data dan buat Word siap cetak",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        period_box = tk.Frame(header, bg=COLORS["soft_blue"], padx=15, pady=8)
        period_box.pack(side="right", padx=24, pady=14)
        tk.Label(
            period_box,
            text="PERIODE AKTIF",
            bg=COLORS["soft_blue"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="e")
        self.header_period_label = tk.Label(
            period_box,
            text=self.profile.bulan,
            bg=COLORS["soft_blue"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 11),
        )
        self.header_period_label.pack(anchor="e", pady=(2, 0))
        tk.Frame(self, bg=COLORS["line"], height=1).pack(fill="x")

    def _build_notebook(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True, padx=22, pady=(14, 8))

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.profile_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=20)
        self.officials_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=20)
        self.blanko_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=16)
        self.info_tab = ttk.Frame(self.notebook, style="Card.TFrame", padding=24)

        self.notebook.add(self.profile_tab, text="Profil")
        self.notebook.add(self.officials_tab, text="Pejabat")
        self.notebook.add(self.blanko_tab, text="Blanko Lembur")
        self.notebook.add(self.info_tab, text="Info aplikasi")

        self._build_profile_tab()
        self._build_officials_tab()
        self._build_blanko_tab()
        self._build_info_tab()

    def _build_statusbar(self) -> None:
        status = tk.Frame(
            self,
            bg=COLORS["surface"],
            height=34,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        self.status_label = tk.Label(
            status,
            text="Siap. Data tersimpan otomatis di perangkat ini.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        self.status_label.pack(side="left", padx=22)
        tk.Label(
            status,
            text="●  DATA LOKAL • BISA OFFLINE",
            bg=COLORS["surface"],
            fg=COLORS["green"],
            font=("Segoe UI Semibold", 8),
        ).pack(side="right", padx=22)

    def _section_intro(self, parent: ttk.Frame, number: str, title: str, subtitle: str) -> ttk.Frame:
        block = ttk.Frame(parent, style="Card.TFrame")
        badge = tk.Label(
            block,
            text=number,
            bg=COLORS["soft_blue"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 9),
            padx=10,
            pady=6,
        )
        badge.pack(side="left", padx=(0, 12))
        copy = ttk.Frame(block, style="Card.TFrame")
        copy.pack(side="left", fill="x", expand=True)
        ttk.Label(copy, text=title, style="Title.Card.TLabel").pack(anchor="w")
        ttk.Label(copy, text=subtitle, style="Muted.Card.TLabel").pack(anchor="w", pady=(3, 0))
        return block

    def _labeled_entry(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        column: int = 0,
        columnspan: int = 1,
        width: int | None = None,
    ) -> ttk.Entry:
        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=7, pady=7)
        ttk.Label(holder, text=label, style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        entry = ttk.Entry(holder, textvariable=variable, width=width)
        entry.pack(fill="x")
        return entry

    def _legacy_build_profile_tab(self) -> None:
        tab = self.profile_tab
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(1, weight=1)

        intro = self._section_intro(
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

        self.profile_name_var = tk.StringVar()
        self.profile_nip_var = tk.StringVar()
        self.profile_unit_var = tk.StringVar()
        self.profile_month_var = tk.StringVar()
        self.profile_year_var = tk.StringVar()

        self.profile_name_entry = self._labeled_entry(form, "Nama pegawai", self.profile_name_var, 0, 0, 2)
        self._labeled_entry(form, "NIP", self.profile_nip_var, 1, 0, 2)
        self._labeled_entry(form, "Unit kerja", self.profile_unit_var, 2, 0, 2)

        month_holder = ttk.Frame(form, style="Card.TFrame")
        month_holder.grid(row=3, column=0, sticky="ew", padx=7, pady=7)
        ttk.Label(month_holder, text="Bulan", style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        self.profile_month_combo = ttk.Combobox(
            month_holder,
            textvariable=self.profile_month_var,
            values=MONTH_NAMES,
            state="readonly",
        )
        self.profile_month_combo.pack(fill="x")

        year_holder = ttk.Frame(form, style="Card.TFrame")
        year_holder.grid(row=3, column=1, sticky="ew", padx=7, pady=7)
        ttk.Label(year_holder, text="Tahun", style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        ttk.Spinbox(year_holder, from_=2000, to=2100, textvariable=self.profile_year_var).pack(fill="x")

        self.profile_error = ttk.Label(form, text="", style="Error.TLabel")
        self.profile_error.grid(row=4, column=0, columnspan=2, sticky="w", padx=7, pady=(5, 0))
        ttk.Button(form, text="Simpan Profil", style="Primary.TButton", command=self._save_profile).grid(
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
        tk.Label(
            aside,
            text="TERHUBUNG OTOMATIS",
            bg=COLORS["surface_alt"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        tk.Label(
            aside,
            text="Satu profil untuk\nsemua blanko",
            bg=COLORS["surface_alt"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 18),
            justify="left",
        ).pack(anchor="w", pady=(8, 18))
        for text in (
            "Nama dan NIP pegawai",
            "Unit kerja",
            "Bulan dan tahun aktif",
            "Filter rekap bulanan",
        ):
            row = tk.Frame(aside, bg=COLORS["surface_alt"])
            row.pack(fill="x", pady=7)
            tk.Label(
                row,
                text="●",
                bg=COLORS["surface_alt"],
                fg=COLORS["blue"],
                font=("Segoe UI", 7),
            ).pack(side="left", padx=(0, 10))
            tk.Label(
                row,
                text=text,
                bg=COLORS["surface_alt"],
                fg="#344054",
                font=("Segoe UI", 10),
            ).pack(side="left")
        tk.Frame(aside, bg=COLORS["line"], height=1).pack(fill="x", pady=20)
        tk.Label(
            aside,
            text="Mengganti bulan tidak menghapus data bulan sebelumnya.",
            bg=COLORS["surface_alt"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=280,
        ).pack(anchor="w")

    def _legacy_build_officials_tab(self) -> None:
        tab = self.officials_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        intro = self._section_intro(
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

        self.manager_name_var = tk.StringVar()
        self.manager_nip_var = tk.StringVar()
        self.asmen_name_var = tk.StringVar()
        self.asmen_nip_var = tk.StringVar()
        self.manager_role_var = tk.StringVar()
        self.asmen_role_var = tk.StringVar()
        self.manager_follow_unit_var = tk.BooleanVar(value=True)
        self.asmen_follow_unit_var = tk.BooleanVar(value=True)

        manager_header = tk.Frame(form, bg=COLORS["surface_alt"], padx=14, pady=10)
        manager_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=7, pady=(0, 8))
        self.manager_title_label = tk.Label(
            manager_header,
            text="Manajer",
            bg=COLORS["surface_alt"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 9),
            wraplength=950,
            justify="left",
        )
        self.manager_title_label.pack(anchor="w")
        self.manager_role_entry = self._role_input_row(form, 1, self.manager_follow_unit_var, self.manager_role_var)
        self._labeled_entry(form, "Nama manajer", self.manager_name_var, 2, 0)
        self._labeled_entry(form, "NIP manajer", self.manager_nip_var, 2, 1)

        asmen_header = tk.Frame(form, bg=COLORS["surface_alt"], padx=14, pady=10)
        asmen_header.grid(row=3, column=0, columnspan=2, sticky="ew", padx=7, pady=(10, 6))
        self.asmen_title_label = tk.Label(
            asmen_header,
            text="Asisten Manajer",
            bg=COLORS["surface_alt"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 9),
            wraplength=950,
            justify="left",
        )
        self.asmen_title_label.pack(anchor="w")
        self.asmen_role_entry = self._role_input_row(form, 4, self.asmen_follow_unit_var, self.asmen_role_var)
        self._labeled_entry(form, "Nama asisten manajer", self.asmen_name_var, 5, 0)
        self._labeled_entry(form, "NIP asisten manajer", self.asmen_nip_var, 5, 1)

        self.officials_error = ttk.Label(form, text="", style="Error.TLabel")
        self.officials_error.grid(row=6, column=0, columnspan=2, sticky="w", padx=7, pady=(10, 0))
        action = ttk.Frame(form, style="Card.TFrame")
        action.grid(row=7, column=0, columnspan=2, sticky="ew", padx=7, pady=(10, 0))
        ttk.Label(
            action,
            text="Hilangkan centang untuk mengisi nama bidang/unit jabatan secara manual.",
            style="Muted.Card.TLabel",
        ).pack(side="left")
        ttk.Button(action, text="Simpan Data Pejabat", style="Primary.TButton", command=self._save_officials).pack(side="right")

        for variable in (self.manager_role_var, self.asmen_role_var,
                         self.manager_follow_unit_var, self.asmen_follow_unit_var):
            variable.trace_add("write", self._refresh_officials_titles)

    def _legacy_role_input_row(self, parent, row, follow_variable, role_variable):
        block = ttk.Frame(parent, style="Card.TFrame")
        block.grid(row=row, column=0, columnspan=2, sticky="ew", padx=7, pady=(0, 6))
        ttk.Checkbutton(block, text="Gunakan Unit Kerja", variable=follow_variable).pack(side="left", padx=(0, 16))
        entry = ttk.Entry(block, textvariable=role_variable)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def _refresh_officials_titles(self, *_args) -> None:
        for value, entry, label, prefix in (
            (self.manager_role_var, self.manager_role_entry, self.manager_title_label, "Manajer"),
            (self.asmen_role_var, self.asmen_role_entry, self.asmen_title_label, "Asisten Manajer"),
        ):
            entry.configure(state="normal")
            label.configure(text=f"{prefix} {value.get().strip()}".strip())

    def _legacy_build_info_tab(self) -> None:
        intro = self._section_intro(
            self.info_tab, "04", "Info aplikasi", "Tentang Blanko Lembur Otomatis dan pembaruan aplikasi.",
        )
        intro.pack(fill="x", pady=(0, 24))
        card = tk.Frame(self.info_tab, bg=COLORS["surface_alt"], padx=28, pady=26,
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
        self.check_update_button = ttk.Button(actions, text="Cek untuk Update", style="Primary.TButton",
                                              command=self._check_for_updates)
        self.check_update_button.pack(side="left")
        self.install_update_button = ttk.Button(actions, text="Unduh & Perbarui", style="Success.TButton",
                                                command=self._download_available_update)
        self.update_status_var = tk.StringVar(value=(
            "Siap memeriksa pembaruan resmi melalui GitHub." if updater.is_configured()
            else "Pembaruan online belum diaktifkan. Aplikasi tetap dapat digunakan."
        ))
        tk.Label(card, textvariable=self.update_status_var, bg=COLORS["surface_alt"],
                 fg=COLORS["muted"], font=("Segoe UI", 10), justify="left",
                 wraplength=900).pack(anchor="w")

    def _run_update_task(self, work, on_success) -> None:
        """Keep network and disk work off Tk's thread; handle all UI on Tk's thread."""
        if self._update_busy:
            return
        self._update_busy = True
        self.check_update_button.configure(state="disabled")
        self.install_update_button.configure(state="disabled")
        results = queue.Queue()

        def worker():
            try:
                results.put((True, work()))
            except Exception as exc:
                results.put((False, exc))

        def poll():
            try:
                success, value = results.get_nowait()
            except queue.Empty:
                self.after(100, poll)
                return
            self._update_busy = False
            self.check_update_button.configure(state="normal")
            self.install_update_button.configure(state="normal")
            if success:
                on_success(value)
            else:
                text = str(value) if isinstance(value, updater.UpdateError) else "Pembaruan gagal. Silakan coba lagi."
                self.update_status_var.set(text)
                messagebox.showerror("Pembaruan belum berhasil", text, parent=self)

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, poll)

    def _check_for_updates(self) -> None:
        if self._update_busy:
            return
        if not updater.is_configured():
            self.update_status_var.set("Pembaruan online belum diaktifkan. Aplikasi tetap dapat digunakan.")
            messagebox.showinfo("Pembaruan belum tersedia",
                                "Layanan pembaruan online belum diaktifkan oleh NAM.\n\n"
                                f"Aplikasi versi {APP_VERSION} tetap bisa digunakan seperti biasa.", parent=self)
            return
        self.update_status_var.set("Memeriksa pembaruan…")
        self._run_update_task(updater.check_for_update, self._show_available_update)

    def _show_available_update(self, release) -> None:
        self._available_update = release
        self._downloaded_update = None
        self.install_update_button.pack_forget()
        if release is None:
            self.update_status_var.set(
                f"Versi {APP_VERSION} sudah terbaru."
            )
            return
        notes = release.notes[:1200] + ("…" if len(release.notes) > 1200 else "")
        self.update_status_var.set(f"Versi {release.version} tersedia.\n{notes}")
        self.install_update_button.configure(text="Unduh & Perbarui")
        self.install_update_button.pack(side="left", padx=(12, 0))

    def _has_unsaved_update_input(self) -> bool:
        month, year = parse_period(self.profile.bulan)
        fields = (
            (self.profile_name_var, self.profile.nama), (self.profile_nip_var, self.profile.nip),
            (self.profile_unit_var, self.profile.unit_kerja), (self.profile_month_var, MONTH_NAMES[month - 1]),
            (self.profile_year_var, str(year)), (self.manager_name_var, self.officials.nama_manager),
            (self.manager_nip_var, self.officials.nip_manager), (self.asmen_name_var, self.officials.nama_asmen),
            (self.asmen_nip_var, self.officials.nip_asmen),
        )
        role_changed = (
            self.manager_role_var.get().strip() != (self.officials.manager_unit_override or self.profile.unit_kerja).strip()
            or self.asmen_role_var.get().strip() != (self.officials.asmen_unit_override or self.profile.unit_kerja).strip()
            or not self.manager_role_var.get().strip()
            or not self.asmen_role_var.get().strip()
        )
        return bool(role_changed or self.draft_items or self.editing_record_id or
                    any(var.get().strip() != value.strip() for var, value in fields) or
                    any(var.get().strip() for var in (self.job_var, self.quantity_var, self.note_var)))

    def _download_available_update(self) -> None:
        if self._update_busy or self._available_update is None:
            return
        if not IS_FROZEN:
            messagebox.showinfo("Jalankan versi EXE", "Pembaruan otomatis tersedia pada versi EXE aplikasi.", parent=self)
            return
        if self._has_unsaved_update_input():
            messagebox.showinfo("Simpan pekerjaan dahulu",
                                "Simpan atau batalkan perubahan pada Profil, Pejabat, dan blanko sebelum memperbarui.", parent=self)
            return
        if self._downloaded_update is not None:
            self._offer_install_update(self._downloaded_update)
            return
        release = self._available_update
        self.update_status_var.set(f"Mengunduh versi {release.version}… Aplikasi tetap dapat digunakan.")
        self._run_update_task(lambda: updater.download_update(release, DATA_DIR), self._offer_install_update)

    def _offer_install_update(self, staged: Path) -> None:
        self._downloaded_update = staged
        self.install_update_button.configure(text="Pasang Update")
        self.update_status_var.set("Pembaruan selesai diunduh dan siap dipasang.")
        if self._has_unsaved_update_input():
            messagebox.showinfo("Simpan pekerjaan dahulu",
                                "Pembaruan siap. Simpan pekerjaan, lalu klik Pasang Update.", parent=self)
            return
        if not messagebox.askyesno("Pasang pembaruan?",
                                  "Aplikasi akan ditutup lalu dibuka kembali dengan versi baru.\n\n"
                                  "Data lembur yang sudah disimpan tetap ada. Lanjutkan?", parent=self):
            return
        try:
            updater.launch_update(staged, Path(sys.executable))
        except (updater.UpdateError, OSError) as exc:
            messagebox.showerror("Pembaruan belum berhasil", str(exc), parent=self)
            return
        self.destroy()

    def _legacy_metric_card(self, parent: ttk.Frame, column: int, label: str, color: str) -> tk.Label:
        card = tk.Frame(
            parent,
            bg=COLORS["surface"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
            padx=15,
            pady=11,
        )
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 7, 0 if column == 2 else 7))
        copy = tk.Frame(card, bg=COLORS["surface"])
        copy.pack(fill="both", expand=True)
        label_row = tk.Frame(copy, bg=COLORS["surface"])
        label_row.pack(fill="x")
        tk.Label(label_row, text="●", bg=COLORS["surface"], fg=color, font=("Segoe UI", 7)).pack(side="left", padx=(0, 7))
        tk.Label(
            label_row,
            text=label.upper(),
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).pack(side="left")
        value = tk.Label(copy, text="0", bg=COLORS["surface"], fg=COLORS["ink"], font=("Segoe UI Semibold", 17))
        value.pack(anchor="w", pady=(3, 0))
        return value

    def _legacy_build_blanko_tab(self) -> None:
        tab = self.blanko_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        metrics = ttk.Frame(tab, style="Card.TFrame")
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for index in range(3):
            metrics.columnconfigure(index, weight=1)
        self.metric_blanko = self._metric_card(metrics, 0, "Blanko bulan ini", COLORS["blue"])
        self.metric_jobs = self._metric_card(metrics, 1, "Total pekerjaan", COLORS["green"])
        self.metric_hours = self._metric_card(metrics, 2, "Total jam lembur", "#F79009")

        panes = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew")

        input_card = tk.Frame(panes, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
        records_card = tk.Frame(panes, bg=COLORS["surface"], highlightbackground=COLORS["line"], highlightthickness=1)
        panes.add(input_card, weight=3)
        panes.add(records_card, weight=2)
        self._build_daily_input(input_card)
        self._build_monthly_records(records_card)

    def _legacy_build_daily_input(self, parent: tk.Frame) -> None:
        shell = ttk.Frame(parent, style="Card.TFrame", padding=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(4, weight=1)

        heading = ttk.Frame(shell, style="Card.TFrame")
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        heading_copy = ttk.Frame(heading, style="Card.TFrame")
        heading_copy.pack(side="left", fill="x", expand=True)
        ttk.Label(heading_copy, text="Input blanko harian", style="Title.Card.TLabel").pack(anchor="w")
        ttk.Label(
            heading_copy,
            text="Pilih tanggal, atur jam, lalu tambahkan pekerjaan.",
            style="Muted.Card.TLabel",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))
        self.edit_mode_label = tk.Label(
            heading,
            text="BARU",
            bg=COLORS["soft_blue"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 8),
            padx=9,
            pady=5,
        )
        self.edit_mode_label.pack(side="right")

        date_time = ttk.Frame(shell, style="Card.TFrame")
        date_time.grid(row=1, column=0, sticky="ew")
        date_time.columnconfigure(0, weight=2)
        date_time.columnconfigure(1, weight=1)
        date_time.columnconfigure(2, weight=1)

        self.overtime_date_var = tk.StringVar()
        self.start_time_var = tk.StringVar(value="16:00")
        self.end_time_var = tk.StringVar(value="18:00")
        self._combo_field(date_time, "Tanggal lembur", self.overtime_date_var, 0)
        self.start_time_entry = self._entry_field(date_time, "Jam mulai (contoh 1600)", self.start_time_var, 1)
        self.end_time_entry = self._entry_field(date_time, "Jam selesai (contoh 2000)", self.end_time_var, 2)
        for entry, variable in (
            (self.start_time_entry, self.start_time_var),
            (self.end_time_entry, self.end_time_var),
        ):
            entry.bind("<KeyRelease>", lambda _event, var=variable: self._format_time_as_typed(var))
            entry.bind("<FocusOut>", lambda _event, var=variable: self._normalize_time_var(var))

        divider = tk.Frame(shell, bg=COLORS["line"], height=1)
        divider.grid(row=2, column=0, sticky="ew", pady=12)

        item_editor = ttk.Frame(shell, style="Card.TFrame")
        item_editor.grid(row=3, column=0, sticky="ew")
        item_editor.columnconfigure(0, weight=5)
        item_editor.columnconfigure(1, weight=2)
        item_editor.columnconfigure(2, weight=3)

        self.job_var = tk.StringVar()
        self.quantity_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.job_entry = self._entry_field(item_editor, "Pekerjaan", self.job_var, 0)
        self.quantity_entry = self._entry_field(item_editor, "Kuantitas", self.quantity_var, 1)
        quantity_validation = (self.register(self._quantity_input_is_valid), "%P")
        self.quantity_entry.configure(validate="key", validatecommand=quantity_validation)
        self._entry_field(item_editor, "Keterangan", self.note_var, 2)

        item_actions = ttk.Frame(item_editor, style="Card.TFrame")
        item_actions.grid(row=1, column=0, columnspan=3, sticky="ew", padx=5, pady=(8, 4))
        self.add_item_button = ttk.Button(
            item_actions,
            text="Tambah ke daftar",
            style="Accent.TButton",
            command=self._add_or_update_item,
        )
        self.add_item_button.pack(side="left")
        ttk.Button(item_actions, text="Kosongkan", style="Secondary.TButton", command=self._clear_item_editor).pack(side="left", padx=(8, 0))
        self.item_counter_label = ttk.Label(item_actions, text=f"0 / {MAX_JOB_ROWS} baris", style="Muted.Card.TLabel")
        self.item_counter_label.pack(side="right")

        table_frame = ttk.Frame(shell, style="Card.TFrame")
        table_frame.grid(row=4, column=0, sticky="nsew", pady=(7, 0))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.draft_tree = ttk.Treeview(
            table_frame,
            columns=("no", "pekerjaan", "kuantitas", "keterangan"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        self.draft_tree.heading("no", text="No.")
        self.draft_tree.heading("pekerjaan", text="Pekerjaan")
        self.draft_tree.heading("kuantitas", text="Kuantitas")
        self.draft_tree.heading("keterangan", text="Keterangan")
        self.draft_tree.column("no", width=45, minwidth=40, anchor="center", stretch=False)
        self.draft_tree.column("pekerjaan", width=300, minwidth=180)
        self.draft_tree.column("kuantitas", width=105, minwidth=85, anchor="center")
        self.draft_tree.column("keterangan", width=180, minwidth=120)
        self.draft_tree.tag_configure("stripe", background=COLORS["surface_alt"])
        self.draft_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.draft_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.draft_tree.configure(yscrollcommand=scrollbar.set)
        self.draft_tree.bind("<Double-1>", lambda _event: self._edit_selected_item())

        row_actions = ttk.Frame(shell, style="Card.TFrame")
        row_actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(row_actions, text="Edit baris", style="Secondary.TButton", command=self._edit_selected_item).pack(side="left")
        ttk.Button(row_actions, text="Hapus baris", style="Danger.TButton", command=self._delete_selected_item).pack(side="left", padx=(8, 0))

        self.blanko_error = ttk.Label(shell, text="", style="Error.TLabel")
        self.blanko_error.grid(row=6, column=0, sticky="w", pady=(8, 0))

        save_actions = ttk.Frame(shell, style="Card.TFrame")
        save_actions.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        self.cancel_edit_button = ttk.Button(save_actions, text="Batal edit", style="Secondary.TButton", command=self._reset_blanko_form)
        self.cancel_edit_button.pack(side="left")
        self.cancel_edit_button.pack_forget()
        self.save_blanko_button = ttk.Button(save_actions, text="Simpan blanko", style="Primary.TButton", command=self._save_blanko)
        self.save_blanko_button.pack(side="right")

    def _legacy_entry_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int) -> ttk.Entry:
        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.grid(row=0, column=column, sticky="ew", padx=5)
        ttk.Label(holder, text=label, style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        entry = ttk.Entry(holder, textvariable=variable)
        entry.pack(fill="x")
        return entry

    def _legacy_combo_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int) -> ttk.Combobox:
        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.grid(row=0, column=column, sticky="ew", padx=5)
        ttk.Label(holder, text=label, style="Card.TLabel", font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        self.date_combo = ttk.Combobox(holder, textvariable=variable, state="readonly")
        self.date_combo.pack(fill="x")
        self.date_combo.bind("<<ComboboxSelected>>", self._on_overtime_date_changed)
        return self.date_combo

    @staticmethod
    def _quantity_input_is_valid(value: str) -> bool:
        return not value or (value.isascii() and value.isdigit())

    def _format_time_as_typed(self, variable: tk.StringVar) -> None:
        raw_value = variable.get().strip()
        if not re.fullmatch(r"\d{4}", raw_value):
            return
        try:
            variable.set(normalize_time_input(raw_value))
        except ValueError:
            pass

    @staticmethod
    def _normalize_time_var(variable: tk.StringVar) -> bool:
        try:
            variable.set(normalize_time_input(variable.get()))
        except ValueError:
            return False
        return True

    def _on_overtime_date_changed(self, _event: tk.Event | None = None) -> None:
        if self.editing_record_id is None:
            self._apply_default_start_time()

    def _apply_default_start_time(self) -> None:
        iso_date = self.date_display_to_iso.get(self.overtime_date_var.get())
        if iso_date:
            self.start_time_var.set(default_start_time(iso_date))

    def _legacy_build_monthly_records(self, parent: tk.Frame) -> None:
        shell = ttk.Frame(parent, style="Card.TFrame", padding=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        ttk.Label(shell, text="Blanko tersimpan", style="Title.Card.TLabel").grid(row=0, column=0, sticky="w")
        self.records_period_label = ttk.Label(shell, text="", style="Muted.Card.TLabel")
        self.records_period_label.grid(row=1, column=0, sticky="w", pady=(3, 10))

        table_frame = ttk.Frame(shell, style="Card.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.records_tree = ttk.Treeview(
            table_frame,
            columns=("tanggal", "jam", "jumlah"),
            show="headings",
            selectmode="browse",
            height=11,
        )
        self.records_tree.heading("tanggal", text="Tanggal")
        self.records_tree.heading("jam", text="Jam")
        self.records_tree.heading("jumlah", text="Pekerjaan")
        self.records_tree.column("tanggal", width=115, minwidth=100)
        self.records_tree.column("jam", width=105, minwidth=90, anchor="center")
        self.records_tree.column("jumlah", width=95, minwidth=80, anchor="center")
        self.records_tree.tag_configure("stripe", background=COLORS["surface_alt"])
        self.records_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.records_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.records_tree.configure(yscrollcommand=scrollbar.set)
        self.records_tree.bind("<Double-1>", lambda _event: self._edit_selected_record())

        record_actions = ttk.Frame(shell, style="Card.TFrame")
        record_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(record_actions, text="Edit", style="Secondary.TButton", command=self._edit_selected_record).pack(side="left")
        ttk.Button(record_actions, text="Hapus", style="Danger.TButton", command=self._delete_selected_record).pack(side="left", padx=(7, 0))

        info = tk.Frame(shell, bg=COLORS["soft_blue"], padx=12, pady=9)
        info.grid(row=4, column=0, sticky="ew", pady=(14, 10))
        tk.Label(
            info,
            text="Preview seluruh tanggal sebelum file Word disimpan.",
            bg=COLORS["soft_blue"],
            fg=COLORS["blue_dark"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=330,
        ).pack(anchor="w")

        self.generate_button = ttk.Button(
            shell,
            text="Rekap Harian",
            style="Success.TButton",
            command=self._preview_month,
        )
        self.generate_button.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.recap_button = ttk.Button(shell, text="Rekap Bulanan", style="Primary.TButton",
                                       command=self._save_monthly_recap)
        self.recap_button.grid(row=6, column=0, sticky="ew")

    def _load_forms(self) -> None:
        self.profile_name_var.set(self.profile.nama)
        self.profile_nip_var.set(self.profile.nip)
        self.profile_unit_var.set(self.profile.unit_kerja)
        month, year = parse_period(self.profile.bulan)
        self.profile_month_var.set(MONTH_NAMES[month - 1])
        self.profile_year_var.set(str(year))

        self.manager_name_var.set(self.officials.nama_manager)
        self.manager_nip_var.set(self.officials.nip_manager)
        self.asmen_name_var.set(self.officials.nama_asmen)
        self.asmen_nip_var.set(self.officials.nip_asmen)
        self.manager_role_var.set(self.officials.manager_unit_override or self.profile.unit_kerja)
        self.asmen_role_var.set(self.officials.asmen_unit_override or self.profile.unit_kerja)
        self._refresh_officials_titles()

    @staticmethod
    def _clean_nip(value: str) -> str:
        return re.sub(r"\s+", "", value.strip())

    @staticmethod
    def _nip_is_valid(value: str) -> bool:
        return bool(value) and value.isdigit()

    def _save_profile(self) -> None:
        self.profile_error.configure(text="")
        name = self.profile_name_var.get().strip()
        nip = self._clean_nip(self.profile_nip_var.get())
        unit = self.profile_unit_var.get().strip()
        month_name = self.profile_month_var.get().strip()
        year_text = self.profile_year_var.get().strip()
        if not name or not unit or not month_name or not year_text:
            self.profile_error.configure(text="Semua data profil wajib diisi.")
            return
        if not self._nip_is_valid(nip):
            self.profile_error.configure(text="NIP harus berisi angka saja.")
            return
        try:
            year = int(year_text)
            period = period_label(MONTH_NAMES.index(month_name) + 1, year)
        except (ValueError, IndexError):
            self.profile_error.configure(text="Bulan atau tahun tidak valid.")
            return

        self.profile = Profile(nama=name, nip=nip, unit_kerja=unit, bulan=period)
        self.store.save_profile(self.profile)
        self.profile_nip_var.set(nip)
        self._refresh_period_dependent_ui()
        self._set_status("Profil dan periode berhasil disimpan.")
        messagebox.showinfo("Profil tersimpan", "Data profil berhasil disimpan dan akan dipakai pada blanko berikutnya.")

    def _save_officials(self) -> None:
        self.officials_error.configure(text="")
        manager_name = self.manager_name_var.get().strip()
        manager_nip = self._clean_nip(self.manager_nip_var.get())
        asmen_name = self.asmen_name_var.get().strip()
        asmen_nip = self._clean_nip(self.asmen_nip_var.get())
        if not manager_name or not asmen_name:
            self.officials_error.configure(text="Nama manajer dan asisten manajer wajib diisi.")
            return
        if ((manager_nip and not self._nip_is_valid(manager_nip)) or
                (asmen_nip and not self._nip_is_valid(asmen_nip))):
            self.officials_error.configure(text="NIP harus berisi angka atau dikosongkan untuk pejabat non-ASN.")
            return

        manager_role = self.manager_role_var.get().strip()
        asmen_role = self.asmen_role_var.get().strip()
        if not manager_role or not asmen_role:
            self.officials_error.configure(text="Bidang/unit jabatan manajer dan asisten manajer wajib diisi.")
            return
        self.officials = Officials(
            nama_manager=manager_name,
            nip_manager=manager_nip,
            nama_asmen=asmen_name,
            nip_asmen=asmen_nip,
            manager_unit_override=manager_role,
            asmen_unit_override=asmen_role,
        )
        self.store.save_officials(self.officials)
        self.manager_nip_var.set(manager_nip)
        self.asmen_nip_var.set(asmen_nip)
        self._set_status("Data pejabat berhasil disimpan.")
        messagebox.showinfo("Data tersimpan", "Data pejabat penandatangan berhasil disimpan.")

    def _refresh_period_dependent_ui(self) -> None:
        self.header_period_label.configure(text=self.profile.bulan)
        self.records_period_label.configure(text=f"Periode {self.profile.bulan}")
        self._refresh_date_options()
        self._refresh_records_tree()
        self._refresh_metrics()

    def _refresh_date_options(self) -> None:
        choices = period_dates(self.profile.bulan)
        self.date_display_to_iso = {display: iso for iso, display in choices}
        displays = list(self.date_display_to_iso.keys())
        self.date_combo.configure(values=displays)
        current_display = self.overtime_date_var.get()
        if current_display in self.date_display_to_iso:
            return
        today_iso = date.today().isoformat()
        preferred = next((display for display, iso in self.date_display_to_iso.items() if iso == today_iso), displays[0])
        self.overtime_date_var.set(preferred)
        if self.editing_record_id is None:
            self._apply_default_start_time()

    def _current_period_records(self) -> list[OvertimeRecord]:
        return records_for_period(self.records, self.profile.bulan)

    def _refresh_metrics(self) -> None:
        records = self._current_period_records()
        total_jobs = sum(len(record.items) for record in records)
        total_minutes = sum(record.minutes for record in records)
        self.metric_blanko.configure(text=str(len(records)))
        self.metric_jobs.configure(text=str(total_jobs))
        self.metric_hours.configure(text=format_duration(total_minutes))
        self.generate_button.configure(state="normal" if records else "disabled")
        self.recap_button.configure(state="normal" if records else "disabled")

    def _refresh_records_tree(self) -> None:
        for item in self.records_tree.get_children():
            self.records_tree.delete(item)
        for record in self._current_period_records():
            row_index = len(self.records_tree.get_children())
            self.records_tree.insert(
                "",
                "end",
                iid=record.blanko_id,
                tags=(("stripe",) if row_index % 2 else ()),
                values=(
                    format_date_short(record.tanggal),
                    f"{record.jam_mulai}–{record.jam_selesai}",
                    f"{len(record.items)} baris",
                ),
            )

    def _add_or_update_item(self) -> None:
        self.blanko_error.configure(text="")
        job = self.job_var.get().strip()
        quantity = self.quantity_var.get().strip()
        note = self.note_var.get().strip()
        if not job or not quantity:
            self.blanko_error.configure(text="Pekerjaan dan kuantitas wajib diisi sebelum ditambahkan.")
            return
        if not self._quantity_input_is_valid(quantity):
            self.blanko_error.configure(text="Kuantitas hanya boleh berisi angka.")
            self.quantity_entry.focus_set()
            return
        if self.editing_item_index is None and len(self.draft_items) >= MAX_JOB_ROWS:
            self.blanko_error.configure(text=f"Maksimal {MAX_JOB_ROWS} pekerjaan dalam satu blanko.")
            return

        item = JobItem(pekerjaan=job, kuantitas=quantity, keterangan=note)
        if self.editing_item_index is None:
            self.draft_items.append(item)
        else:
            self.draft_items[self.editing_item_index] = item
        self._clear_item_editor()
        self._refresh_draft_tree()
        self.job_entry.focus_set()

    def _refresh_draft_tree(self) -> None:
        for child in self.draft_tree.get_children():
            self.draft_tree.delete(child)
        for index, item in enumerate(self.draft_items):
            self.draft_tree.insert(
                "",
                "end",
                iid=str(index),
                tags=(("stripe",) if index % 2 else ()),
                values=(index + 1, item.pekerjaan, item.kuantitas, item.keterangan),
            )
        self.item_counter_label.configure(text=f"{len(self.draft_items)} / {MAX_JOB_ROWS} baris")

    def _clear_item_editor(self) -> None:
        self.job_var.set("")
        self.quantity_var.set("")
        self.note_var.set("")
        self.editing_item_index = None
        self.add_item_button.configure(text="Tambah ke daftar")

    def _selected_draft_index(self) -> int | None:
        selection = self.draft_tree.selection()
        return int(selection[0]) if selection else None

    def _edit_selected_item(self) -> None:
        index = self._selected_draft_index()
        if index is None:
            messagebox.showwarning("Pilih pekerjaan", "Pilih satu baris pekerjaan yang ingin diedit.")
            return
        item = self.draft_items[index]
        self.editing_item_index = index
        self.job_var.set(item.pekerjaan)
        self.quantity_var.set(item.kuantitas)
        self.note_var.set(item.keterangan)
        self.add_item_button.configure(text="Simpan perubahan baris")
        self.job_entry.focus_set()

    def _delete_selected_item(self) -> None:
        index = self._selected_draft_index()
        if index is None:
            messagebox.showwarning("Pilih pekerjaan", "Pilih satu baris pekerjaan yang ingin dihapus.")
            return
        del self.draft_items[index]
        self._clear_item_editor()
        self._refresh_draft_tree()

    def _save_blanko(self) -> None:
        self.blanko_error.configure(text="")
        if self.job_var.get().strip() or self.quantity_var.get().strip() or self.note_var.get().strip():
            self._add_or_update_item()
            if self.job_var.get().strip() or self.quantity_var.get().strip() or self.note_var.get().strip():
                return

        for label, variable, entry in (
            ("Jam mulai", self.start_time_var, self.start_time_entry),
            ("Jam selesai", self.end_time_var, self.end_time_entry),
        ):
            if not self._normalize_time_var(variable):
                self.blanko_error.configure(text=f"{label} tidak valid. Ketik misalnya 1600 atau 16:00.")
                entry.focus_set()
                return

        display_date = self.overtime_date_var.get()
        iso_date = self.date_display_to_iso.get(display_date, "")
        record = OvertimeRecord(
            blanko_id=iso_date,
            tanggal=iso_date,
            jam_mulai=self.start_time_var.get().strip(),
            jam_selesai=self.end_time_var.get().strip(),
            items=list(self.draft_items),
        )
        try:
            validate_record(record, self.profile.bulan)
        except ValueError as exc:
            self.blanko_error.configure(text=str(exc))
            return

        duplicate = next(
            (
                existing
                for existing in self.records
                if existing.tanggal == iso_date and existing.blanko_id != self.editing_record_id
            ),
            None,
        )
        if duplicate is not None:
            replace = messagebox.askyesno(
                "Tanggal sudah pernah diisi",
                f"Blanko tanggal {format_date_id(iso_date)} sudah ada.\n\nGanti data lama dengan data yang baru?",
                icon="warning",
            )
            if not replace:
                return

        remove_ids = {identifier for identifier in (self.editing_record_id, duplicate.blanko_id if duplicate else None) if identifier}
        self.records = [existing for existing in self.records if existing.blanko_id not in remove_ids]
        self.records.append(record)
        self.records.sort(key=lambda item: item.tanggal)
        self.store.save_records(self.records)
        saved_date = format_date_id(record.tanggal)
        was_edit = self.editing_record_id is not None or duplicate is not None
        self._reset_blanko_form()
        self._refresh_records_tree()
        self._refresh_metrics()
        self._set_status(f"Blanko {saved_date} berhasil {'diperbarui' if was_edit else 'disimpan'}.")

    def _selected_record(self) -> OvertimeRecord | None:
        selection = self.records_tree.selection()
        if not selection:
            return None
        record_id = selection[0]
        return next((record for record in self.records if record.blanko_id == record_id), None)

    def _edit_selected_record(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showwarning("Pilih blanko", "Pilih satu tanggal yang ingin diedit.")
            return
        self.editing_record_id = record.blanko_id
        self.draft_items = [JobItem(item.pekerjaan, item.kuantitas, item.keterangan) for item in record.items]
        display = next((display for display, iso in self.date_display_to_iso.items() if iso == record.tanggal), "")
        self.overtime_date_var.set(display)
        self.start_time_var.set(record.jam_mulai)
        self.end_time_var.set(record.jam_selesai)
        self._refresh_draft_tree()
        self._clear_item_editor()
        self.edit_mode_label.configure(text="EDIT", bg=COLORS["amber_soft"], fg=COLORS["amber"])
        self.save_blanko_button.configure(text="Simpan perubahan")
        self.cancel_edit_button.pack(side="left")
        self._set_status(f"Mengedit blanko {format_date_id(record.tanggal)}.")

    def _delete_selected_record(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showwarning("Pilih blanko", "Pilih satu tanggal yang ingin dihapus.")
            return
        confirmed = messagebox.askyesno(
            "Hapus blanko",
            f"Hapus blanko tanggal {format_date_id(record.tanggal)}?\n\nTindakan ini akan menghapus seluruh baris pekerjaan pada tanggal tersebut.",
            icon="warning",
        )
        if not confirmed:
            return
        self.records = [item for item in self.records if item.blanko_id != record.blanko_id]
        self.store.save_records(self.records)
        if self.editing_record_id == record.blanko_id:
            self._reset_blanko_form()
        self._refresh_records_tree()
        self._refresh_metrics()
        self._set_status(f"Blanko {format_date_id(record.tanggal)} dihapus.")

    def _reset_blanko_form(self) -> None:
        self.editing_record_id = None
        self.editing_item_index = None
        self.draft_items = []
        self.start_time_var.set("16:00")
        self.end_time_var.set("18:00")
        self.blanko_error.configure(text="")
        self._clear_item_editor()
        self._refresh_draft_tree()
        self.edit_mode_label.configure(text="BARU", bg=COLORS["soft_blue"], fg=COLORS["blue"])
        self.save_blanko_button.configure(text="Simpan blanko")
        self.cancel_edit_button.pack_forget()
        self._select_first_available_date()

    def _select_first_available_date(self) -> None:
        used = {record.tanggal for record in self._current_period_records()}
        for display, iso in self.date_display_to_iso.items():
            if iso not in used:
                self.overtime_date_var.set(display)
                self._apply_default_start_time()
                return
        if self.date_display_to_iso:
            self.overtime_date_var.set(next(iter(self.date_display_to_iso)))
            self._apply_default_start_time()

    def _profile_complete(self) -> bool:
        return all((self.profile.nama.strip(), self.profile.nip.strip(), self.profile.unit_kerja.strip()))

    def _officials_complete(self) -> bool:
        return all(
            (
                self.officials.nama_manager.strip(),
                self.officials.nama_asmen.strip(),
            )
        )

    def _preview_month(self) -> None:
        records = self._current_period_records()
        if not records:
            messagebox.showwarning("Belum ada data", f"Belum ada blanko untuk periode {self.profile.bulan}.")
            return
        if not self._profile_complete():
            messagebox.showwarning("Profil belum lengkap", "Lengkapi dan simpan profil pegawai sebelum membuat Word.")
            self.notebook.select(self.profile_tab)
            return
        if not self._officials_complete():
            messagebox.showwarning("Data pejabat belum lengkap", "Lengkapi dan simpan data pejabat sebelum membuat Word.")
            self.notebook.select(self.officials_tab)
            return
        PreviewDialog(self, records, self._save_word)

    def _save_monthly_recap(self) -> None:
        records = self._current_period_records()
        if not records:
            messagebox.showwarning("Belum ada data", f"Belum ada blanko untuk periode {self.profile.bulan}.", parent=self)
            return
        if not self._profile_complete():
            messagebox.showwarning("Profil belum lengkap", "Lengkapi dan simpan profil sebelum membuat rekap.", parent=self)
            self.notebook.select(self.profile_tab)
            return
        if not self._officials_complete():
            messagebox.showwarning("Data pejabat belum lengkap", "Lengkapi dan simpan nama pejabat sebelum membuat rekap.", parent=self)
            self.notebook.select(self.officials_tab)
            return
        if self._has_unsaved_update_input():
            messagebox.showwarning("Simpan perubahan dahulu",
                                   "Simpan atau batalkan perubahan pada Profil, Pejabat, dan blanko. "
                                   "Rekap bulanan menggunakan data yang sudah disimpan.", parent=self)
            return
        destination = filedialog.asksaveasfilename(
            parent=self, title="Simpan Rekap Lembur Bulanan", defaultextension=".docx",
            initialfile=safe_filename(f"Rekap Lembur Bulan {self.profile.bulan}") + ".docx",
            filetypes=(("Dokumen Word", "*.docx"), ("Semua file", "*.*")),
        )
        if not destination:
            self._set_status("Pembuatan rekap bulanan dibatalkan.")
            return
        try:
            generate_monthly_recap(RECAP_TEMPLATE_PATH, Path(destination), self.profile, self.officials, records)
        except PermissionError:
            messagebox.showerror("File sedang digunakan",
                                 "Tutup file tujuan jika sedang dibuka di Word, lalu coba simpan kembali.", parent=self)
            return
        except Exception as exc:
            messagebox.showerror("Rekap bulanan gagal dibuat", str(exc), parent=self)
            return
        total_jobs = sum(len(record.items) for record in records)
        self._set_status(f"Rekap bulanan dibuat: {Path(destination).name}")
        messagebox.showinfo("Rekap bulanan selesai",
                            f"Rekap {self.profile.bulan} berhasil dibuat.\n\n{destination}\n\n"
                            f"{len(records)} hari lembur · {total_jobs} pekerjaan.", parent=self)

    def _save_word(self, records: list[OvertimeRecord]) -> None:
        default_name = safe_filename(f"Blanko Lembur - {self.profile.bulan}") + ".docx"
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Simpan Word Blanko Lembur",
            defaultextension=".docx",
            initialfile=default_name,
            filetypes=(("Dokumen Word", "*.docx"), ("Semua file", "*.*")),
        )
        if not destination:
            self._set_status("Pembuatan Word dibatalkan.")
            return
        try:
            generate_word(
                template_path=TEMPLATE_PATH,
                output_path=Path(destination),
                profile=self.profile,
                officials=self.officials,
                records=records,
            )
        except PermissionError:
            messagebox.showerror(
                "File sedang digunakan",
                "Word tidak dapat disimpan karena file tujuan sedang dibuka. Tutup file tersebut lalu coba lagi.",
            )
            return
        except Exception as exc:
            messagebox.showerror("Word gagal dibuat", f"Dokumen tidak dapat dibuat.\n\n{exc}")
            return
        self._set_status(f"Word berhasil dibuat: {Path(destination).name}")
        messagebox.showinfo(
            "Word siap dicetak",
            f"Dokumen berhasil dibuat.\n\n{destination}\n\nJumlah halaman: {len(records)}",
        )

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        selected = self.notebook.select()
        if not selected:
            return
        tab_text = self.notebook.tab(selected, "text")
        self._set_status(f"Membuka {tab_text.split('   ')[-1]}.")

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _focus_daily_form(self) -> None:
        self.date_combo.focus_set()

    # The tab layouts live in ui/*_tab.py. Keeping these small adapters here
    # makes the application coordinator easy to read while preserving the
    # existing callback and data model methods above.
    def _build_profile_tab(self) -> None:
        build_profile_tab_ui(self)

    def _build_officials_tab(self) -> None:
        build_officials_tab_ui(self)

    def _build_blanko_tab(self) -> None:
        build_blanko_tab_ui(self)

    def _build_info_tab(self) -> None:
        build_info_tab_ui(self)


class PreviewDialog(tk.Toplevel):
    def __init__(
        self,
        parent: BlankoLemburApp,
        records: list[OvertimeRecord],
        on_confirm,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.records = records
        self.on_confirm = on_confirm
        self.title(f"Preview Word - {parent.profile.bulan}")
        self.geometry("960x610")
        self.minsize(820, 520)
        self.configure(bg=COLORS["background"])
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._center_over_parent()
        self._build()

    def _center_over_parent(self) -> None:
        self.update_idletasks()
        width, height = 960, 610
        x = self.parent.winfo_rootx() + max(0, (self.parent.winfo_width() - width) // 2)
        y = self.parent.winfo_rooty() + max(0, (self.parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build(self) -> None:
        header = tk.Frame(
            self,
            bg=COLORS["surface"],
            padx=24,
            pady=16,
            highlightbackground=COLORS["line"],
            highlightthickness=1,
        )
        header.pack(fill="x")
        copy = tk.Frame(header, bg=COLORS["surface"])
        copy.pack(side="left")
        tk.Label(
            copy,
            text="PREVIEW DOKUMEN",
            bg=COLORS["surface"],
            fg=COLORS["blue"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        tk.Label(
            copy,
            text=f"Blanko Lembur • {self.parent.profile.bulan}",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w", pady=(3, 0))

        total_jobs = sum(len(record.items) for record in self.records)
        total_minutes = sum(record.minutes for record in self.records)
        summary = tk.Label(
            header,
            text=f"{len(self.records)} halaman   •   {total_jobs} pekerjaan   •   {format_duration(total_minutes)}",
            bg=COLORS["soft_blue"],
            fg=COLORS["blue_dark"],
            font=("Segoe UI Semibold", 9),
            padx=15,
            pady=9,
        )
        summary.pack(side="right")

        shell = ttk.Frame(self, padding=20)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        ttk.Label(
            shell,
            text="Periksa seluruh tanggal dan pekerjaan. Setiap tanggal akan menjadi satu halaman baru.",
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        table_frame = ttk.Frame(shell)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            table_frame,
            columns=("tanggal", "jam", "no", "pekerjaan", "kuantitas", "keterangan"),
            show="headings",
        )
        headings = {
            "tanggal": "Tanggal",
            "jam": "Jam",
            "no": "No.",
            "pekerjaan": "Pekerjaan",
            "kuantitas": "Kuantitas",
            "keterangan": "Keterangan",
        }
        for column, heading in headings.items():
            tree.heading(column, text=heading)
        tree.column("tanggal", width=105, minwidth=90)
        tree.column("jam", width=100, minwidth=85, anchor="center")
        tree.column("no", width=45, minwidth=40, anchor="center", stretch=False)
        tree.column("pekerjaan", width=300, minwidth=180)
        tree.column("kuantitas", width=100, minwidth=80, anchor="center")
        tree.column("keterangan", width=190, minwidth=120)
        tree.tag_configure("stripe", background=COLORS["surface_alt"])
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        preview_row = 0
        for record in self.records:
            for index, item in enumerate(record.items, start=1):
                tree.insert(
                    "",
                    "end",
                    tags=(("stripe",) if preview_row % 2 else ()),
                    values=(
                        format_date_short(record.tanggal) if index == 1 else "",
                        f"{record.jam_mulai}–{record.jam_selesai}" if index == 1 else "",
                        index,
                        item.pekerjaan,
                        item.kuantitas,
                        item.keterangan,
                    ),
                )
                preview_row += 1

        note = tk.Frame(shell, bg=COLORS["green_soft"], padx=12, pady=8)
        note.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        tk.Label(
            note,
            text="Kolom Hasil Output Ada/Tidak tetap kosong dan dapat dicentang setelah dicetak.",
            bg=COLORS["green_soft"],
            fg="#087C5E",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        actions = ttk.Frame(shell)
        actions.grid(row=3, column=0, sticky="e", pady=(15, 0))
        ttk.Button(actions, text="Kembali", style="Secondary.TButton", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Simpan sebagai Word", style="Success.TButton", command=self._confirm).pack(side="left")

    def _confirm(self) -> None:
        records = self.records
        self.destroy()
        self.parent.after(50, lambda: self.on_confirm(records))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--apply-update":
        if len(sys.argv) != 4:
            raise SystemExit(2)
        raise SystemExit(updater.apply_update(Path(sys.argv[2]), Path(sys.argv[3])))
    ready_marker = None
    if len(sys.argv) > 1 and sys.argv[1] == "--update-ready":
        if len(sys.argv) != 3:
            raise SystemExit(2)
        ready_marker = Path(sys.argv[2])
    updater.cleanup_updates()
    app = BlankoLemburApp()
    if ready_marker is not None:
        def acknowledge_update():
            try:
                updater.confirm_update_ready(ready_marker)
            except (updater.UpdateError, OSError):
                # Let the helper restore the previous application if startup
                # cannot prove this is the expected signed version.
                app.destroy()
        app.after(200, acknowledge_update)
    app.mainloop()
