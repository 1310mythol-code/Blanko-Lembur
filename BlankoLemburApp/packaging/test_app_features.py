"""Tk integration checks using isolated workspace data and mocked dialogs/network."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from xml.dom import minidom

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import blanko_lembur as gui  # noqa: E402
from core import JobItem, Officials, OvertimeRecord, Profile, W_NS  # noqa: E402


def widget_texts(widget):
    result = []
    if "text" in widget.keys():
        result.append(str(widget.cget("text")))
    for child in widget.winfo_children():
        result.extend(widget_texts(child))
    return result


def document_text(path):
    with zipfile.ZipFile(path) as archive:
        document = minidom.parseString(archive.read("word/document.xml"))
    return [
        "".join(child.data for child in node.childNodes if child.nodeType == child.TEXT_NODE)
        for node in document.getElementsByTagNameNS(W_NS, "t")
    ]


class AppFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="gui-test-", dir=APP_DIR / "packaging"
        )
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.patch(gui, "DATA_DIR", self.directory / "data")
        self.patch(gui.updater, "is_configured", return_value=False)
        self.check_update = self.patch(gui.updater, "check_for_update")
        self.download_update = self.patch(gui.updater, "download_update")
        self.launch_update = self.patch(gui.updater, "launch_update")
        self.showinfo = self.patch(gui.messagebox, "showinfo")
        self.showwarning = self.patch(gui.messagebox, "showwarning")
        self.showerror = self.patch(gui.messagebox, "showerror")
        self.askyesno = self.patch(gui.messagebox, "askyesno", return_value=False)
        self.destination = self.directory / "hasil.docx"
        self.save_dialog = self.patch(
            gui.filedialog, "asksaveasfilename", return_value=str(self.destination)
        )
        # Withdraw before the constructor's centering step can map a real window.
        self.patch(
            gui.BlankoLemburApp,
            "_center_window",
            autospec=True,
            side_effect=lambda app: app.withdraw(),
        )
        self.app = gui.BlankoLemburApp()
        self.app.withdraw()
        self.addCleanup(self.close_app)

    def patch(self, target, attribute, *args, **kwargs):
        patcher = mock.patch.object(target, attribute, *args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def close_app(self):
        for callback in self.app.tk.call("after", "info"):
            self.app.after_cancel(callback)
        self.app.destroy()

    def save_complete_profile(self):
        self.app.profile_name_var.set("Pegawai Pengujian")
        self.app.profile_nip_var.set("00123456789")
        self.app.profile_unit_var.set("Instalasi Gizi")
        self.app.profile_month_var.set("September")
        self.app.profile_year_var.set("2026")
        self.app._save_profile()
        self.assertEqual(str(self.app.profile_error.cget("text")), "")
        self.assertTrue(self.app._profile_complete())

    def save_officials_without_nips(self):
        self.app.manager_name_var.set("Manajer Pengujian")
        self.app.asmen_name_var.set("Asisten Pengujian")
        self.app.manager_nip_var.set("   ")
        self.app.asmen_nip_var.set("")
        self.app._save_officials()
        self.assertEqual(str(self.app.officials_error.cget("text")), "")
        self.assertTrue(self.app._officials_complete())
        self.assertEqual(self.app.store.load_officials().nip_manager, "")
        self.assertEqual(self.app.store.load_officials().nip_asmen, "")

    def save_daily_records(self):
        self.app.records = [
            OvertimeRecord("september-1", "2026-09-01", "16:00", "20:00", [
                JobItem("Menyusun laporan", "1 dokumen"),
                JobItem("Memeriksa bukti", "3 berkas"),
            ]),
            OvertimeRecord("september-2", "2026-09-02", "16:30", "18:30", [
                JobItem("Rekonsiliasi data", "2 daftar"),
            ]),
            OvertimeRecord("august-1", "2026-08-31", "16:00", "18:00", [
                JobItem("Pekerjaan bulan sebelumnya", "1 berkas"),
            ]),
        ]
        self.app.store.save_records(self.app.records)
        self.app._refresh_period_dependent_ui()

    def test_info_tab_has_requested_content_and_update_action(self):
        self.assertEqual(
            [self.app.notebook.tab(tab, "text") for tab in self.app.notebook.tabs()],
            ["Profil", "Pejabat", "Blanko Lembur", "Info aplikasi"],
        )
        labels = widget_texts(self.app.info_tab)
        for expected in (
            "Aplikasi Ini dibuat oleh NAM",
            "Versi aplikasi: 1.0",
            "Aplikasi ini dibuat untuk pegawai RSUP Dr M Djamil",
            "Cek untuk Update",
        ):
            self.assertIn(expected, labels)
        self.assertFalse(self.app.install_update_button.winfo_manager())

    def test_optional_nips_allow_saving_preview_and_word_callback(self):
        self.save_complete_profile()
        self.save_officials_without_nips()
        self.app.job_var.set("Menyelesaikan laporan unit")
        self.app.quantity_var.set("1")
        self.app.end_time_var.set("20:00")
        self.app._save_blanko()
        self.assertEqual(len(self.app.records), 1)
        self.assertEqual(len(self.app.store.load_records()), 1)
        with mock.patch.object(gui, "PreviewDialog") as preview:
            self.app._preview_month()
            preview.assert_called_once_with(self.app, self.app.records, self.app._save_word)
        self.app._save_word(self.app.records)
        self.assertTrue(self.destination.is_file())
        content = document_text(self.destination)
        self.assertIn("Manajer Instalasi Gizi", content)
        self.assertIn("Asisten Manajer Instalasi Gizi", content)
        self.assertFalse(any(part.startswith("NIP ") for part in content))
        self.showerror.assert_not_called()
        self.showwarning.assert_not_called()

    def test_invalid_nonempty_official_nip_rejected_without_data_change(self):
        self.save_officials_without_nips()
        expected_data = self.app.store.officials_path.read_bytes()
        for field in (self.app.manager_nip_var, self.app.asmen_nip_var):
            with self.subTest(field=str(field)):
                field.set("123abc")
                self.app._save_officials()
                self.assertIn("angka", str(self.app.officials_error.cget("text")))
                self.assertEqual(self.app.store.officials_path.read_bytes(), expected_data)
                field.set("")

    def test_official_titles_follow_unit_change_and_saved_profile(self):
        self.save_complete_profile()
        self.app.profile_unit_var.set("  Instalasi Farmasi & Pelayanan  ")
        self.assertEqual(
            str(self.app.manager_title_label.cget("text")),
            "Manajer Instalasi Farmasi & Pelayanan",
        )
        self.assertEqual(
            str(self.app.asmen_title_label.cget("text")),
            "Asisten Manajer Instalasi Farmasi & Pelayanan",
        )
        self.app._save_profile()
        self.assertEqual(self.app.store.load_profile().unit_kerja, "Instalasi Farmasi & Pelayanan")

    def test_manual_roles_are_independent_persist_and_can_follow_unit_again(self):
        self.save_complete_profile()
        self.save_officials_without_nips()
        for manual, follow, entry, label, other_label, override_name, prefix in (
            (self.app.manager_role_var, self.app.manager_follow_unit_var,
             self.app.manager_role_entry, self.app.manager_title_label,
             self.app.asmen_title_label, "manager_unit_override", "Manajer"),
            (self.app.asmen_role_var, self.app.asmen_follow_unit_var,
             self.app.asmen_role_entry, self.app.asmen_title_label,
             self.app.manager_title_label, "asmen_unit_override", "Asisten Manajer"),
        ):
            with self.subTest(role=prefix):
                self.assertEqual(str(entry.cget("state")), "readonly")
                follow.set(False)
                self.assertEqual(str(entry.cget("state")), "normal")
                manual.set("  Pelayanan & Operasional  ")
                self.assertTrue(self.app._has_unsaved_update_input())
                self.app._save_officials()
                self.assertFalse(self.app._has_unsaved_update_input())
                stored = self.app.store.load_officials()
                self.assertEqual(getattr(stored, override_name), "Pelayanan & Operasional")
                self.app.officials = stored
                self.app._load_forms()
                self.assertFalse(follow.get())
                self.assertEqual(manual.get(), "Pelayanan & Operasional")
                self.app.profile_unit_var.set("Unit Baru")
                self.assertEqual(str(label.cget("text")), f"{prefix} Pelayanan & Operasional")
                self.assertTrue(str(other_label.cget("text")).endswith("Unit Baru"))
                self.app._save_profile()
                self.assertFalse(self.app._has_unsaved_update_input())
                follow.set(True)
                self.assertEqual(manual.get(), "Unit Baru")
                self.app._save_officials()
                self.assertEqual(getattr(self.app.store.load_officials(), override_name), "")
                self.app.officials = self.app.store.load_officials()
                self.app._load_forms()
                self.assertTrue(follow.get())

    def test_empty_manual_role_is_rejected_without_overwriting_saved_officials(self):
        self.save_complete_profile()
        self.save_officials_without_nips()
        original = self.app.store.officials_path.read_bytes()
        for follow, role in (
            (self.app.manager_follow_unit_var, self.app.manager_role_var),
            (self.app.asmen_follow_unit_var, self.app.asmen_role_var),
        ):
            with self.subTest(role=str(role)):
                follow.set(False)
                role.set("   ")
                self.app._save_officials()
                self.assertIn("manual", str(self.app.officials_error.cget("text")))
                self.assertTrue(self.app._has_unsaved_update_input())
                self.assertEqual(self.app.store.officials_path.read_bytes(), original)
                self.app._load_forms()

    def test_separate_export_buttons_create_daily_and_monthly_documents(self):
        self.assertEqual(str(self.app.generate_button.cget("text")), "Rekap Harian")
        self.assertEqual(str(self.app.recap_button.cget("text")), "Rekap Bulanan")
        self.assertEqual(str(self.app.generate_button.cget("state")), "disabled")
        self.assertEqual(str(self.app.recap_button.cget("state")), "disabled")
        self.save_complete_profile()
        self.save_officials_without_nips()
        self.app.manager_follow_unit_var.set(False)
        self.app.manager_role_var.set("Keuangan & Perencanaan")
        self.app._save_officials()
        self.save_daily_records()
        self.assertEqual(str(self.app.generate_button.cget("state")), "normal")
        self.assertEqual(str(self.app.recap_button.cget("state")), "normal")
        daily = self.directory / "harian.docx"
        monthly = self.directory / "bulanan.docx"
        self.save_dialog.side_effect = [str(daily), str(monthly)]
        with mock.patch.object(gui, "PreviewDialog") as preview:
            self.app.generate_button.invoke()
            preview.assert_called_once_with(self.app, self.app.records[:2], self.app._save_word)
            preview.call_args.args[2](preview.call_args.args[1])
            self.app.recap_button.invoke()
            self.assertEqual(preview.call_count, 1)
        for path in (daily, monthly):
            self.assertTrue(path.is_file())
            content = document_text(path)
            self.assertIn("Manajer Keuangan & Perencanaan", content)
            self.assertIn("Asisten Manajer Instalasi Gizi", content)
            self.assertNotIn("Pekerjaan bulan sebelumnya", content)
            self.assertFalse(any(part.startswith("NIP ") for part in content))
        monthly_content = document_text(monthly)
        self.assertEqual(monthly_content.count("01/09/2026"), 2)
        self.assertEqual(monthly_content.count("16.00-20.00"), 2)
        self.assertIn("02/09/2026", monthly_content)
        self.assertEqual(self.save_dialog.call_args.kwargs["initialfile"],
                         "Rekap Lembur Bulan September 2026.docx")
        self.assertEqual(self.showinfo.call_args.args[0], "Rekap bulanan selesai")
        self.assertIn("2 hari lembur", self.showinfo.call_args.args[1])
        self.assertIn("3 pekerjaan", self.showinfo.call_args.args[1])
        self.showerror.assert_not_called()
        self.showwarning.assert_not_called()

    def test_monthly_export_guards_incomplete_and_unsaved_data(self):
        self.app._save_monthly_recap()
        self.assertEqual(self.showwarning.call_args.args[0], "Belum ada data")
        self.save_complete_profile()
        self.save_daily_records()
        self.app.profile = Profile(bulan="September 2026")
        self.app._save_monthly_recap()
        self.assertEqual(self.showwarning.call_args.args[0], "Profil belum lengkap")
        self.assertEqual(self.app.notebook.select(), str(self.app.profile_tab))
        self.app.profile = self.app.store.load_profile()
        self.app.officials = Officials(nama_manager="", nama_asmen="")
        self.app._save_monthly_recap()
        self.assertEqual(self.showwarning.call_args.args[0], "Data pejabat belum lengkap")
        self.assertEqual(self.app.notebook.select(), str(self.app.officials_tab))
        self.save_officials_without_nips()
        mutations = (
            lambda: self.app.profile_unit_var.set("Perubahan belum disimpan"),
            lambda: self.app.manager_name_var.set("Nama baru"),
            lambda: self.app.asmen_follow_unit_var.set(False),
            lambda: self.app.job_var.set("Pekerjaan belum disimpan"),
            lambda: self.app.draft_items.append(JobItem("Draf", "1")),
            lambda: setattr(self.app, "editing_record_id", "september-1"),
        )
        with mock.patch.object(gui, "generate_monthly_recap") as generate:
            for mutate in mutations:
                with self.subTest(mutation=mutate):
                    self.app._load_forms()
                    self.app._reset_blanko_form()
                    mutate()
                    self.app._save_monthly_recap()
                    self.assertEqual(self.showwarning.call_args.args[0], "Simpan perubahan dahulu")
                    self.save_dialog.assert_not_called()
                    generate.assert_not_called()

    def test_monthly_export_cancel_and_write_failure_do_not_report_success(self):
        self.save_complete_profile()
        self.save_officials_without_nips()
        self.save_daily_records()
        self.showinfo.reset_mock()
        with mock.patch.object(gui, "generate_monthly_recap") as generate:
            self.save_dialog.return_value = ""
            self.app.recap_button.invoke()
            generate.assert_not_called()
            self.showinfo.assert_not_called()
            self.save_dialog.return_value = str(self.destination)
            generate.side_effect = PermissionError("File sedang terbuka")
            self.app.recap_button.invoke()
            self.assertEqual(self.showerror.call_args.args[0], "File sedang digunakan")
            self.showinfo.assert_not_called()

    def test_unconfigured_update_check_is_friendly_and_does_not_use_network(self):
        self.app.check_update_button.invoke()
        self.assertIn("belum diaktifkan", self.app.update_status_var.get())
        self.assertIn("tetap dapat digunakan", self.app.update_status_var.get())
        self.showinfo.assert_called_once()
        self.check_update.assert_not_called()
        self.download_update.assert_not_called()
        self.launch_update.assert_not_called()
        self.assertFalse(self.app._update_busy)
        self.assertFalse(self.app.install_update_button.winfo_manager())

    def test_unsaved_forms_prevent_download_and_install(self):
        self.assertFalse(self.app._has_unsaved_update_input())
        self.app._available_update = SimpleNamespace(version="1.1", notes="Fitur baru")
        self.patch(gui, "IS_FROZEN", True)
        mutations = (
            lambda: self.app.profile_unit_var.set("Unit belum disimpan"),
            lambda: self.app.manager_name_var.set("Nama belum disimpan"),
            lambda: self.app.job_var.set("Pekerjaan belum disimpan"),
            lambda: self.app.draft_items.append(JobItem("Draf pekerjaan", "1")),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.app._load_forms()
                self.app._reset_blanko_form()
                self.assertFalse(self.app._has_unsaved_update_input())
                mutate()
                self.app._download_available_update()
                self.download_update.assert_not_called()
                self.app._offer_install_update(self.directory / "update.exe")
                self.launch_update.assert_not_called()
                self.askyesno.assert_not_called()
                self.assertEqual(self.showinfo.call_args.args[0], "Simpan pekerjaan dahulu")


if __name__ == "__main__":
    unittest.main(verbosity=2)
