from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from .models import PackageKind, ScanReport, SourceType
from .scanner import ArchiveScanner
from .steam import detect_cs2_steam_installation


class SourceBuildError(RuntimeError):
    pass


@dataclass(slots=True)
class SourceBuildInspection:
    mod_name: str
    source_root: str | None
    solution_file: str
    project_files: list[str]
    ui_directories: list[str]
    dotnet_sdk_version: str | None = None
    required_environment: list[str] = field(default_factory=list)
    npm_scripts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourceBuildPrerequisites:
    windows_supported: bool
    steam_game_path: Path | None
    tool_path: Path | None
    dotnet_executable: str | None
    npm_executable: str | None
    issues: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.issues


@dataclass(slots=True)
class CommandResult:
    return_code: int
    output: str


@dataclass(slots=True)
class SourceBuildResult:
    output_directory: Path
    compiled_report: ScanReport
    logs: list[str]


class CommandRunner(Protocol):
    def __call__(self, command: list[str], cwd: Path, env: dict[str, str]) -> CommandResult: ...


def inspect_source_build(report: ScanReport) -> SourceBuildInspection:
    if report.kind != PackageKind.SOURCE_REPOSITORY:
        raise SourceBuildError("Only a detected source repository can be built in source mode.")

    if report.source_type == SourceType.ZIP:
        return _inspect_zip(report)
    if report.source_type == SourceType.DIRECTORY:
        return _inspect_directory(report)
    raise SourceBuildError(f"Unsupported source type: {report.source_type.value}")


def check_source_build_prerequisites(
    inspection: SourceBuildInspection,
    steam_root: str | Path | None = None,
) -> SourceBuildPrerequisites:
    issues: list[str] = []
    windows_supported = os.name == "nt"
    if not windows_supported:
        issues.append("Source builds currently require Windows.")

    steam = detect_cs2_steam_installation(steam_root)
    if steam is None:
        issues.append("Cities: Skylines II was not detected in a Steam library.")

    tool_value = os.environ.get("CSII_TOOLPATH")
    tool_path = Path(tool_value).expanduser() if tool_value else None
    if tool_path is None or not (tool_path / "Mod.props").is_file() or not (tool_path / "Mod.targets").is_file():
        issues.append(
            "The official CS2 modding toolchain is missing or CSII_TOOLPATH is not configured."
        )

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        version = inspection.dotnet_sdk_version or "the required .NET SDK"
        issues.append(f"dotnet was not found; install {version} or a compatible newer SDK.")

    npm = shutil.which("npm")
    if inspection.ui_directories and npm is None:
        issues.append("npm was not found, but this source package contains a UI project.")

    return SourceBuildPrerequisites(
        windows_supported=windows_supported,
        steam_game_path=steam.game_path if steam else None,
        tool_path=tool_path,
        dotnet_executable=dotnet,
        npm_executable=npm,
        issues=issues,
    )


def build_trusted_source(
    report: ScanReport,
    work_root: str | Path,
    *,
    trusted_source_confirmed: bool,
    prerequisites: SourceBuildPrerequisites | None = None,
    runner: CommandRunner | None = None,
) -> SourceBuildResult:
    """Build source in a temporary copy and redirect normal toolchain output.

    This is containment, not a security sandbox. MSBuild and npm scripts are
    executable code and may access anything available to the current user.
    """

    if not trusted_source_confirmed:
        raise SourceBuildError(
            "Building source executes project scripts. Explicit trusted-source confirmation is required."
        )

    inspection = inspect_source_build(report)
    prerequisites = prerequisites or check_source_build_prerequisites(inspection)
    if not prerequisites.ready:
        raise SourceBuildError("\n".join(prerequisites.issues))

    command_runner = runner or _run_command
    root = Path(work_root).expanduser().resolve()
    source_dir = root / "source"
    user_data_dir = root / "build-user-data"
    source_dir.mkdir(parents=True, exist_ok=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    _copy_source(report, source_dir)

    env = os.environ.copy()
    env["CSII_USERDATAPATH"] = str(user_data_dir)
    if prerequisites.tool_path:
        env["CSII_TOOLPATH"] = str(prerequisites.tool_path)

    logs: list[str] = []
    project_root = source_dir
    solution = project_root / _strip_source_root(inspection.solution_file, inspection.source_root)
    if not solution.is_file():
        raise SourceBuildError(f"Solution file was not found after extraction: {solution}")

    for ui_relative in inspection.ui_directories:
        ui_dir = project_root / _strip_source_root(ui_relative, inspection.source_root)
        lock_file = ui_dir / "package-lock.json"
        if not lock_file.is_file():
            raise SourceBuildError(
                f"Automatic source build requires a package-lock.json file: {ui_dir}"
            )
        command = [
            prerequisites.npm_executable or "npm",
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ]
        _execute(command_runner, command, ui_dir, env, logs)

    command = [
        prerequisites.dotnet_executable or "dotnet",
        "build",
        str(solution),
        "--configuration",
        "Release",
        "--nologo",
    ]
    _execute(command_runner, command, project_root, env, logs)

    mods_root = user_data_dir / "Mods"
    candidates: list[ScanReport] = []
    if mods_root.is_dir():
        for folder in mods_root.iterdir():
            if folder.is_dir():
                candidate = ArchiveScanner().scan(folder)
                if candidate.kind == PackageKind.READY_CODE_MOD and candidate.can_install:
                    candidates.append(candidate)

    if not candidates:
        raise SourceBuildError(
            "The build completed but did not produce a valid mod in the redirected Mods folder."
        )

    expected = inspection.mod_name.casefold()
    compiled = next(
        (candidate for candidate in candidates if candidate.display_name.casefold() == expected),
        candidates[0] if len(candidates) == 1 else None,
    )
    if compiled is None:
        names = ", ".join(item.display_name for item in candidates)
        raise SourceBuildError(f"The build produced multiple ambiguous mods: {names}")

    return SourceBuildResult(compiled.source_path, compiled, logs)


def _inspect_zip(report: ScanReport) -> SourceBuildInspection:
    with zipfile.ZipFile(report.source_path) as archive:
        entries = {
            item.filename.replace("\\", "/"): item
            for item in archive.infolist()
            if not item.is_dir()
        }

        def read(name: str) -> bytes:
            info = entries[name]
            if info.file_size > 2 * 1024 * 1024:
                raise SourceBuildError(f"Build metadata is too large: {name}")
            return archive.read(info)

        return _inspect_entries(report, list(entries), read)


def _inspect_directory(report: ScanReport) -> SourceBuildInspection:
    entries = [item.relative_to(report.source_path).as_posix() for item in report.source_path.rglob("*") if item.is_file()]

    def read(name: str) -> bytes:
        path = report.source_path / PurePosixPath(name)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise SourceBuildError(f"Build metadata is too large: {name}")
        return path.read_bytes()

    return _inspect_entries(report, entries, read)


def _inspect_entries(
    report: ScanReport,
    entries: list[str],
    read: Callable[[str], bytes],
) -> SourceBuildInspection:
    solutions = sorted((name for name in entries if name.lower().endswith(".sln")), key=len)
    if not solutions:
        raise SourceBuildError("No Visual Studio solution (.sln) was detected.")

    dotnet_version: str | None = None
    global_json = next((name for name in entries if name.lower().endswith("global.json")), None)
    if global_json:
        try:
            dotnet_version = json.loads(read(global_json).decode("utf-8-sig"))["sdk"]["version"]
        except (KeyError, ValueError, UnicodeError):
            pass

    ui_directories: list[str] = []
    npm_scripts: dict[str, str] = {}
    warnings: list[str] = [
        "Building source executes MSBuild targets and npm scripts with the current user's permissions.",
        "The temporary build directory reduces accidental game-file changes but is not a security sandbox.",
    ]
    searchable_text: list[str] = []

    for name in entries:
        lower = name.lower()
        if lower.endswith("package.json"):
            try:
                package = json.loads(read(name).decode("utf-8-sig"))
                scripts = package.get("scripts") or {}
                npm_scripts.update({str(key): str(value) for key, value in scripts.items()})
                ui_directories.append(str(PurePosixPath(name).parent))
            except (ValueError, UnicodeError):
                warnings.append(f"Could not parse {name}.")
        if lower.endswith((".csproj", ".targets", "webpack.config.js")):
            try:
                searchable_text.append(read(name).decode("utf-8-sig", errors="replace"))
            except OSError:
                pass

    required_environment = sorted(
        set(re.findall(r"\bCSII_[A-Z0-9_]+\b", "\n".join(searchable_text)))
    )
    if any("<Exec" in text for text in searchable_text):
        warnings.append("The project contains an MSBuild Exec task.")

    return SourceBuildInspection(
        mod_name=report.display_name,
        source_root=report.common_root,
        solution_file=solutions[0],
        project_files=report.project_files,
        ui_directories=sorted(set(ui_directories)),
        dotnet_sdk_version=dotnet_version,
        required_environment=required_environment,
        npm_scripts=npm_scripts,
        warnings=warnings,
    )


def _copy_source(report: ScanReport, destination: Path) -> None:
    if report.source_type == SourceType.ZIP:
        with zipfile.ZipFile(report.source_path) as archive:
            prefix = f"{report.common_root}/" if report.common_root else ""
            for item in archive.infolist():
                if item.is_dir():
                    continue
                normalized = item.filename.replace("\\", "/")
                relative = normalized[len(prefix) :] if prefix and normalized.startswith(prefix) else normalized
                target = _safe_target(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return

    if report.source_type == SourceType.DIRECTORY:
        for source in report.source_path.rglob("*"):
            if source.is_symlink():
                raise SourceBuildError(f"Source symlink is not accepted: {source}")
            if not source.is_file():
                continue
            target = _safe_target(destination, source.relative_to(report.source_path).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return

    raise SourceBuildError(f"Unsupported source type: {report.source_type.value}")


def _safe_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", relative):
        raise SourceBuildError(f"Unsafe source path: {relative}")
    target = (root / Path(*pure.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise SourceBuildError(f"Source path escapes the build directory: {relative}")
    return target


def _strip_source_root(value: str, source_root: str | None) -> Path:
    pure = PurePosixPath(value)
    if source_root and pure.parts and pure.parts[0] == source_root:
        pure = PurePosixPath(*pure.parts[1:])
    return Path(*pure.parts)


def _execute(
    runner: CommandRunner,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    logs: list[str],
) -> None:
    result = runner(command, cwd, env)
    logs.append(f"> {' '.join(command)}\n{result.output}".rstrip())
    if result.return_code != 0:
        tail = result.output[-4_000:]
        raise SourceBuildError(f"Build command failed ({result.return_code}):\n{tail}")


def _run_command(command: list[str], cwd: Path, env: dict[str, str]) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30 * 60,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout)
