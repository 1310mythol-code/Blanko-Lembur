"""Updater checks use signed fake EXEs and mock network/processes; no real GUI starts."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app_metadata
import updater


class Response(io.BytesIO):
    def geturl(self):
        return "https://example.invalid/release"


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        # Keep all test mutations inside the authorized workspace.
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "BlankoLemburOtomatis"
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.patches = [
            patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}),
            patch.object(app_metadata, "APP_VERSION", "1.0"),
            patch.object(app_metadata, "UPDATE_MANIFEST_URL", "https://example.invalid/update.json"),
            patch.object(app_metadata, "UPDATE_PUBLIC_KEY", base64.b64encode(public).decode()),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.exe = b"MZ-fake-new-exe-for-test-only"

    def manifest(self, **changes):
        payload = {"version": "1.1", "notes": "Perbaikan untuk unit kerja", "url": "https://example.invalid/app.exe",
                   "sha256": hashlib.sha256(self.exe).hexdigest(), "size": len(self.exe)}
        payload.update(changes)
        signature = base64.b64encode(self.private.sign(updater.canonical_payload(payload))).decode()
        return json.dumps({"payload": payload, "signature": signature}).encode()

    def stage(self):
        release = updater._parse_manifest(self.manifest())
        with patch.object(updater, "_open", return_value=Response(self.exe)):
            return updater.download_update(release, self.data)

    def helper_state(self):
        staged = self.stage()
        target = self.root / "Aplikasi Lama.exe"
        target.write_bytes(b"MZ-original-fake-exe")
        helper = staged.parent / "helper.exe"
        helper.write_bytes(target.read_bytes())
        request = {"target": str(target), "original_sha256": updater._digest(target)}
        (staged.parent / "request.json").write_text(json.dumps(request), encoding="utf-8")
        return staged, target, helper

    def run_helper(self, staged, target, helper, **popen_options):
        if not popen_options:
            def mark_ready(argv, **kwargs):
                marker = Path(argv[2])
                marker.write_text(json.dumps({"version": "1.1", "target": str(target)}), encoding="utf-8")
                return Mock(poll=Mock(return_value=None))
            popen_options["side_effect"] = mark_ready
        with (patch.object(sys, "platform", "win32"), patch.object(sys, "frozen", True, create=True),
              patch.object(sys, "executable", str(helper)), patch.object(updater, "_show_error") as error,
              patch.object(updater.subprocess, "Popen", **popen_options) as popen):
            result = updater.apply_update(staged, target)
        return result, popen, error

    def test_blank_configuration_has_clear_message_and_no_network(self):
        with patch.object(app_metadata, "UPDATE_MANIFEST_URL", ""), patch.object(updater, "_open") as network:
            self.assertFalse(updater.is_configured())
            with self.assertRaisesRegex(updater.UpdateError, "belum diaktifkan"):
                updater.check_for_update()
            network.assert_not_called()

    def test_signed_new_release(self):
        with patch.object(updater, "_open", return_value=Response(self.manifest())):
            release = updater.check_for_update()
        self.assertEqual(release.version, "1.1")

    def test_current_and_older_versions_are_not_updates(self):
        for version in ("0.9", "1.0", "1.0.0", "1.0.0.0"):
            with self.subTest(version=version), patch.object(updater, "_open", return_value=Response(self.manifest(version=version))):
                self.assertIsNone(updater.check_for_update())
        self.assertGreater(updater._version("1.10"), updater._version("1.9"))

    def test_manifest_tamper_rejected(self):
        payload = json.loads(self.manifest())
        payload["payload"]["url"] = "https://example.invalid/tampered.exe"
        with self.assertRaisesRegex(updater.UpdateError, "Keaslian"):
            updater._parse_manifest(json.dumps(payload).encode())

    def test_wrong_key_rejected(self):
        with patch.object(app_metadata, "UPDATE_PUBLIC_KEY", base64.b64encode(b"a" * 32).decode()):
            with self.assertRaises(updater.UpdateError):
                updater._parse_manifest(self.manifest())

    def test_bad_manifest_fields_rejected(self):
        for changes in ({"size": True}, {"size": updater.MAX_EXE_BYTES + 1}, {"version": "v1.1"},
                        {"sha256": "bad"}, {"url": "http://example.invalid/file"}, {"notes": 1}):
            with self.subTest(changes=changes), self.assertRaises(updater.UpdateError):
                updater._parse_manifest(self.manifest(**changes))

    def test_duplicate_json_and_oversize_rejected(self):
        for raw in (b'{"payload":{},"payload":{},"signature":""}', b" " * (updater.MAX_MANIFEST_BYTES + 1)):
            with self.assertRaises(updater.UpdateError):
                updater._parse_manifest(raw)

    def test_http_and_credentials_rejected(self):
        for url in ("http://example.invalid/file", "file:///C:/file", "https://name:password@example.invalid/",
                    "https://example.invalid:8080/file", "https://example.invalid/file\n", "https://example.invalid/#fragment"):
            with self.subTest(url=url), self.assertRaises(updater.UpdateError):
                updater._https_url(url)
        with self.assertRaises(updater.UpdateError):
            updater._HTTPSRedirects().redirect_request(None, None, 302, "", {}, "http://example.invalid/file")

    def test_network_error_is_friendly(self):
        with patch.object(updater, "_open", side_effect=URLError("offline")):
            with self.assertRaisesRegex(updater.UpdateError, "koneksi internet"):
                updater.check_for_update()

    def test_missing_first_github_release_means_no_update(self):
        def missing_release(_url):
            raise HTTPError(
                app_metadata.UPDATE_MANIFEST_URL, 404, "Not Found", {}, None
            )

        with patch.object(updater, "_open", side_effect=missing_release):
            self.assertIsNone(updater.check_for_update())

    def test_good_download_has_manifest_and_verified_content(self):
        staged = self.stage()
        self.assertEqual(staged.read_bytes(), self.exe)
        self.assertTrue((staged.parent / "release.json").is_file())

    def test_tampered_release_dataclass_rejected_before_network(self):
        release = replace(updater._parse_manifest(self.manifest()), sha256="0" * 64)
        with patch.object(updater, "_open") as network:
            with self.assertRaises(updater.UpdateError):
                updater.download_update(release, self.data)
            network.assert_not_called()

    def test_bad_hash_size_and_truncated_download_cleaned(self):
        for contents in (self.exe + b"extra", self.exe[:-1], b"MZ" + b"x" * (len(self.exe) - 2)):
            with self.subTest(contents=contents), patch.object(updater, "_open", return_value=Response(contents)):
                with self.assertRaises(updater.UpdateError):
                    updater.download_update(updater._parse_manifest(self.manifest()), self.data)
            self.assertEqual(list((self.data / "updates").iterdir()), [])

    def test_download_network_failure_cleaned(self):
        with patch.object(updater, "_open", side_effect=URLError("offline")):
            with self.assertRaisesRegex(updater.UpdateError, "tidak dapat diunduh"):
                updater.download_update(updater._parse_manifest(self.manifest()), self.data)
        self.assertEqual(list((self.data / "updates").iterdir()), [])

    def test_unexpected_data_directory_rejected(self):
        with self.assertRaises(updater.UpdateError):
            updater.download_update(updater._parse_manifest(self.manifest()), self.root / "other")

    def test_launch_copies_original_and_uses_argument_vector(self):
        staged = self.stage()
        target = self.root / "Aplikasi yang dipakai.exe"
        target.write_bytes(b"MZ-old")
        with (patch.object(sys, "platform", "win32"), patch.object(sys, "frozen", True, create=True),
              patch.object(sys, "executable", str(target)), patch.object(updater.subprocess, "Popen") as popen):
            updater.launch_update(staged, target)
        helper = staged.parent / "helper.exe"
        self.assertEqual(helper.read_bytes(), target.read_bytes())
        argv = popen.call_args.args[0]
        self.assertEqual(argv, [str(helper), "--apply-update", str(staged), str(target)])
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_helper_success_replaces_fake_exe_preserves_csv(self):
        staged, target, helper = self.helper_state()
        csv = self.data / "records.csv"
        csv.write_bytes(b"existing-user-data")
        result, popen, error = self.run_helper(staged, target, helper)
        self.assertEqual(result, 0)
        self.assertEqual(target.read_bytes(), self.exe)
        self.assertEqual(csv.read_bytes(), b"existing-user-data")
        self.assertEqual(popen.call_args.args[0], [str(target), "--update-ready", str(staged.parent / "ready.json")])
        error.assert_not_called()
        updater.cleanup_updates()
        self.assertFalse(staged.parent.exists())
        self.assertTrue(csv.exists())

    def test_helper_retries_locked_target_without_killing_process(self):
        staged, target, helper = self.helper_state()
        real_replace = os.replace
        calls = []
        def replace_once_locked(source, dest):
            calls.append((source, dest))
            if len(calls) == 1:
                raise PermissionError("in use")
            return real_replace(source, dest)
        with patch.object(updater.os, "replace", side_effect=replace_once_locked), patch.object(updater.time, "sleep") as sleep:
            result, _, _ = self.run_helper(staged, target, helper)
        self.assertEqual(result, 0)
        sleep.assert_called_once_with(0.5)

    def test_helper_permission_failure_keeps_old_exe(self):
        staged, target, helper = self.helper_state()
        original = target.read_bytes()
        with (patch.object(updater.os, "replace", side_effect=PermissionError("read only")),
              patch.object(updater, "REPLACE_ATTEMPTS", 2), patch.object(updater.time, "sleep")):
            result, popen, error = self.run_helper(staged, target, helper)
        self.assertEqual(result, 1)
        self.assertEqual(target.read_bytes(), original)
        popen.assert_not_called()
        self.assertIn("Aplikasi lama", error.call_args.args[0])
        self.assertEqual(list(self.root.glob(".*.update-*.exe")), [])

    def test_helper_launch_failure_rolls_back(self):
        staged, target, helper = self.helper_state()
        original = target.read_bytes()
        result, _, error = self.run_helper(staged, target, helper, side_effect=OSError("cannot start"))
        self.assertEqual(result, 1)
        self.assertEqual(target.read_bytes(), original)
        self.assertIn("Aplikasi lama", error.call_args.args[0])

    def test_helper_child_exit_before_ready_rolls_back(self):
        staged, target, helper = self.helper_state()
        original = target.read_bytes()
        result, _, error = self.run_helper(staged, target, helper, return_value=Mock(poll=Mock(return_value=1)))
        self.assertEqual(result, 1)
        self.assertEqual(target.read_bytes(), original)
        self.assertIn("berhenti sebelum", error.call_args.args[0])

    def test_helper_ready_timeout_rolls_back(self):
        staged, target, helper = self.helper_state()
        original = target.read_bytes()
        with patch.object(updater, "READY_TIMEOUT", 0):
            result, _, error = self.run_helper(staged, target, helper, return_value=Mock(poll=Mock(return_value=None)))
        self.assertEqual(result, 1)
        self.assertEqual(target.read_bytes(), original)
        self.assertIn("belum mengonfirmasi", error.call_args.args[0])

    def test_success_cleanup_failure_does_not_roll_back(self):
        staged, target, helper = self.helper_state()
        original_write = Path.write_text
        def fail_complete_write(path, data, *args, **kwargs):
            if path.name == "complete.json":
                raise PermissionError("cleanup blocked")
            return original_write(path, data, *args, **kwargs)
        with patch.object(Path, "write_text", fail_complete_write):
            result, _, error = self.run_helper(staged, target, helper)
        self.assertEqual(result, 0)
        self.assertEqual(target.read_bytes(), self.exe)
        self.assertTrue((staged.parent / "previous.exe").exists())
        error.assert_not_called()

    def test_new_application_confirms_version_hash_and_target(self):
        staged, target, _ = self.helper_state()
        target.write_bytes(self.exe)
        marker = staged.parent / "ready.json"
        with (patch.object(sys, "platform", "win32"), patch.object(sys, "frozen", True, create=True),
              patch.object(sys, "executable", str(target))):
            with self.assertRaisesRegex(updater.UpdateError, "Versi aplikasi"):
                updater.confirm_update_ready(marker)
            self.assertFalse(marker.exists())
            with patch.object(app_metadata, "APP_VERSION", "1.1"):
                updater.confirm_update_ready(marker)
        self.assertEqual(json.loads(marker.read_text()), {"version": "1.1", "target": str(target)})

    def test_failed_helper_spawn_can_be_retried(self):
        staged = self.stage()
        target = self.root / "Aplikasi.exe"
        target.write_bytes(b"MZ-old")
        with (patch.object(sys, "platform", "win32"), patch.object(sys, "frozen", True, create=True),
              patch.object(sys, "executable", str(target)), patch.object(updater.subprocess, "Popen", side_effect=OSError("blocked"))):
            with self.assertRaises(updater.UpdateError):
                updater.launch_update(staged, target)
        self.assertTrue(staged.exists())
        self.assertFalse((staged.parent / "helper.exe").exists())
        self.assertFalse((staged.parent / "request.json").exists())
        with (patch.object(sys, "platform", "win32"), patch.object(sys, "frozen", True, create=True),
              patch.object(sys, "executable", str(target)), patch.object(updater.subprocess, "Popen") as popen):
            updater.launch_update(staged, target)
        popen.assert_called_once()

    def test_helper_wrong_path_and_changed_state_rejected(self):
        staged, target, helper = self.helper_state()
        for staged_arg in (self.root / "update.exe", staged.parent / "other.exe"):
            result, popen, _ = self.run_helper(staged_arg, target, helper)
            self.assertEqual(result, 1)
            popen.assert_not_called()
        target.write_bytes(b"MZ-some-other-app")
        result, popen, _ = self.run_helper(staged, target, helper)
        self.assertEqual(result, 1)
        popen.assert_not_called()
        self.assertEqual(target.read_bytes(), b"MZ-some-other-app")

    def test_helper_reverifies_download_before_replacement(self):
        staged, target, helper = self.helper_state()
        original = target.read_bytes()
        staged.write_bytes(b"MZ-tampered")
        result, popen, _ = self.run_helper(staged, target, helper)
        self.assertEqual(result, 1)
        self.assertEqual(target.read_bytes(), original)
        popen.assert_not_called()

    def test_cleanup_leaves_unrelated_files_and_incomplete_stages(self):
        staged = self.stage()
        unknown = staged.parent / "do-not-delete.csv"
        unknown.write_bytes(b"keep")
        updater.cleanup_updates()
        self.assertTrue(staged.exists())
        (staged.parent / "complete.json").write_text("{}")
        updater.cleanup_updates()
        self.assertTrue(unknown.is_file())
        self.assertFalse(staged.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
