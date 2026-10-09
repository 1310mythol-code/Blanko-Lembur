"""Check profile defaults without requiring a Tk window."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blanko_lembur import BlankoLemburApp


class ProfileUnitSyncTests(unittest.TestCase):
    def test_saved_defaults_preserve_independent_manual_edits(self):
        app = SimpleNamespace(
            profile=SimpleNamespace(unit_kerja="Instalasi Gizi"), manager_role_var=Mock(),
            asmen_role_var=Mock(),
        )
        app.manager_role_var.get.return_value = ""
        app.asmen_role_var.get.return_value = ""
        BlankoLemburApp._sync_official_units_from_profile(app, "")
        app.manager_role_var.set.assert_called_once_with("Instalasi Gizi")
        app.asmen_role_var.set.assert_called_once_with("Instalasi Gizi")
        app.manager_role_var.set.reset_mock()
        app.asmen_role_var.set.reset_mock()
        app.manager_role_var.get.return_value = "Pelayanan"
        app.asmen_role_var.get.return_value = "Instalasi Gizi"
        app.profile.unit_kerja = " Farmasi "
        BlankoLemburApp._sync_official_units_from_profile(app, "Instalasi Gizi")
        app.manager_role_var.set.assert_not_called()
        app.asmen_role_var.set.assert_called_once_with("Farmasi")


if __name__ == "__main__":
    unittest.main()
