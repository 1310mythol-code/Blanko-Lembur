"""Move the existing update signing key between Windows accounts without plaintext files."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from publish_update import DPAPI_MAGIC, _dpapi_protect, _dpapi_unprotect, _load_private_key
import app_metadata
from updater import _parse_manifest, canonical_payload

APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent
DEFAULT_DPAPI = Path(os.environ.get("LOCALAPPDATA", "")) / "BlankoLemburOtomatisDeveloper" / "update-signing-key.dpapi"


def _outside_repo(path: Path) -> bool:
    return not path.resolve().is_relative_to(REPO_DIR.resolve())


def _verify_key(private: Ed25519PrivateKey) -> None:
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("Kunci privat harus Ed25519.")
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if base64.b64encode(public).decode("ascii") != app_metadata.UPDATE_PUBLIC_KEY:
        raise ValueError("Kunci tidak cocok dengan UPDATE_PUBLIC_KEY aplikasi.")

    payload = {
        "version": "1.3", "notes": "Uji tanda tangan lokal",
        "url": "https://example.invalid/update.exe", "sha256": "0" * 64, "size": 2,
    }
    signature = base64.b64encode(private.sign(canonical_payload(payload))).decode("ascii")
    manifest = json.dumps({"payload": payload, "signature": signature}).encode("utf-8")
    _parse_manifest(manifest)


def _new_password() -> bytes:
    first = getpass.getpass("Password baru untuk berkas ekspor (minimal 12 karakter): ")
    second = getpass.getpass("Ulangi password baru: ")
    if len(first) < 12 or first != second:
        raise ValueError("Password harus cocok dan minimal 12 karakter.")
    return first.encode("utf-8")


def export_key(source: Path, destination: Path) -> None:
    if not _outside_repo(destination):
        raise ValueError("Simpan berkas ekspor di luar repository.")
    if destination.exists():
        raise FileExistsError("Berkas ekspor sudah ada; tidak ditimpa.")
    private = _load_private_key(source)
    _verify_key(private)
    password = _new_password()
    encoded = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )
    _verify_key(serialization.load_pem_private_key(encoded, password=password))
    with destination.open("xb") as output:
        output.write(encoded)
    print("Ekspor terenkripsi dibuat dan tanda tangannya diverifikasi: " + str(destination))


def import_key(source: Path, destination: Path) -> None:
    if not _outside_repo(destination):
        raise ValueError("Simpan kunci DPAPI di luar repository.")
    if destination.exists():
        raise FileExistsError("Kunci DPAPI sudah ada; tidak ditimpa.")
    private = _load_private_key(source)
    _verify_key(private)
    raw = private.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    encoded = DPAPI_MAGIC + _dpapi_protect(raw)
    _verify_key(serialization.load_der_private_key(_dpapi_unprotect(encoded[len(DPAPI_MAGIC):]), password=None))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(encoded)
    print("Kunci DPAPI akun Windows ini dibuat dan tanda tangannya diverifikasi: " + str(destination))


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrasi kunci update yang sudah ada; tidak membuat kunci baru.")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Buat salinan PEM terenkripsi berpassword untuk PC baru.")
    export.add_argument("--private-key", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    import_ = commands.add_parser("import", help="Lindungi kembali kunci dengan DPAPI akun Windows saat ini.")
    import_.add_argument("--encrypted-key", type=Path, required=True)
    import_.add_argument("--output", type=Path, default=DEFAULT_DPAPI)
    args = parser.parse_args()
    try:
        if args.command == "export":
            export_key(args.private_key, args.output)
        else:
            import_key(args.encrypted_key, args.output)
    except (FileNotFoundError, FileExistsError, ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
