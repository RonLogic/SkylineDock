from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from skylinedock.models import PackageKind
from skylinedock.scanner import ArchiveScanner
from skylinedock.source_builder import (
    CommandResult,
    SourceBuildError,
    SourceBuildPrerequisites,
    build_trusted_source,
    check_source_build_prerequisites,
    inspect_source_build,
)


class SourceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = self.root / "Traffic-main.zip"
        with zipfile.ZipFile(self.package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Traffic-main/Traffic.sln", "solution")
            archive.writestr(
                "Traffic-main/Code/Traffic.csproj",
                """<Project><PropertyGroup><Title>Traffic</Title><Version>1.0</Version></PropertyGroup>
                <Target><Exec Command="npm run build"/></Target></Project>""",
            )
            archive.writestr("Traffic-main/Code/A.cs", "class A {}")
            archive.writestr("Traffic-main/Code/B.cs", "class B {}")
            archive.writestr("Traffic-main/Code/C.cs", "class C {}")
            archive.writestr(
                "Traffic-main/Code/Properties/PublishConfiguration.xml",
                '<Publish><DisplayName Value="Traffic"/><ModId Value="80095"/></Publish>',
            )
            archive.writestr("Traffic-main/global.json", '{"sdk":{"version":"8.0.0"}}')
            archive.writestr(
                "Traffic-main/UI/package.json",
                '{"scripts":{"build":"webpack"},"dependencies":{}}',
            )
            archive.writestr("Traffic-main/UI/package-lock.json", '{"lockfileVersion":3}')
            archive.writestr(
                "Traffic-main/UI/webpack.config.js",
                "const output = process.env.CSII_USERDATAPATH;",
            )
        self.report = ArchiveScanner().scan(self.package)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prerequisites(self) -> SourceBuildPrerequisites:
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        (tools / "Mod.props").write_text("")
        (tools / "Mod.targets").write_text("")
        return SourceBuildPrerequisites(
            windows_supported=True,
            steam_game_path=self.root / "game",
            tool_path=tools,
            dotnet_executable="dotnet",
            npm_executable="npm",
            issues=[],
        )

    def test_inspects_toolchain_requirements(self) -> None:
        inspection = inspect_source_build(self.report)

        self.assertEqual(PackageKind.SOURCE_REPOSITORY, self.report.kind)
        self.assertEqual("Traffic", inspection.mod_name)
        self.assertEqual("8.0.0", inspection.dotnet_sdk_version)
        self.assertEqual(["Traffic-main/UI"], inspection.ui_directories)
        self.assertIn("CSII_USERDATAPATH", inspection.required_environment)
        self.assertTrue(any("Exec" in warning for warning in inspection.warnings))

    def test_build_requires_explicit_trust_confirmation(self) -> None:
        with self.assertRaises(SourceBuildError):
            build_trusted_source(
                self.report,
                self.root / "work",
                trusted_source_confirmed=False,
                prerequisites=self.prerequisites(),
            )

    def test_accepts_a_manually_selected_game_folder(self) -> None:
        game = self.root / "Cities Skylines II"
        game.mkdir()
        (game / "Cities2.exe").write_bytes(b"MZ")

        prerequisites = check_source_build_prerequisites(
            inspect_source_build(self.report),
            game_path=game,
        )

        self.assertEqual(game.resolve(), prerequisites.steam_game_path)
        self.assertFalse(any("selected game folder" in issue for issue in prerequisites.issues))

    def test_build_redirects_output_and_validates_compiled_mod(self) -> None:
        commands: list[list[str]] = []

        def fake_runner(command: list[str], cwd: Path, env: dict[str, str]) -> CommandResult:
            commands.append(command)
            if "build" in command:
                output = Path(env["CSII_USERDATAPATH"]) / "Mods" / "Traffic"
                output.mkdir(parents=True)
                (output / "Traffic.dll").write_bytes(b"MZ compiled")
                (output / "Traffic.mjs").write_text("export {};")
            return CommandResult(0, "ok")

        result = build_trusted_source(
            self.report,
            self.root / "work",
            trusted_source_confirmed=True,
            prerequisites=self.prerequisites(),
            runner=fake_runner,
        )

        self.assertEqual(PackageKind.READY_CODE_MOD, result.compiled_report.kind)
        self.assertEqual("Traffic", result.compiled_report.display_name)
        self.assertEqual("ci", commands[0][1])
        self.assertEqual("build", commands[1][1])


if __name__ == "__main__":
    unittest.main()
