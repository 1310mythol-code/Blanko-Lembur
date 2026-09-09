"""Signed updates for the portable Windows executable; never touches user CSVs."""
from __future__ import annotations

import base64
import ctypes
import hashlib
from http.client import HTTPException
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import app_metadata

MAX_MANIFEST_BYTES = 64 * 1024
MAX_EXE_BYTES = 200 * 1024 * 1024
NETWORK_TIMEOUT = 15
REPLACE_ATTEMPTS = 120
READY_TIMEOUT = 45
STAGE_NAME = re.compile(r"update-[0-9a-f]{32}\Z")


class UpdateError(Exception):
    """An update could not safely be completed."""


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    notes: str
    url: str
    sha256: str
    size: int
    manifest: bytes = field(repr=False, compare=False)


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,6}(?:\.\d{1,6}){1,3}", value, re.ASCII):
        raise UpdateError("Nomor versi pembaruan tidak valid.")
    parts = tuple(map(int, value.split(".")))
    return parts + (0,) * (4 - len(parts))


def _https_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 for c in value):
        raise UpdateError("Alamat pembaruan tidak valid; alamat HTTPS diperlukan.")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.fragment and parsed.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise UpdateError("Alamat pembaruan tidak valid; alamat HTTPS diperlukan.")
    return value


def is_configured() -> bool:
    return bool(app_metadata.UPDATE_MANIFEST_URL and app_metadata.UPDATE_PUBLIC_KEY)


class _HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str):
    request = Request(_https_url(url), headers={"User-Agent": "BlankoLemburOtomatis/" + app_metadata.APP_VERSION})
    return build_opener(_HTTPSRedirects()).open(request, timeout=NETWORK_TIMEOUT)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _parse_manifest(raw: bytes) -> UpdateRelease:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UpdateError("Informasi pembaruan terlalu besar.")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        envelope = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
            raise ValueError("Invalid envelope")
        payload = envelope["payload"]
        if not isinstance(payload, dict) or set(payload) != {"version", "notes", "url", "sha256", "size"}:
            raise ValueError("Invalid payload")
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(app_metadata.UPDATE_PUBLIC_KEY, validate=True))
        public_key.verify(base64.b64decode(envelope["signature"], validate=True), canonical_payload(payload))
        version = payload["version"]
        _version(version)
        _https_url(payload["url"])
        if not isinstance(payload["notes"], str) or len(payload["notes"]) > 10000:
            raise ValueError("Invalid notes")
        if not isinstance(payload["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["sha256"]):
            raise ValueError("Invalid digest")
        if type(payload["size"]) is not int or not 2 <= payload["size"] <= MAX_EXE_BYTES:
            raise ValueError("Invalid size")
        return UpdateRelease(**payload, manifest=raw)
    except UpdateError:
        raise
    except ImportError as exc:
        raise UpdateError("Komponen pemeriksaan pembaruan tidak tersedia. Gunakan EXE resmi terbaru.") from exc
    except (ValueError, TypeError, KeyError, InvalidSignature) as exc:
        raise UpdateError("Keaslian informasi pembaruan tidak dapat diverifikasi. Pembaruan dibatalkan.") from exc


def check_for_update() -> UpdateRelease | None:
    if not is_configured():
        raise UpdateError("Layanan pembaruan belum diaktifkan. Sumber rilis aplikasi akan diatur oleh pengembang.")
    try:
        with _open(app_metadata.UPDATE_MANIFEST_URL) as response:
            _https_url(response.geturl())
            chunks = []
            total = 0
            started = time.monotonic()
            while total <= MAX_MANIFEST_BYTES:
                if time.monotonic() - started > 30:
                    raise UpdateError("Pemeriksaan pembaruan terlalu lama. Silakan coba lagi.")
                chunk = response.read1(min(8192, MAX_MANIFEST_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            raw = b"".join(chunks)
        release = _parse_manifest(raw)
        return release if _version(release.version) > _version(app_metadata.APP_VERSION) else None
    except HTTPError as exc:
        # A new public repository can be configured before its first Release
        # exists. Treat that normal state as "no update" instead of showing a
        # network failure to users.
        if exc.code == 404:
            return None
        raise UpdateError("Tidak dapat memeriksa pembaruan. Layanan GitHub sedang tidak tersedia.") from exc
    except UpdateError:
        raise
    except (OSError, URLError, ValueError, HTTPException) as exc:
        raise UpdateError("Tidak dapat memeriksa pembaruan. Periksa koneksi internet, lalu coba lagi.") from exc


def _data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "BlankoLemburOtomatis"


def _plain_path(path: Path) -> Path:
    """Refuse link/junction redirection before any filesystem mutation."""
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            raise UpdateError("Lokasi pembaruan tidak boleh berupa tautan atau junction.")
    if path != path.resolve():
        raise UpdateError("Lokasi pembaruan tidak valid.")
    return path


def _stage_path(staged: Path) -> Path:
    staged = _plain_path(staged)
    root = _plain_path(_data_dir() / "updates")
    if staged.name != "update.exe" or staged.parent.parent != root or not STAGE_NAME.fullmatch(staged.parent.name):
        raise UpdateError("Lokasi berkas pembaruan tidak valid.")
    return staged


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def _verify_file(path: Path, release: UpdateRelease) -> None:
    path = _plain_path(path)
    if not path.is_file() or path.stat().st_size != release.size or _digest(path) != release.sha256:
        raise UpdateError("Berkas pembaruan tidak lengkap atau telah berubah. Unduh ulang pembaruan.")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise UpdateError("Berkas pembaruan bukan aplikasi Windows yang valid.")


def download_update(release: UpdateRelease, data_dir: Path) -> Path:
    # Re-verify provenance rather than trusting a caller-constructed dataclass.
    verified = _parse_manifest(release.manifest)
    if verified != release or _version(release.version) <= _version(app_metadata.APP_VERSION):
        raise UpdateError("Versi pembaruan tidak valid atau sudah terpasang.")
    if _plain_path(data_dir) != _plain_path(_data_dir()):
        raise UpdateError("Pembaruan hanya tersedia pada aplikasi EXE yang telah dikemas.")
    root = _plain_path(Path(data_dir) / "updates")
    stage = root / ("update-" + uuid.uuid4().hex)
    try:
        root.mkdir(parents=True, exist_ok=True)
        stage.mkdir()
        staged = stage / "update.exe"
        started = time.monotonic()
        with _open(release.url) as response, staged.open("xb") as output:
            _https_url(response.geturl())
            total = 0
            while True:
                if time.monotonic() - started > 180:
                    raise UpdateError("Pengunduhan terlalu lama. Periksa koneksi, lalu coba lagi.")
                chunk = response.read1(min(64 * 1024, release.size + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > release.size:
                    raise UpdateError("Ukuran berkas pembaruan tidak sesuai informasi rilis.")
                output.write(chunk)
        _verify_file(staged, release)
        (stage / "release.json").write_bytes(release.manifest)
        return staged
    except Exception as exc:
        _remove_stage_files(stage, include_helper=True)
        if isinstance(exc, UpdateError):
            raise
        if isinstance(exc, (OSError, URLError, ValueError, HTTPException)):
            raise UpdateError("Pembaruan tidak dapat diunduh. Periksa koneksi dan ruang penyimpanan, lalu coba lagi.") from exc
        raise


def _target_path(target: Path) -> Path:
    target = _plain_path(target)
    if target.suffix.lower() != ".exe" or not target.is_file():
        raise UpdateError("Lokasi aplikasi tujuan tidak valid.")
    updates = _plain_path(_data_dir() / "updates")
    if target.is_relative_to(updates):
        raise UpdateError("Aplikasi tujuan tidak boleh berada di folder pembaruan sementara.")
    return target


def _process_args() -> dict:
    env = os.environ.copy()
    # One-file PyInstaller children must own their extracted runtime directory.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "close_fds": True, "env": env}


def launch_update(staged_exe: Path, target_exe: Path) -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise UpdateError("Pembaruan otomatis hanya dapat dipasang dari aplikasi EXE Windows.")
    staged = _stage_path(staged_exe)
    target = _target_path(target_exe)
    if target != _plain_path(Path(sys.executable)):
        raise UpdateError("Pembaruan hanya dapat mengganti aplikasi yang sedang digunakan.")
    created = []
    try:
        release = _parse_manifest(_plain_path(staged.parent / "release.json").read_bytes())
        _verify_file(staged, release)
        helper = staged.parent / "helper.exe"
        request = {"target": str(target), "original_sha256": _digest(target)}
        _plain_path(helper)
        with helper.open("xb") as output, target.open("rb") as source:
            created.append(helper)
            shutil.copyfileobj(source, output)
        with (staged.parent / "request.json").open("x", encoding="utf-8") as output:
            created.append(staged.parent / "request.json")
            json.dump(request, output)
        subprocess.Popen([str(helper), "--apply-update", str(staged), str(target)], **_process_args())
    except UpdateError:
        raise
    except (OSError, ValueError) as exc:
        for path in reversed(created):
            try:
                _plain_path(path).unlink(missing_ok=True)
            except (OSError, UpdateError):
                pass
        raise UpdateError("Pemasangan pembaruan tidak dapat dimulai. Aplikasi lama masih dapat digunakan.") from exc


def _remove_stage_files(stage: Path, *, include_helper: bool = False) -> None:
    """Delete only known temporary files, never recursively delete directories."""
    try:
        _stage_path(stage / "update.exe")
    except (OSError, UpdateError):
        return
    names = ["update.exe", "release.json", "request.json", "previous.exe", "ready.json"]
    if include_helper:
        names += ["helper.exe"]
    for name in names:
        try:
            _plain_path(stage / name).unlink(missing_ok=True)
        except (OSError, UpdateError):
            pass
    if include_helper and not (stage / "helper.exe").exists():
        try:
            _plain_path(stage / "complete.json").unlink(missing_ok=True)
        except (OSError, UpdateError):
            pass
    try:
        stage.rmdir()
    except OSError:
        pass


def cleanup_updates() -> None:
    """Call on normal startup; a running helper is harmlessly skipped until next time."""
    try:
        root = _plain_path(_data_dir() / "updates")
        if not root.is_dir():
            return
        for stage in root.iterdir():
            if STAGE_NAME.fullmatch(stage.name) and _plain_path(stage / "complete.json").is_file():
                _remove_stage_files(stage, include_helper=True)
    except (OSError, UpdateError):
        pass


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "Pembaruan aplikasi", 0x10)


def confirm_update_ready(marker: Path) -> None:
    """The new EXE acknowledges startup only after constructing its normal application."""
    marker = _plain_path(marker)
    if (sys.platform != "win32" or not getattr(sys, "frozen", False)
            or marker.name != "ready.json"):
        raise UpdateError("Penanda kesiapan pembaruan tidak valid.")
    staged = _stage_path(marker.parent / "update.exe")
    request = json.loads(_plain_path(marker.parent / "request.json").read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    target = _target_path(Path(sys.executable))
    if request.get("target") != str(target):
        raise UpdateError("Aplikasi tidak cocok dengan tujuan pembaruan.")
    release = _parse_manifest(_plain_path(staged.parent / "release.json").read_bytes())
    if _version(release.version) != _version(app_metadata.APP_VERSION):
        raise UpdateError("Versi aplikasi tidak cocok dengan informasi pembaruan.")
    _verify_file(target, release)
    with marker.open("x", encoding="utf-8") as output:
        json.dump({"version": release.version, "target": str(target)}, output)


def _wait_ready(process, marker: Path, target: Path, version: str) -> None:
    started = time.monotonic()
    while time.monotonic() - started < READY_TIMEOUT:
        marker = _plain_path(marker)
        if marker.exists():
            if marker.stat().st_size <= 4096:
                try:
                    status = json.loads(marker.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
                    if status == {"version": version, "target": str(target)}:
                        return
                except (ValueError, OSError):
                    pass  # The child may be finishing its very small marker write.
        if process.poll() is not None:
            raise UpdateError("Aplikasi versi baru berhenti sebelum siap digunakan.")
        time.sleep(0.25)
    raise UpdateError("Aplikasi versi baru belum mengonfirmasi kesiapan. Tutup aplikasi jika pemulihan diperlukan.")


def apply_update(staged_exe: Path, target_exe: Path) -> int:
    """Internal helper entry point. Main process must exit after launching this helper."""
    candidate = None
    replaced = False
    backup = None
    try:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            raise UpdateError("Pemasang pembaruan hanya tersedia dalam aplikasi EXE Windows.")
        staged = _stage_path(staged_exe)
        target = _target_path(target_exe)
        helper = _plain_path(Path(sys.executable))
        if helper != staged.parent / "helper.exe":
            raise UpdateError("Program pembantu pembaruan tidak valid.")
        request = json.loads(_plain_path(staged.parent / "request.json").read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if (set(request) != {"target", "original_sha256"} or request["target"] != str(target)
                or request["original_sha256"] != _digest(helper)
                or request["original_sha256"] != _digest(target)):
            raise UpdateError("Aplikasi tujuan telah berubah. Pembaruan dibatalkan.")
        release = _parse_manifest(_plain_path(staged.parent / "release.json").read_bytes())
        if _version(release.version) <= _version(app_metadata.APP_VERSION):
            raise UpdateError("Pembaruan harus menggunakan versi yang lebih baru.")
        _verify_file(staged, release)
        # Copy to the target volume, so replacement is atomic even from a USB drive.
        candidate = target.with_name("." + target.stem + ".update-" + uuid.uuid4().hex + ".exe")
        with candidate.open("xb") as output, staged.open("rb") as source:
            shutil.copyfileobj(source, output)
        _verify_file(candidate, release)
        backup = staged.parent / "previous.exe"
        with backup.open("xb") as output, target.open("rb") as source:
            shutil.copyfileobj(source, output)
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                # An in-use Windows executable cannot be replaced. No process is killed.
                _plain_path(target)
                if _digest(target) != request["original_sha256"]:
                    raise UpdateError("Aplikasi tujuan berubah selama pembaruan. Pembaruan dibatalkan.")
                os.replace(candidate, target)
                replaced = True
                break
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise UpdateError("Aplikasi masih terbuka atau folder tidak dapat ditulis. Tutup semua jendela aplikasi dan coba lagi.")
                time.sleep(0.5)
        marker = staged.parent / "ready.json"
        # Reject an old acknowledgement; only the new process may create this marker.
        if marker.exists():
            raise UpdateError("Penanda pembaruan sudah ada. Unduh ulang pembaruan.")
        process = subprocess.Popen([str(target), "--update-ready", str(marker)], **_process_args())
        _wait_ready(process, marker, target, release.version)
        # Installation is committed. Housekeeping failures must never trigger rollback.
        try:
            (staged.parent / "complete.json").write_text("{}", encoding="utf-8")
            _remove_stage_files(staged.parent)
        except OSError:
            pass
        return 0
    except Exception as exc:
        recovery = "Aplikasi lama dan data lembur tetap tersimpan."
        if replaced and backup is not None:
            try:
                # If starting the new EXE fails, restore the verified original.
                if _digest(target) != release.sha256 or _digest(backup) != request["original_sha256"]:
                    raise OSError("Recovery identity mismatch")
                with candidate.open("xb") as output, backup.open("rb") as source:
                    shutil.copyfileobj(source, output)
                os.replace(candidate, target)
            except (OSError, UpdateError):
                if backup.is_file():
                    recovery = "Salinan aplikasi lama tersimpan di:\n" + str(backup) + "\nData lembur tetap tersimpan."
                else:
                    recovery = "Pemulihan EXE belum berhasil. Pasang kembali EXE resmi. Data lembur tetap tersimpan."
        if candidate is not None:
            try:
                _plain_path(candidate).unlink(missing_ok=True)
            except (OSError, UpdateError):
                pass
        message = str(exc) if isinstance(exc, UpdateError) else "Pembaruan gagal dipasang. Periksa izin folder dan ruang penyimpanan."
        _show_error(message + "\n\n" + recovery)
        return 1
