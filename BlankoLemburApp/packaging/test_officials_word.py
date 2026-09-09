"""Regression checks for optional official NIPs and unit-specific Word signatures."""

from __future__ import annotations

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
)


def children(node, name):
    return [child for child in node.childNodes if child.localName == name]


def text(node):
    return "".join(
        child.data
        for element in node.getElementsByTagNameNS(W_NS, "t")
        for child in element.childNodes
        if child.nodeType == child.TEXT_NODE
    )


def signature_tables(path):
    with zipfile.ZipFile(path) as archive:
        document = minidom.parseString(archive.read("word/document.xml"))
    body = document.getElementsByTagNameNS(W_NS, "body")[0]
    return children(body, "tbl")[2::3]


class OfficialsWordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="blanko-officials-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.template = APP_DIR / "blanko_template.docx"
        self.profile = Profile(
            nama="Pegawai Uji",
            nip="123456789",
            unit_kerja="Instalasi Gizi & Pelayanan",
            bulan="September 2026",
        )
        self.record = OvertimeRecord(
            "test-2026-09-07",
            "2026-09-07",
            "16:00",
            "18:00",
            [JobItem("Pekerjaan pengujian", "1 dokumen")],
        )

    def generate(self, officials, records=None):
        output = self.directory / "hasil.docx"
        generate_word(
            self.template, output, self.profile, officials, records or [self.record]
        )
        return signature_tables(output)

    def test_nips_empty_independently_or_both_and_names_preserved(self):
        for manager_nip, assistant_nip in (
            ("", ""),
            ("198012312006011001", ""),
            ("", "198512312010012001"),
            ("198012312006011001", "198512312010012001"),
            ("   ", "  "),
        ):
            with self.subTest(manager=manager_nip, assistant=assistant_nip):
                officials = Officials(
                    "Manajer Uji", manager_nip, "Asisten Uji", assistant_nip
                )
                table = self.generate(officials)[0]
                rows = children(table, "tr")
                name_cells = children(rows[5], "tc")
                nip_cells = children(rows[6], "tc")
                self.assertEqual(text(name_cells[0]), "Manajer Uji")
                self.assertEqual(text(name_cells[2]), "Asisten Uji")
                for index, nip in ((0, manager_nip), (2, assistant_nip)):
                    expected = f"NIP {nip.strip()}" if nip.strip() else ""
                    self.assertEqual(text(nip_cells[index]), expected)
                self.assertNotIn("YYYY", text(table))
                self.assertNotIn("ZZZZ", text(table))

    def test_unit_titles_on_every_generated_page(self):
        second = OvertimeRecord(
            "test-2026-09-08",
            "2026-09-08",
            "16:00",
            "19:00",
            [JobItem("Pekerjaan berikutnya", "2 dokumen")],
        )
        tables = self.generate(Officials(), [self.record, second])
        self.assertEqual(len(tables), 2)
        for table in tables:
            roles = children(children(table, "tr")[1], "tc")
            self.assertEqual(text(roles[0]), "Manajer Instalasi Gizi & Pelayanan")
            self.assertEqual(text(roles[2]), "Asisten Manajer Instalasi Gizi & Pelayanan")
            self.assertNotIn("Akuntansi dan BMN", text(table))
            self.assertNotIn("Verifikasi dan Tarif", text(table))

    def test_signature_formatting_and_blank_signature_space_preserved(self):
        before = signature_tables(self.template)[0]
        # Template highlights intentionally disappear from all generated blankos.
        for highlight in list(before.getElementsByTagNameNS(W_NS, "highlight")):
            highlight.parentNode.removeChild(highlight)
        after = self.generate(Officials())[0]
        before_rows, after_rows = children(before, "tr"), children(after, "tr")
        self.assertEqual(len(before_rows), len(after_rows))
        for before_row, after_row in zip(before_rows, after_rows):
            before_cells, after_cells = children(before_row, "tc"), children(after_row, "tc")
            self.assertEqual(len(before_cells), len(after_cells))
            for before_cell, after_cell in zip(before_cells, after_cells):
                for name in ("tcPr", "pPr", "rPr"):
                    original = [node.toxml() for node in before_cell.getElementsByTagNameNS(W_NS, name)]
                    generated = [node.toxml() for node in after_cell.getElementsByTagNameNS(W_NS, name)]
                    self.assertEqual(generated, original)
        for row_index in (2, 3, 4):
            self.assertEqual(after_rows[row_index].toxml(), before_rows[row_index].toxml())

    def test_existing_csv_headers_and_optional_nips_round_trip(self):
        data_dir = self.directory / "data"
        data_dir.mkdir()
        profile_path = data_dir / "profil.csv"
        officials_path = data_dir / "pejabat.csv"
        profile_path.write_text(
            "nama;nip;unit_kerja;bulan\nPegawai Lama;00123;Unit Lama;September 2026\n",
            encoding="utf-8-sig",
        )
        officials_path.write_text(
            "nama_manager;nip_manager;nama_asmen;nip_asmen\nManajer Lama;001234;Asisten Lama;\n",
            encoding="utf-8-sig",
        )
        original_profile = profile_path.read_bytes()
        original_officials = officials_path.read_bytes()
        store = DataStore(data_dir)
        profile = store.load_profile()
        officials = store.load_officials()
        self.assertEqual(profile_path.read_bytes(), original_profile)
        self.assertEqual(officials_path.read_bytes(), original_officials)
        self.assertEqual(profile.nip, "00123")
        self.assertEqual(profile.unit_kerja, "Unit Lama")
        self.assertEqual(officials, Officials("Manajer Lama", "001234", "Asisten Lama", ""))
        officials.nip_manager = ""
        store.save_officials(officials)
        self.assertEqual(store.load_officials(), officials)
        self.assertEqual(
            officials_path.read_text(encoding="utf-8-sig").splitlines()[0],
            ";".join(DataStore.OFFICIAL_HEADERS),
        )
        self.assertEqual(profile_path.read_bytes(), original_profile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
