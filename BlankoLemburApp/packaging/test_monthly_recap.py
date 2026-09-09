"""Monthly recap data, reference-fidelity, pagination and file-safety checks."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from xml.dom import minidom

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import recap  # noqa: E402
from core import JobItem, Officials, OvertimeRecord, Profile, W_NS  # noqa: E402


def children(node, name):
    return [child for child in node.childNodes if child.localName == name]


def text(node):
    return "".join(
        child.data
        for element in node.getElementsByTagNameNS(W_NS, "t")
        for child in element.childNodes
        if child.nodeType == child.TEXT_NODE
    )


def document(path):
    with zipfile.ZipFile(path) as archive:
        return minidom.parseString(archive.read("word/document.xml"))


def tables(doc):
    return children(doc.getElementsByTagNameNS(W_NS, "body")[0], "tbl")


def values(row):
    return [text(cell) for cell in children(row, "tc")]


class MonthlyRecapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="recap-test-", dir=APP_DIR / "packaging")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.template = APP_DIR / "REKAP LEMBUR BULAN.docx"
        self.original_template = self.template.read_bytes()
        self.output = self.directory / "rekap.docx"
        self.profile = Profile("Pegawai Uji", "001234567890", "Instalasi Gizi", "September 2026")
        self.officials = Officials("Manajer Uji", "00123", "Asisten Uji", "00456")
        self.record = OvertimeRecord(
            "test-7", "2026-09-07", "16:00", "18:03", [JobItem("Laporan harian", "1 laporan")]
        )

    def tearDown(self):
        self.assertEqual(self.template.read_bytes(), self.original_template)

    def generate(self, records=None, officials=None):
        result = recap.generate_monthly_recap(
            self.template,
            self.output,
            self.profile,
            officials or self.officials,
            [self.record] if records is None else records,
        )
        self.assertEqual(result, self.output)
        doc = document(result)
        self.addCleanup(doc.unlink)
        return doc

    def test_empty_month_rejected_without_creating_or_replacing_output(self):
        self.output.write_bytes(b"existing-output")
        previous_month = OvertimeRecord("old", "2026-08-31", "16:00", "17:00", [JobItem("Old", "1")])
        for records in ([], [previous_month]):
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, "Tidak ada data"):
                self.generate(records)
            self.assertEqual(self.output.read_bytes(), b"existing-output")
        self.assertFalse(list(self.directory.glob("*.tmp")))

    def test_active_month_only_and_multi_job_rows_sorted_without_aggregation(self):
        earlier = OvertimeRecord(
            "test-2", "2026-09-02", "07:00", "12:45",
            [JobItem("Pekerjaan pertama", "2 berkas"), JobItem("Pekerjaan kedua", "3 kegiatan")],
        )
        outside = OvertimeRecord("outside", "2026-10-01", "16:00", "17:00", [JobItem("Bulan lain", "99")])
        doc = self.generate(iter([self.record, outside, earlier]))
        rows = children(tables(doc)[1], "tr")
        self.assertEqual(values(rows[1]), ["1", "02/09/2026", "Pekerjaan pertama", "2 berkas", "07.00-12.45"])
        self.assertEqual(values(rows[2]), ["2", "02/09/2026", "Pekerjaan kedua", "3 kegiatan", "07.00-12.45"])
        self.assertEqual(values(rows[3]), ["3", "07/09/2026", "Laporan harian", "1 laporan", "16.00-18.03"])
        self.assertNotIn("Bulan lain", text(doc))

    def test_title_identity_blank_scaffold_and_examples_removed(self):
        doc = self.generate()
        body = doc.getElementsByTagNameNS(W_NS, "body")[0]
        self.assertEqual(text(children(body, "p")[1]), "SEPTEMBER 2026")
        identity, data, signatures = tables(doc)
        self.assertEqual([values(row)[2] for row in children(identity, "tr")], [self.profile.nama, self.profile.nip, self.profile.unit_kerja])
        rows = children(data, "tr")
        self.assertEqual(len(rows), 19)
        self.assertTrue(all(values(row) == ["", "", "", "", ""] for row in rows[2:]))
        self.assertEqual(values(children(signatures, "tr")[1]), ["Manajer Instalasi Gizi", "", "Asisten Manajer Instalasi Gizi"])
        for stale in ("SRIKANDI", "nomenklatur", "AGUSTUS", "Nur Almito", "Suhatsyah", "Rahma Devi", "Akuntansi", "Verivikasi", "XXX", "YYY"):
            self.assertNotIn(stale, text(doc))
        self.assertFalse(doc.getElementsByTagNameNS(W_NS, "highlight"))

    def test_optional_official_nips_independently_or_together(self):
        for manager, assistant in (("", ""), ("00123", ""), ("", "00456"), ("00123", "00456"), ("  ", "  ")):
            with self.subTest(manager=manager, assistant=assistant):
                doc = self.generate(officials=Officials("Nama Manajer", manager, "Nama Asisten", assistant))
                rows = children(tables(doc)[2], "tr")
                self.assertEqual(values(rows[5]), ["Nama Manajer", "", "Nama Asisten"])
                self.assertEqual(values(rows[6]), [f"NIP {manager.strip()}" if manager.strip() else "", "", f"NIP {assistant.strip()}" if assistant.strip() else ""])

    def test_expands_for_many_jobs_and_sets_continuation_properties(self):
        records = [
            OvertimeRecord(f"day-{day}", f"2026-09-{day:02d}", "16:00", "20:00", [JobItem(f"Pekerjaan {day}/{index}", f"{index} berkas") for index in range(1, 8)])
            for day in range(1, 8)
        ]
        doc = self.generate(records)
        rows = children(tables(doc)[1], "tr")
        self.assertEqual(len(rows), 50)
        self.assertEqual(values(rows[-1]), ["49", "07/09/2026", "Pekerjaan 7/7", "7 berkas", "16.00-20.00"])
        header = rows[0].getElementsByTagNameNS(W_NS, "tblHeader")
        self.assertEqual(len(header), 1)
        self.assertEqual(header[0].getAttributeNS(W_NS, "val"), "1")
        self.assertTrue(all(len(row.getElementsByTagNameNS(W_NS, "cantSplit")) == 1 for row in rows))
        signature_rows = children(tables(doc)[2], "tr")
        for row in signature_rows[:-1]:
            for paragraph in row.getElementsByTagNameNS(W_NS, "p"):
                self.assertEqual(len(paragraph.getElementsByTagNameNS(W_NS, "keepNext")), 1)
        for paragraph in signature_rows[-1].getElementsByTagNameNS(W_NS, "p"):
            self.assertFalse(paragraph.getElementsByTagNameNS(W_NS, "keepNext"))

    def test_special_xml_characters_preserved_as_text(self):
        self.profile.nama = 'Nama <Uji> & "Rekan"'
        self.profile.unit_kerja = "Gizi & Pelayanan"
        self.record.items = [JobItem("Memeriksa A < B & B > C", '2 berkas "lengkap"')]
        doc = self.generate()
        self.assertIn(self.profile.nama, text(doc))
        self.assertEqual(values(children(tables(doc)[1], "tr")[1])[2:4], [self.record.items[0].pekerjaan, self.record.items[0].kuantitas])
        self.assertIn("Asisten Manajer Gizi & Pelayanan", text(doc))

    def test_untouched_zip_parts_section_geometry_and_formatting_preserved(self):
        generated = self.generate()
        original = document(self.template)
        self.addCleanup(original.unlink)
        with zipfile.ZipFile(self.template) as before, zipfile.ZipFile(self.output) as after:
            self.assertEqual(before.namelist(), after.namelist())
            self.assertEqual(before.comment, after.comment)
            for name in before.namelist():
                if name != "word/document.xml":
                    self.assertEqual(before.read(name), after.read(name), name)
        for tag in ("sectPr", "tblPr", "tblGrid", "tcPr", "sz", "rFonts"):
            self.assertEqual(
                [node.toxml() for node in original.getElementsByTagNameNS(W_NS, tag)],
                [node.toxml() for node in generated.getElementsByTagNameNS(W_NS, tag)], tag,
            )
        # Added flow properties and removed template highlighting are intentional.
        for doc in (original, generated):
            for tag in ("highlight", "cantSplit", "tblHeader", "keepNext", "keepLines"):
                for node in list(doc.getElementsByTagNameNS(W_NS, tag)):
                    node.parentNode.removeChild(node)
        for tag in ("pPr", "rPr"):
            self.assertEqual(
                [node.toxml() for node in original.getElementsByTagNameNS(W_NS, tag)],
                [node.toxml() for node in generated.getElementsByTagNameNS(W_NS, tag)], tag,
            )

    def test_cannot_overwrite_reference_by_path_or_hardlink(self):
        for output in (self.template, self.template.parent / "." / self.template.name):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "template asli"):
                recap.generate_monthly_recap(self.template, output, self.profile, self.officials, [self.record])
        # Use a temporary reference copy for the real samefile/hard-link case.
        copy = self.directory / "template.docx"
        copy.write_bytes(self.original_template)
        link = self.directory / "template-alias.docx"
        try:
            os.link(copy, link)
        except OSError as exc:
            self.skipTest(f"Hard links not available: {exc}")
        with self.assertRaisesRegex(ValueError, "template asli"):
            recap.generate_monthly_recap(copy, link, self.profile, self.officials, [self.record])
        self.assertEqual(copy.read_bytes(), self.original_template)

    def test_invalid_record_leaves_existing_output_and_no_temporary(self):
        self.output.write_bytes(b"existing-output")
        self.record.jam_selesai = "15:00"
        with self.assertRaisesRegex(ValueError, "Jam selesai"):
            self.generate()
        self.assertEqual(self.output.read_bytes(), b"existing-output")
        self.assertFalse(list(self.directory.glob("*.tmp")))

    def test_write_failure_cleans_temporary_and_preserves_existing_output(self):
        self.output.write_bytes(b"existing-output")
        with mock.patch.object(recap.os, "replace", side_effect=PermissionError("Document open")):
            with self.assertRaises(PermissionError):
                self.generate()
        self.assertEqual(self.output.read_bytes(), b"existing-output")
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()), ["rekap.docx"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
