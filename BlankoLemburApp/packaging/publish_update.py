"""Offline signing helper. This script never uploads files or publishes a release."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from updater import MAX_EXE_BYTES, _digest, _https_url, _version, canonical_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Siapkan tanda tangan pembaruan Blanko Lembur (tanpa unggahan).")
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen", help="Buat kunci privat terenkripsi; jangan simpan di repository.")
    keygen.add_argument("--private-key", type=Path, required=True)
    sign = commands.add_parser("sign", help="Buat manifest bertanda tangan dari EXE yang sudah diuji.")
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--exe", type=Path, required=True)
    sign.add_argument("--version", required=True)
    sign.add_argument("--url", required=True)
    sign.add_argument("--notes-file", type=Path)
    sign.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "keygen":
        if args.private_key.exists():
            parser.error("Berkas kunci sudah ada; tidak ditimpa.")
        password = getpass.getpass("Kata sandi baru untuk kunci privat (minimal 12 karakter): ")
        if len(password) < 12 or password != getpass.getpass("Ulangi kata sandi: "):
            parser.error("Kata sandi harus cocok dan minimal 12 karakter.")
        private = Ed25519PrivateKey.generate()
        encoded = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.BestAvailableEncryption(password.encode("utf-8")))
        with args.private_key.open("xb") as output:
            output.write(encoded)
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        print("UPDATE_PUBLIC_KEY = " + repr(base64.b64encode(public).decode("ascii")))
        print("Simpan kunci privat dan kata sandinya secara aman. Jangan unggah atau sertakan dalam EXE.")
        return

    _version(args.version)
    _https_url(args.url)
    size = args.exe.stat().st_size
    if not 2 <= size <= MAX_EXE_BYTES:
        parser.error("Ukuran EXE tidak valid atau melebihi 200 MiB.")
    with args.exe.open("rb") as stream:
        if stream.read(2) != b"MZ":
            parser.error("Berkas harus berupa EXE Windows.")
    digest = _digest(args.exe)
    notes = args.notes_file.read_text(encoding="utf-8-sig") if args.notes_file else ""
    if len(notes) > 10000:
        parser.error("Catatan pembaruan maksimal 10.000 karakter.")
    password = getpass.getpass("Kata sandi kunci privat: ").encode("utf-8")
    private = serialization.load_pem_private_key(args.private_key.read_bytes(), password=password)
    if not isinstance(private, Ed25519PrivateKey):
        parser.error("Kunci privat harus Ed25519.")
    payload = {"version": args.version, "notes": notes, "url": args.url, "sha256": digest, "size": size}
    signature = base64.b64encode(private.sign(canonical_payload(payload))).decode("ascii")
    with args.output.open("x", encoding="utf-8") as output:
        json.dump({"payload": payload, "signature": signature}, output, indent=2, ensure_ascii=True)
        output.write("\n")
    print("Manifest dibuat: " + str(args.output))
    print("EXE dan manifest belum diunggah. Unggah keduanya pada rilis yang sama setelah diuji.")


if __name__ == "__main__":
    main()
