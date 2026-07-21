from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from skylinedock.installer import build_install_plan, install
from skylinedock.scanner import ArchiveScanner


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_mod(self, contents: bytes = b"version one") -> Path:
        path = self.root / "UsefulMod.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("UsefulMod/UsefulMod.dll", contents)
            archive.writestr("UsefulMod/Localization/en-US.json", "{}")
        return path

    def test_installs_code_mod_and_writes_receipt(self) -> None:
        package = self.make_mod()
        report = ArchiveScanner().scan(package)
        app_data = self.root / "GameData"
        plan = build_install_plan(report, app_data)

        destination = install(plan)

        self.assertEqual(app_data / "Mods" / "UsefulMod", destination)
        self.assertEqual(b"version one", (destination / "UsefulMod.dll").read_bytes())
        receipt = app_data / ".skylinedock" / "receipts" / "UsefulMod.json"
        self.assertTrue(receipt.exists())
        self.assertEqual(str(destination), json.loads(receipt.read_text())["destination"])

    def test_replacement_creates_backup(self) -> None:
        package = self.make_mod(b"new")
        report = ArchiveScanner().scan(package)
        app_data = self.root / "GameData"
        existing = app_data / "Mods" / "UsefulMod"
        existing.mkdir(parents=True)
        (existing / "UsefulMod.dll").write_bytes(b"old")
        plan = build_install_plan(report, app_data)

        install(plan)

        backups = list((app_data / ".skylinedock" / "backups").iterdir())
        self.assertEqual(1, len(backups))
        self.assertEqual(b"old", (backups[0] / "UsefulMod.dll").read_bytes())
        self.assertEqual(b"new", (existing / "UsefulMod.dll").read_bytes())

    def test_installs_direct_cok_asset(self) -> None:
        package = self.root / "Building.cok"
        package.write_bytes(b"asset")
        report = ArchiveScanner().scan(package)
        app_data = self.root / "GameData"

        destination = install(build_install_plan(report, app_data))

        self.assertEqual(b"asset", (destination / "Building.cok").read_bytes())


if __name__ == "__main__":
    unittest.main()
