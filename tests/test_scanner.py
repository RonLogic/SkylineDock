from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from skylinedock.models import PackageKind
from skylinedock.scanner import ArchiveScanner


class ArchiveScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.scanner = ArchiveScanner()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_zip(self, name: str, files: dict[str, bytes | str]) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, content in files.items():
                archive.writestr(filename, content)
        return path

    def test_detects_source_repository_and_publish_metadata(self) -> None:
        package = self.make_zip(
            "Traffic-main.zip",
            {
                "Traffic-main/Traffic.sln": "",
                "Traffic-main/Code/Traffic.csproj": """
                    <Project><PropertyGroup><Title>Traffic</Title><Version>1.2.3</Version>
                    <Authors>Author</Authors></PropertyGroup></Project>
                """,
                "Traffic-main/Code/A.cs": "class A {}",
                "Traffic-main/Code/B.cs": "class B {}",
                "Traffic-main/UI/view.tsx": "export default {};",
                "Traffic-main/Code/Properties/PublishConfiguration.xml": """
                    <Publish><ModId Value="80095"/><DisplayName Value="Traffic"/>
                    <ModVersion Value="0.2.12.1"/><GameVersion Value="1.5.*"/>
                    <Tag Value="Code Mod"/></Publish>
                """,
            },
        )

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.SOURCE_REPOSITORY, report.kind)
        self.assertEqual("Traffic", report.metadata.display_name)
        self.assertEqual("0.2.12.1", report.metadata.version)
        self.assertEqual("1.5.*", report.metadata.game_version)
        self.assertEqual("80095", report.metadata.paradox_mod_id)
        self.assertEqual("Traffic-main", report.common_root)
        self.assertFalse(report.can_install)

    def test_detects_ready_code_mod(self) -> None:
        package = self.make_zip(
            "UsefulMod.zip",
            {
                "UsefulMod/UsefulMod.dll": b"MZ fake test assembly",
                "UsefulMod/Localization/en-US.json": "{}",
            },
        )

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.READY_CODE_MOD, report.kind)
        self.assertTrue(report.can_install)

    def test_infers_primary_mod_name_from_compiled_outputs(self) -> None:
        package = self.make_zip(
            "download-id.zip",
            {
                "Reinforced.Typings.dll": b"MZ dependency",
                "Traffic.dll": b"MZ main",
                "Traffic.mjs": "export {};",
                "Traffic.css": "body {}",
                "Traffic_win_x86_64.dll": b"native",
            },
        )

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.READY_CODE_MOD, report.kind)
        self.assertEqual("Traffic", report.metadata.display_name)

    def test_detects_asset_package(self) -> None:
        package = self.make_zip("Asset.zip", {"Asset/Building.cok": b"test"})

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.ASSET_PACKAGE, report.kind)
        self.assertTrue(report.can_install)

    def test_detects_direct_cok_asset(self) -> None:
        package = self.root / "Building.cok"
        package.write_bytes(b"asset")

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.ASSET_PACKAGE, report.kind)
        self.assertTrue(report.can_install)

    def test_blocks_case_insensitive_duplicate_paths(self) -> None:
        package = self.make_zip(
            "Duplicate.zip",
            {"Mod/Mod.dll": b"first", "mod/mod.DLL": b"second"},
        )

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.INVALID, report.kind)
        self.assertTrue(any("Duplicate" in error for error in report.errors))

    def test_blocks_zip_slip(self) -> None:
        package = self.make_zip("Unsafe.zip", {"../evil.dll": b"test"})

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.INVALID, report.kind)
        self.assertTrue(any("traversal" in error for error in report.errors))
        self.assertFalse(report.can_install)

    def test_marks_source_and_binaries_as_mixed(self) -> None:
        package = self.make_zip(
            "Mixed.zip",
            {
                "Mixed/Mod.sln": "",
                "Mixed/Mod.csproj": "<Project/>",
                "Mixed/A.cs": "",
                "Mixed/B.cs": "",
                "Mixed/C.cs": "",
                "Mixed/Mod.dll": b"MZ",
            },
        )

        report = self.scanner.scan(package)

        self.assertEqual(PackageKind.MIXED_SOURCE_PACKAGE, report.kind)
        self.assertFalse(report.can_install)


if __name__ == "__main__":
    unittest.main()
