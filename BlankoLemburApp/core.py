from __future__ import annotations

import calendar
import csv
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from xml.dom import Node, minidom


MONTH_NAMES = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MAX_JOB_ROWS = 7


def current_period_label() -> str:
    today = date.today()
    return f"{MONTH_NAMES[today.month - 1]} {today.year}"


def period_label(month: int, year: int) -> str:
    if not 1 <= month <= 12:
        raise ValueError("Bulan harus antara 1 dan 12.")
    return f"{MONTH_NAMES[month - 1]} {year}"


def parse_period(label: str) -> tuple[int, int]:
    cleaned = " ".join((label or "").strip().split())
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", cleaned)
    if not match:
        raise ValueError("Format bulan harus seperti 'Agustus 2026'.")
    month_text, year_text = match.groups()
    month_lookup = {name.casefold(): index + 1 for index, name in enumerate(MONTH_NAMES)}
    month = month_lookup.get(month_text.casefold())
    if month is None:
        raise ValueError("Nama bulan tidak dikenali.")
    return month, int(year_text)


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_date_id(value: str) -> str:
    parsed = parse_iso_date(value)
    return f"{parsed.day} {MONTH_NAMES[parsed.month - 1]} {parsed.year}"


def format_date_short(value: str) -> str:
    parsed = parse_iso_date(value)
    return parsed.strftime("%d-%m-%Y")


def format_time_for_word(value: str) -> str:
    return value.replace(":", ".")


def normalize_time_input(value: str) -> str:
    """Normalize friendly time input such as 2000, 700, or 16.30."""
    cleaned = (value or "").strip().replace(".", ":")
    if re.fullmatch(r"\d{1,2}", cleaned):
        hour_text, minute_text = cleaned, "00"
    elif re.fullmatch(r"\d{3,4}", cleaned):
        digits = cleaned.zfill(4)
        hour_text, minute_text = digits[:2], digits[2:]
    else:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", cleaned)
        if not match:
            raise ValueError("Jam harus seperti 2000 atau 20:00.")
        hour_text, minute_text = match.groups()

    hour = int(hour_text)
    minute = int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError("Jam tidak valid. Contoh penulisan: 2000 atau 20:00.")
    return f"{hour:02d}:{minute:02d}"


def parse_time_minutes(value: str) -> int:
    try:
        parsed = datetime.strptime(normalize_time_input(value), "%H:%M")
    except ValueError as exc:
        raise ValueError("Jam harus seperti 2000 atau 20:00.") from exc
    return parsed.hour * 60 + parsed.minute


def default_start_time(value: str) -> str:
    """Return the default overtime start time for an ISO-formatted date."""
    weekday = parse_iso_date(value).weekday()
    if weekday <= 3:  # Monday through Thursday
        return "16:00"
    if weekday == 4:  # Friday
        return "16:30"
    return "07:00"  # Saturday and Sunday


def duration_minutes(start_time: str, end_time: str) -> int:
    start = parse_time_minutes(start_time)
    end = parse_time_minutes(end_time)
    if end <= start:
        raise ValueError("Jam selesai harus lebih besar dari jam mulai.")
    return end - start


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(max(0, minutes), 60)
    if hours and remainder:
        return f"{hours} jam {remainder} menit"
    if hours:
        return f"{hours} jam"
    return f"{remainder} menit"


@dataclass
class Profile:
    nama: str = "Nur Almito Muslindra"
    nip: str = ""
    unit_kerja: str = "Tim Kerja Akuntansi dan BMN"
    bulan: str = field(default_factory=current_period_label)


@dataclass
class Officials:
    nama_manager: str = "Suhatsyah, SE, MM, CPIA"
    nip_manager: str = ""
    nama_asmen: str = "Rahma Devi, SE. MM"
    nip_asmen: str = ""
    manager_unit_override: str = ""
    asmen_unit_override: str = ""


def official_role_titles(profile: Profile, officials: Officials) -> tuple[str, str]:
    """Use each manual unit suffix when set, otherwise follow the profile unit."""
    unit = profile.unit_kerja.strip()
    manager_unit = officials.manager_unit_override.strip() or unit
    assistant_unit = officials.asmen_unit_override.strip() or unit
    return (
        f"Manajer {manager_unit}".rstrip(),
        f"Asisten Manajer {assistant_unit}".rstrip(),
    )


@dataclass
class JobItem:
    pekerjaan: str
    kuantitas: str
    keterangan: str = ""


@dataclass
class OvertimeRecord:
    blanko_id: str
    tanggal: str
    jam_mulai: str
    jam_selesai: str
    items: list[JobItem]

    @property
    def minutes(self) -> int:
        return duration_minutes(self.jam_mulai, self.jam_selesai)


class DataStore:
    PROFILE_HEADERS = ("nama", "nip", "unit_kerja", "bulan")
    OFFICIAL_HEADERS = (
        "nama_manager",
        "nip_manager",
        "nama_asmen",
        "nip_asmen",
        "manager_unit_override",
        "asmen_unit_override",
    )
    RECORD_HEADERS = (
        "blanko_id",
        "urutan",
        "tanggal",
        "jam_mulai",
        "jam_selesai",
        "pekerjaan",
        "kuantitas",
        "keterangan",
    )

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.base_dir / "profil.csv"
        self.officials_path = self.base_dir / "pejabat.csv"
        self.records_path = self.base_dir / "lembur_records.csv"
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not self.profile_path.exists():
            self.save_profile(Profile())
        if not self.officials_path.exists():
            self.save_officials(Officials())
        if not self.records_path.exists():
            self._write_rows(self.records_path, self.RECORD_HEADERS, [])

    @staticmethod
    def _write_rows(path: Path, headers: Iterable[str], rows: Iterable[dict[str, str]]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(headers), delimiter=";", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)

    @staticmethod
    def _read_rows(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=";"))

    def load_profile(self) -> Profile:
        rows = self._read_rows(self.profile_path)
        if not rows:
            return Profile()
        row = rows[0]
        return Profile(
            nama=(row.get("nama") or "").strip(),
            nip=(row.get("nip") or "").strip(),
            unit_kerja=(row.get("unit_kerja") or "").strip(),
            bulan=(row.get("bulan") or current_period_label()).strip(),
        )

    def save_profile(self, profile: Profile) -> None:
        self._write_rows(
            self.profile_path,
            self.PROFILE_HEADERS,
            [
                {
                    "nama": profile.nama,
                    "nip": profile.nip,
                    "unit_kerja": profile.unit_kerja,
                    "bulan": profile.bulan,
                }
            ],
        )

    def load_officials(self) -> Officials:
        rows = self._read_rows(self.officials_path)
        if not rows:
            return Officials()
        row = rows[0]
        return Officials(
            nama_manager=(row.get("nama_manager") or "").strip(),
            nip_manager=(row.get("nip_manager") or "").strip(),
            nama_asmen=(row.get("nama_asmen") or "").strip(),
            nip_asmen=(row.get("nip_asmen") or "").strip(),
            manager_unit_override=(row.get("manager_unit_override") or "").strip(),
            asmen_unit_override=(row.get("asmen_unit_override") or "").strip(),
        )

    def save_officials(self, officials: Officials) -> None:
        self._write_rows(
            self.officials_path,
            self.OFFICIAL_HEADERS,
            [
                {
                    "nama_manager": officials.nama_manager,
                    "nip_manager": officials.nip_manager,
                    "nama_asmen": officials.nama_asmen,
                    "nip_asmen": officials.nip_asmen,
                    "manager_unit_override": officials.manager_unit_override,
                    "asmen_unit_override": officials.asmen_unit_override,
                }
            ],
        )

    def load_records(self) -> list[OvertimeRecord]:
        grouped: dict[str, OvertimeRecord] = {}
        for row in self._read_rows(self.records_path):
            tanggal = (row.get("tanggal") or "").strip()
            if not tanggal:
                continue
            blanko_id = (row.get("blanko_id") or tanggal).strip()
            if blanko_id not in grouped:
                grouped[blanko_id] = OvertimeRecord(
                    blanko_id=blanko_id,
                    tanggal=tanggal,
                    jam_mulai=(row.get("jam_mulai") or "").strip(),
                    jam_selesai=(row.get("jam_selesai") or "").strip(),
                    items=[],
                )
            grouped[blanko_id].items.append(
                JobItem(
                    pekerjaan=(row.get("pekerjaan") or "").strip(),
                    kuantitas=(row.get("kuantitas") or "").strip(),
                    keterangan=(row.get("keterangan") or "").strip(),
                )
            )
        return sorted(grouped.values(), key=lambda item: item.tanggal)

    def save_records(self, records: Iterable[OvertimeRecord]) -> None:
        rows: list[dict[str, str]] = []
        for record in sorted(records, key=lambda item: item.tanggal):
            for order, item in enumerate(record.items, start=1):
                rows.append(
                    {
                        "blanko_id": record.blanko_id,
                        "urutan": str(order),
                        "tanggal": record.tanggal,
                        "jam_mulai": record.jam_mulai,
                        "jam_selesai": record.jam_selesai,
                        "pekerjaan": item.pekerjaan,
                        "kuantitas": item.kuantitas,
                        "keterangan": item.keterangan,
                    }
                )
        self._write_rows(self.records_path, self.RECORD_HEADERS, rows)


def records_for_period(records: Iterable[OvertimeRecord], period: str) -> list[OvertimeRecord]:
    month, year = parse_period(period)
    selected = []
    for record in records:
        parsed = parse_iso_date(record.tanggal)
        if parsed.month == month and parsed.year == year:
            selected.append(record)
    return sorted(selected, key=lambda item: item.tanggal)


def period_dates(period: str) -> list[tuple[str, str]]:
    month, year = parse_period(period)
    days = calendar.monthrange(year, month)[1]
    return [
        (date(year, month, day).isoformat(), f"{day:02d} {MONTH_NAMES[month - 1]} {year}")
        for day in range(1, days + 1)
    ]


def validate_record(record: OvertimeRecord, period: str) -> None:
    if not record.tanggal:
        raise ValueError("Tanggal lembur wajib diisi.")
    parsed_date = parse_iso_date(record.tanggal)
    period_month, period_year = parse_period(period)
    if (parsed_date.month, parsed_date.year) != (period_month, period_year):
        raise ValueError("Tanggal lembur harus berada pada bulan aktif.")
    duration_minutes(record.jam_mulai, record.jam_selesai)
    if not record.items:
        raise ValueError("Tambahkan minimal satu pekerjaan.")
    if len(record.items) > MAX_JOB_ROWS:
        raise ValueError(f"Maksimal {MAX_JOB_ROWS} pekerjaan dalam satu blanko.")
    for index, item in enumerate(record.items, start=1):
        if not item.pekerjaan.strip():
            raise ValueError(f"Pekerjaan baris {index} masih kosong.")
        if not item.kuantitas.strip():
            raise ValueError(f"Kuantitas baris {index} masih kosong.")


def _local_name(node: Node) -> str:
    return node.localName or node.nodeName.split(":")[-1]


def _direct_elements(node: Node, local_name: str) -> list[Node]:
    return [
        child
        for child in node.childNodes
        if child.nodeType == Node.ELEMENT_NODE and _local_name(child) == local_name
    ]


def _descendants(node: Node, local_name: str) -> list[Node]:
    if hasattr(node, "getElementsByTagNameNS"):
        found = list(node.getElementsByTagNameNS(W_NS, local_name))
        if found:
            return found
    if hasattr(node, "getElementsByTagName"):
        return list(node.getElementsByTagName(f"w:{local_name}"))
    return []


def _replace_text_node(text_node: Node, value: str) -> None:
    while text_node.firstChild:
        text_node.removeChild(text_node.firstChild)
    text_node.appendChild(text_node.ownerDocument.createTextNode(value))
    if value.startswith(" ") or value.endswith(" "):
        text_node.setAttributeNS(XML_NS, "xml:space", "preserve")


def _set_container_text(container: Node, value: str, prototype: Node | None = None) -> None:
    text_nodes = _descendants(container, "t")
    if not text_nodes and value:
        paragraph = container if _local_name(container) == "p" else None
        if paragraph is None:
            paragraphs = _descendants(container, "p")
            paragraph = paragraphs[0] if paragraphs else None
        if paragraph is None:
            paragraph = container.ownerDocument.createElementNS(W_NS, "w:p")
            container.appendChild(paragraph)

        run = None
        if prototype is not None:
            prototype_runs = _descendants(prototype, "r")
            if prototype_runs:
                run = prototype_runs[0].cloneNode(deep=True)
        if run is None:
            run = container.ownerDocument.createElementNS(W_NS, "w:r")
            run.appendChild(container.ownerDocument.createElementNS(W_NS, "w:t"))
        paragraph.appendChild(run)
        text_nodes = _descendants(container, "t")

    if not text_nodes:
        return
    _replace_text_node(text_nodes[0], value)
    for extra in text_nodes[1:]:
        _replace_text_node(extra, "")


def _remove_highlights(container: Node) -> None:
    for highlight in list(_descendants(container, "highlight")):
        if highlight.parentNode is not None:
            highlight.parentNode.removeChild(highlight)


def _page_break(document: minidom.Document) -> Node:
    paragraph = document.createElementNS(W_NS, "w:p")
    run = document.createElementNS(W_NS, "w:r")
    line_break = document.createElementNS(W_NS, "w:br")
    line_break.setAttributeNS(W_NS, "w:type", "page")
    run.appendChild(line_break)
    paragraph.appendChild(run)
    return paragraph


def _fill_page(container: Node, profile: Profile, officials: Officials, record: OvertimeRecord) -> None:
    page_date = parse_iso_date(record.tanggal)
    paragraphs = _direct_elements(container, "p")
    tables = _direct_elements(container, "tbl")
    if len(paragraphs) < 2 or len(tables) < 3:
        raise ValueError("Struktur template Word tidak sesuai dengan blanko yang didukung.")

    _set_container_text(
        paragraphs[1],
        f"{MONTH_NAMES[page_date.month - 1].upper()} {page_date.year}",
    )

    info_rows = _direct_elements(tables[0], "tr")
    if len(info_rows) < 5:
        raise ValueError("Tabel identitas pada template tidak lengkap.")
    info_cells = [_direct_elements(row, "tc") for row in info_rows]
    _set_container_text(info_cells[0][2], profile.nama)
    _set_container_text(info_cells[1][2], profile.nip)
    _set_container_text(info_cells[2][2], profile.unit_kerja)
    _set_container_text(info_cells[3][2], format_date_id(record.tanggal))
    _set_container_text(
        info_cells[4][2],
        f"{format_time_for_word(record.jam_mulai)} – {format_time_for_word(record.jam_selesai)}",
    )

    job_rows = _direct_elements(tables[1], "tr")
    data_rows = job_rows[2:]
    if len(data_rows) < MAX_JOB_ROWS:
        raise ValueError("Jumlah baris pekerjaan pada template kurang dari tujuh.")
    prototype_cells = _direct_elements(data_rows[0], "tc")
    for row in data_rows:
        cells = _direct_elements(row, "tc")
        for cell in cells:
            _set_container_text(cell, "")

    for index, item in enumerate(record.items):
        cells = _direct_elements(data_rows[index], "tc")
        _set_container_text(cells[0], str(index + 1), prototype_cells[0])
        _set_container_text(cells[1], item.pekerjaan, prototype_cells[1])
        _set_container_text(cells[2], item.kuantitas, prototype_cells[2])
        _set_container_text(cells[3], "")
        _set_container_text(cells[4], "")
        _set_container_text(cells[5], item.keterangan, prototype_cells[1])

    signature_rows = _direct_elements(tables[2], "tr")
    if len(signature_rows) < 7:
        raise ValueError("Tabel tanda tangan pada template tidak lengkap.")
    role_cells = _direct_elements(signature_rows[1], "tc")
    manager_name_cells = _direct_elements(signature_rows[5], "tc")
    manager_nip_cells = _direct_elements(signature_rows[6], "tc")
    manager_role, assistant_role = official_role_titles(profile, officials)
    _set_container_text(role_cells[0], manager_role)
    _set_container_text(role_cells[2], assistant_role)
    _set_container_text(manager_name_cells[0], officials.nama_manager)
    _set_container_text(manager_name_cells[2], officials.nama_asmen)
    manager_nip = officials.nip_manager.strip()
    assistant_nip = officials.nip_asmen.strip()
    _set_container_text(manager_nip_cells[0], f"NIP {manager_nip}" if manager_nip else "")
    _set_container_text(manager_nip_cells[2], f"NIP {assistant_nip}" if assistant_nip else "")

    _remove_highlights(container)


def generate_word(
    template_path: Path | str,
    output_path: Path | str,
    profile: Profile,
    officials: Officials,
    records: Iterable[OvertimeRecord],
) -> Path:
    selected = sorted(list(records), key=lambda item: item.tanggal)
    if not selected:
        raise ValueError("Tidak ada blanko yang dapat dibuat.")
    for record in selected:
        validate_record(record, profile.bulan)

    template_path = Path(template_path)
    output_path = Path(output_path)
    if not template_path.exists():
        raise FileNotFoundError(f"Template Word tidak ditemukan: {template_path}")

    with zipfile.ZipFile(template_path, "r") as source_zip:
        document_xml = source_zip.read("word/document.xml")
        document = minidom.parseString(document_xml)
        body_nodes = document.getElementsByTagNameNS(W_NS, "body")
        if not body_nodes:
            body_nodes = document.getElementsByTagName("w:body")
        if not body_nodes:
            raise ValueError("Bagian isi template Word tidak ditemukan.")
        body = body_nodes[0]

        template_nodes: list[Node] = []
        section_properties = None
        for child in list(body.childNodes):
            if child.nodeType == Node.ELEMENT_NODE and _local_name(child) == "sectPr":
                section_properties = child.cloneNode(deep=True)
            else:
                template_nodes.append(child.cloneNode(deep=True))
        if section_properties is None:
            raise ValueError("Pengaturan halaman template Word tidak ditemukan.")

        while body.firstChild:
            body.removeChild(body.firstChild)

        for record_index, record in enumerate(selected):
            page_container = document.createElementNS(W_NS, "w:body")
            for node in template_nodes:
                page_container.appendChild(node.cloneNode(deep=True))
            _fill_page(page_container, profile, officials, record)
            while page_container.firstChild:
                body.appendChild(page_container.firstChild)
            if record_index < len(selected) - 1:
                body.appendChild(_page_break(document))
        body.appendChild(section_properties)

        generated_xml = document.toxml(encoding="UTF-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
            for item in source_zip.infolist():
                payload = generated_xml if item.filename == "word/document.xml" else source_zip.read(item.filename)
                target_zip.writestr(item, payload)
        os.replace(temporary, output_path)
    return output_path


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", value).strip().strip(".")
    return cleaned or "Blanko Lembur"
