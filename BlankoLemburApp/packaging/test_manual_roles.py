"""Regressions for automatic/manual official units and existing saved data."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.dom import minidom

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from core import (  # noqa: E402
    DataStore,
    JobItem,
    Officials,
    OvertimeRecord,
    Profile,
    W_NS,
    generate_word,
    official_role_titles,
)
from recap import generate_monthly_recap  # noqa: E402


def children(node, name):
    return [child for child in node.childNodes if child.localName == name]


def text(node):
    return "".join(
        child.data
        for element in node.getElementsByTagNameNS(W_NS, "t")
        for child in element.childNodes
        if child.nodeType == child.TEXT_NODE
    )


class ManualRoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="manual-role-test-", dir=APP_DIR / "packaging"
        )
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.profile = Profile("Pegawai Uji", "001234", "Instalasi Gizi", "September 2026")

    def test_old_four_column_csv_loads_automatic_without_rewriting_any_data(self):
        store = DataStore(self.directory)
        store.save_profile(self.profile)
        store.officials_path.write_text(
            "nama_manager;nip_manager;nama_asmen;nip_asmen\n"
            "Manajer Lama;001234;Asisten Lama;\n",
            encoding="utf-8-sig",
        )
        original = {path: path.read_bytes() for path in self.directory.glob("*.csv")}
        reopened = DataStore(self.directory)
        officials = reopened.load_officials()
        self.assertEqual(officials, Officials("Manajer Lama", "001234", "Asisten Lama", ""))
        self.assertEqual(
            official_role_titles(reopened.load_profile(), officials),
            ("Manajer Instalasi Gizi", "Asisten Manajer Instalasi Gizi"),
        )
        self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_saved_manual_units_and_optional_nips_survive_reopening(self):
        store = DataStore(self.directory)
        officials = Officials(
            "Manajer Uji", "", "Asisten Uji", "001234",
            'Pelayanan & "Pendukung"; Umum', "Verifikasi dan Tarif",
        )
        original_profile = store.profile_path.read_bytes()
        original_records = store.records_path.read_bytes()
        store.save_officials(officials)
        self.assertEqual(DataStore(self.directory).load_officials(), officials)
        with store.officials_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=";"))
        self.assertEqual(tuple(rows[0]), DataStore.OFFICIAL_HEADERS)
        self.assertEqual(rows[1][-2:], [officials.manager_unit_override, officials.asmen_unit_override])
        self.assertEqual(store.profile_path.read_bytes(), original_profile)
        self.assertEqual(store.records_path.read_bytes(), original_records)

    def test_manual_units_are_independent_and_ignore_surrounding_spaces(self):
        for manager, assistant, expected in (
            ("", "", ("Manajer Instalasi Gizi", "Asisten Manajer Instalasi Gizi")),
            ("  Pelayanan  ", "", ("Manajer Pelayanan", "Asisten Manajer Instalasi Gizi")),
            ("", "  Tarif  ", ("Manajer Instalasi Gizi", "Asisten Manajer Tarif")),
            ("Pelayanan", "Tarif", ("Manajer Pelayanan", "Asisten Manajer Tarif")),
            ("   ", "\t", ("Manajer Instalasi Gizi", "Asisten Manajer Instalasi Gizi")),
        ):
            with self.subTest(manager=manager, assistant=assistant):
                officials = Officials(manager_unit_override=manager, asmen_unit_override=assistant)
                self.assertEqual(official_role_titles(self.profile, officials), expected)

    def test_unit_changes_follow_automatic_roles_and_cleared_override_restores_following(self):
        for manual_field, expected in (
            ("manager_unit_override", ("Manajer Unit Khusus", "Asisten Manajer Unit Baru")),
            ("asmen_unit_override", ("Manajer Unit Baru", "Asisten Manajer Unit Khusus")),
        ):
            with self.subTest(manual_field=manual_field):
                self.profile.unit_kerja = "Instalasi Gizi"
                officials = Officials(**{manual_field: "Unit Khusus"})
                self.profile.unit_kerja = " Unit Baru "
                self.assertEqual(official_role_titles(self.profile, officials), expected)
                setattr(officials, manual_field, "")
                self.assertEqual(
                    official_role_titles(self.profile, officials),
                    ("Manajer Unit Baru", "Asisten Manajer Unit Baru"),
                )

    def test_blank_profile_unit_does_not_leave_trailing_spaces(self):
        self.profile.unit_kerja = "  "
        self.assertEqual(
            official_role_titles(self.profile, Officials()), ("Manajer", "Asisten Manajer")
        )

    def test_both_word_formats_use_manual_roles_and_keep_optional_nips(self):
        records = [
            OvertimeRecord(
                f"day-{day}", f"2026-09-{day:02d}", "16:00", "18:00",
                [JobItem(f"Laporan hari {day}", "1 dokumen")],
            )
            for day in (7, 8)
        ]
        for generator, filename, signature_count in (
            (generate_word, "blanko_template.docx", 2),
            (generate_monthly_recap, "REKAP LEMBUR BULAN.docx", 1),
        ):
            template = APP_DIR / filename
            original_template = template.read_bytes()
            for manager, assistant in (("", "Tarif <A> & B"), ("Pelayanan & BMN", ""), ("Pelayanan & BMN", "Tarif <A> & B")):
                with self.subTest(format=filename, manager=manager, assistant=assistant):
                    officials = Officials("Manajer Uji", "", "Asisten Uji", "001234", manager, assistant)
                    output = self.directory / "output.docx"
                    generator(template, output, self.profile, officials, records)
                    with zipfile.ZipFile(output) as archive:
                        document = minidom.parseString(archive.read("word/document.xml"))
                    try:
                        body = document.getElementsByTagNameNS(W_NS, "body")[0]
                        tables = children(body, "tbl")[2::3]
                        self.assertEqual(len(tables), signature_count)
                        expected_roles = official_role_titles(self.profile, officials)
                        for table in tables:
                            rows = children(table, "tr")
                            roles = children(rows[1], "tc")
                            self.assertEqual((text(roles[0]), text(roles[2])), expected_roles)
                            self.assertEqual(
                                [text(cell) for cell in children(rows[5], "tc")],
                                ["Manajer Uji", "", "Asisten Uji"],
                            )
                            self.assertEqual(
                                [text(cell) for cell in children(rows[6], "tc")],
                                ["", "", "NIP 001234"],
                            )
                        self.assertFalse(document.getElementsByTagNameNS(W_NS, "highlight"))
                    finally:
                        document.unlink()
                    self.assertEqual(template.read_bytes(), original_template)


if __name__ == "__main__":
    unittest.main(verbosity=2)
