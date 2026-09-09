"""Monthly Word recap built from the retained hospital form and saved daily data."""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable
from xml.dom import Node, minidom

from core import (
    Officials,
    OvertimeRecord,
    Profile,
    W_NS,
    _descendants,
    _direct_elements,
    _remove_highlights,
    _set_container_text,
    format_time_for_word,
    official_role_titles,
    parse_iso_date,
    parse_period,
    period_label,
    records_for_period,
    validate_record,
)


def _property(container: Node, name: str, before: tuple[str, ...] = ()) -> Node:
    """Get or insert a direct Word property without changing existing formatting."""
    existing = _direct_elements(container, name)
    if existing:
        return existing[0]
    element = container.ownerDocument.createElementNS(W_NS, f"w:{name}")
    following = next(
        (
            child
            for child in container.childNodes
            if child.nodeType == Node.ELEMENT_NODE and child.localName in before
        ),
        None,
    )
    container.insertBefore(element, following)
    return element


def _row_pagination(row: Node, *, header: bool = False) -> None:
    properties = _property(row, "trPr", ("tc",))
    no_split = _property(
        properties,
        "cantSplit",
        ("trHeight", "tblHeader", "tblCellSpacing", "jc", "hidden", "ins", "del", "trPrChange"),
    )
    no_split.setAttributeNS(W_NS, "w:val", "1")
    if header:
        repeat = _property(
            properties, "tblHeader", ("tblCellSpacing", "jc", "hidden", "ins", "del", "trPrChange")
        )
        repeat.setAttributeNS(W_NS, "w:val", "1")


def _keep_signature_together(table: Node) -> None:
    rows = _direct_elements(table, "tr")
    for index, row in enumerate(rows):
        _row_pagination(row)
        for paragraph in _descendants(row, "p"):
            properties = _property(paragraph, "pPr", ("r", "bookmarkStart", "bookmarkEnd"))
            if index < len(rows) - 1:
                following_names = tuple(
                    child.localName
                    for child in properties.childNodes
                    if child.nodeType == Node.ELEMENT_NODE and child.localName != "pStyle"
                )
                keep_next = _property(properties, "keepNext", following_names)
                keep_next.setAttributeNS(W_NS, "w:val", "1")
            following_names = tuple(
                child.localName
                for child in properties.childNodes
                if child.nodeType == Node.ELEMENT_NODE and child.localName not in ("pStyle", "keepNext")
            )
            keep_lines = _property(properties, "keepLines", following_names)
            keep_lines.setAttributeNS(W_NS, "w:val", "1")


def _cells(row: Node, count: int) -> list[Node]:
    cells = _direct_elements(row, "tc")
    if len(cells) != count:
        raise ValueError("Struktur kolom pada template rekap bulanan tidak sesuai.")
    return cells


def _fill_recap(
    document: minidom.Document,
    profile: Profile,
    officials: Officials,
    records: list[OvertimeRecord],
) -> None:
    bodies = _descendants(document, "body")
    if not bodies:
        raise ValueError("Bagian isi template rekap bulanan tidak ditemukan.")
    body = bodies[0]
    paragraphs = _direct_elements(body, "p")
    tables = _direct_elements(body, "tbl")
    if len(paragraphs) < 2 or len(tables) != 3 or not _direct_elements(body, "sectPr"):
        raise ValueError("Struktur template rekap bulanan tidak sesuai.")

    identity_rows = _direct_elements(tables[0], "tr")
    recap_rows = _direct_elements(tables[1], "tr")
    signature_rows = _direct_elements(tables[2], "tr")
    if len(identity_rows) != 3 or len(recap_rows) < 2 or len(signature_rows) != 7:
        raise ValueError("Tabel pada template rekap bulanan tidak lengkap.")
    # Check all structural slots before making changes in the in-memory copy.
    identity_cells = [_cells(row, 3) for row in identity_rows]
    [_cells(row, 5) for row in recap_rows]
    signature_cells = [_cells(row, 3) for row in signature_rows]

    month, year = parse_period(profile.bulan)
    _set_container_text(paragraphs[1], period_label(month, year).upper())
    for cells, value in zip(identity_cells, (profile.nama, profile.nip, profile.unit_kerja)):
        _set_container_text(cells[2], value)

    table = tables[1]
    data_rows = recap_rows[1:]
    prototype = data_rows[0].cloneNode(deep=True)
    prototype_cells = _cells(prototype, 5)
    items = [(record, item) for record in records for item in record.items]
    for _ in range(max(18, len(items)) - len(data_rows)):
        row = prototype.cloneNode(deep=True)
        table.appendChild(row)
        data_rows.append(row)

    _row_pagination(recap_rows[0], header=True)
    for index, row in enumerate(data_rows):
        _row_pagination(row)
        cells = _cells(row, 5)
        if index < len(items):
            record, item = items[index]
            values = (
                str(index + 1),
                parse_iso_date(record.tanggal).strftime("%d/%m/%Y"),
                item.pekerjaan,
                item.kuantitas,
                f"{format_time_for_word(record.jam_mulai)}-{format_time_for_word(record.jam_selesai)}",
            )
        else:
            values = ("", "", "", "", "")
        for column, value in enumerate(values):
            _set_container_text(cells[column], value, prototype_cells[column])

    manager_role, assistant_role = official_role_titles(profile, officials)
    for column, role, name, nip in (
        (0, manager_role, officials.nama_manager, officials.nip_manager),
        (2, assistant_role, officials.nama_asmen, officials.nip_asmen),
    ):
        _set_container_text(signature_cells[1][column], role)
        _set_container_text(signature_cells[5][column], name)
        _set_container_text(signature_cells[6][column], f"NIP {nip.strip()}" if nip.strip() else "")
    _keep_signature_together(tables[2])
    _remove_highlights(body)


def generate_monthly_recap(
    template_path: Path | str,
    output_path: Path | str,
    profile: Profile,
    officials: Officials,
    records: Iterable[OvertimeRecord],
) -> Path:
    """Write a separate recap for the profile's active month without editing data."""
    template_path = Path(template_path)
    output_path = Path(output_path)
    if not template_path.is_file():
        raise FileNotFoundError(f"Template rekap bulanan tidak ditemukan: {template_path}")
    if output_path.resolve() == template_path.resolve() or (
        output_path.exists() and output_path.samefile(template_path)
    ):
        raise ValueError("Simpan rekap dengan nama lain agar template asli tidak tertimpa.")

    selected = records_for_period(records, profile.bulan)
    if not selected:
        raise ValueError("Tidak ada data lembur pada bulan aktif untuk dibuat rekap.")
    for record in selected:
        validate_record(record, profile.bulan)

    temporary: Path | None = None
    try:
        with zipfile.ZipFile(template_path, "r") as source:
            document = minidom.parseString(source.read("word/document.xml"))
            try:
                _fill_recap(document, profile, officials, selected)
                generated_xml = document.toxml(encoding="UTF-8")
            finally:
                document.unlink()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target:
                target.comment = source.comment
                for member in source.infolist():
                    content = generated_xml if member.filename == "word/document.xml" else source.read(member.filename)
                    target.writestr(member, content)
        os.replace(temporary, output_path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output_path
