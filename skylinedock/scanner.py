from __future__ import annotations

import re
import stat
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from .models import ModMetadata, PackageKind, ScanReport, SourceType


ReadBytes = Callable[[str, int], bytes]


class ScanError(RuntimeError):
    pass


class ArchiveScanner:
    """Safely inspects a package without extracting or executing its contents."""

    MAX_ENTRIES = 20_000
    MAX_UNCOMPRESSED_SIZE = 2 * 1024 * 1024 * 1024
    MAX_METADATA_SIZE = 2 * 1024 * 1024
    MAX_COMPRESSION_RATIO = 1_000
    SOURCE_EXTENSIONS = {".cs", ".csproj", ".sln", ".ts", ".tsx"}

    def scan(self, source: str | Path) -> ScanReport:
        path = Path(source).expanduser().resolve()

        if path.is_dir():
            return self._scan_directory(path)

        if not path.exists():
            return self._invalid(path, SourceType.UNKNOWN, "The selected path does not exist.")

        if path.suffix.lower() in {".rar", ".7z"}:
            report = self._invalid(
                path,
                SourceType.UNSUPPORTED_ARCHIVE,
                "RAR and 7Z scanning is planned, but this MVP accepts ZIP files and folders only.",
            )
            report.recommended_action = "Extract the archive first, then drop the resulting folder."
            return report

        if path.suffix.lower() in {".dll", ".cok"}:
            kind = (
                PackageKind.READY_CODE_MOD
                if path.suffix.lower() == ".dll"
                else PackageKind.ASSET_PACKAGE
            )
            return ScanReport(
                source_path=path,
                source_type=SourceType.DIRECT_FILE,
                kind=kind,
                metadata=ModMetadata(display_name=path.stem),
                file_count=1,
                uncompressed_size=path.stat().st_size,
                dll_files=[path.name] if kind == PackageKind.READY_CODE_MOD else [],
                asset_files=[path.name] if kind == PackageKind.ASSET_PACKAGE else [],
                warnings=(
                    ["A standalone DLL may be missing localization or other companion files."]
                    if kind == PackageKind.READY_CODE_MOD
                    else []
                ),
                recommended_action=(
                    "Ready for installation, but a complete ZIP or folder is safer when available."
                    if kind == PackageKind.READY_CODE_MOD
                    else "Ready for a safe preview and installation into ImportedData."
                ),
            )

        if path.suffix.lower() != ".zip" or not zipfile.is_zipfile(path):
            return self._invalid(path, SourceType.UNKNOWN, "This is not a readable ZIP package.")

        return self._scan_zip(path)

    def _scan_zip(self, path: Path) -> ScanReport:
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                errors, warnings = self._validate_zip(infos)
                name_to_info = {
                    self._normalize_name(item.filename): item for item in infos if not item.is_dir()
                }
                names = list(name_to_info)

                def read_bytes(name: str, limit: int) -> bytes:
                    info = name_to_info[name]
                    if info.file_size > limit:
                        raise ScanError(f"Metadata file is larger than {limit:,} bytes: {name}")
                    with archive.open(info, "r") as stream:
                        return stream.read(limit + 1)

                report = self._analyze(
                    path,
                    SourceType.ZIP,
                    names,
                    read_bytes,
                    sum(item.file_size for item in infos),
                )
                report.errors.extend(errors)
                report.warnings.extend(warnings)
                if errors:
                    report.kind = PackageKind.INVALID
                    report.recommended_action = "Do not install this archive. Review the reported safety errors."
                return report
        except (OSError, zipfile.BadZipFile, ScanError) as exc:
            return self._invalid(path, SourceType.ZIP, str(exc))

    def _scan_directory(self, path: Path) -> ScanReport:
        names: list[str] = []
        total_size = 0
        errors: list[str] = []

        try:
            for item in path.rglob("*"):
                if item.is_symlink():
                    errors.append(f"Symbolic links are not accepted: {item.relative_to(path)}")
                    continue
                if not item.is_file():
                    continue
                names.append(item.relative_to(path).as_posix())
                total_size += item.stat().st_size
                if len(names) > self.MAX_ENTRIES:
                    errors.append(f"Folder contains more than {self.MAX_ENTRIES:,} files.")
                    break
                if total_size > self.MAX_UNCOMPRESSED_SIZE:
                    errors.append("Folder is larger than the 2 GiB MVP safety limit.")
                    break

            def read_bytes(name: str, limit: int) -> bytes:
                target = (path / PurePosixPath(name)).resolve()
                if not target.is_relative_to(path):
                    raise ScanError(f"Path escapes the selected folder: {name}")
                if target.stat().st_size > limit:
                    raise ScanError(f"Metadata file is larger than {limit:,} bytes: {name}")
                return target.read_bytes()

            report = self._analyze(path, SourceType.DIRECTORY, names, read_bytes, total_size)
            report.errors.extend(errors)
            if errors:
                report.kind = PackageKind.INVALID
                report.recommended_action = "Do not install this folder. Review the reported safety errors."
            return report
        except (OSError, ScanError) as exc:
            return self._invalid(path, SourceType.DIRECTORY, str(exc))

    def _analyze(
        self,
        path: Path,
        source_type: SourceType,
        names: list[str],
        read_bytes: ReadBytes,
        total_size: int,
    ) -> ScanReport:
        normalized = [self._normalize_name(name) for name in names]
        lowercase = {name.lower(): name for name in normalized}
        dlls = sorted(name for name in normalized if Path(name).suffix.lower() == ".dll")
        assets = sorted(name for name in normalized if Path(name).suffix.lower() == ".cok")
        projects = sorted(
            name
            for name in normalized
            if Path(name).suffix.lower() in {".csproj", ".sln"}
        )
        source_file_count = sum(
            1 for name in normalized if Path(name).suffix.lower() in self.SOURCE_EXTENSIONS
        )
        common_root = self._common_root(normalized) if source_type == SourceType.ZIP else None

        metadata = ModMetadata()
        warnings: list[str] = []
        self._read_publish_metadata(lowercase, read_bytes, metadata, warnings)
        self._read_project_metadata(lowercase, read_bytes, metadata, warnings)
        if not metadata.display_name and dlls:
            metadata.display_name = self._infer_mod_name(normalized, dlls)

        strong_source_signals = bool(projects) and source_file_count >= 4

        if dlls and strong_source_signals:
            kind = PackageKind.MIXED_SOURCE_PACKAGE
            action = (
                "Source code and compiled DLLs are mixed together. Use an official release package "
                "instead of installing this archive automatically."
            )
            warnings.append("Compiled files are mixed with a development repository.")
        elif dlls:
            kind = PackageKind.READY_CODE_MOD
            action = "Ready for a safe preview and installation into the game's Mods folder."
        elif assets and not strong_source_signals:
            kind = PackageKind.ASSET_PACKAGE
            action = "Ready for a safe preview and installation into ImportedData."
        elif strong_source_signals:
            kind = PackageKind.SOURCE_REPOSITORY
            if metadata.paradox_mod_id:
                action = (
                    "This is source code, not an installable mod. Use the detected Paradox Mods ID "
                    "to obtain the official compiled version."
                )
            else:
                action = "This is source code. Find an official compiled release before installing."
        else:
            kind = PackageKind.UNKNOWN
            action = "No installable CS2 code mod or .cok asset was detected."

        return ScanReport(
            source_path=path,
            source_type=source_type,
            kind=kind,
            metadata=metadata,
            common_root=common_root,
            file_count=len(normalized),
            uncompressed_size=total_size,
            dll_files=dlls,
            asset_files=assets,
            project_files=projects,
            warnings=warnings,
            recommended_action=action,
        )

    def _validate_zip(self, infos: Iterable[zipfile.ZipInfo]) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        entries = list(infos)

        if len(entries) > self.MAX_ENTRIES:
            errors.append(f"Archive contains more than {self.MAX_ENTRIES:,} entries.")

        total_size = sum(item.file_size for item in entries)
        if total_size > self.MAX_UNCOMPRESSED_SIZE:
            errors.append("Archive expands beyond the 2 GiB MVP safety limit.")

        for item in entries:
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            mode = item.external_attr >> 16
            is_link = stat.S_ISLNK(mode)

            if not name or "\x00" in name:
                errors.append("Archive contains an empty or invalid filename.")
            elif name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
                errors.append(f"Absolute archive path is blocked: {name}")
            elif ".." in parts:
                errors.append(f"Archive path traversal is blocked: {name}")
            elif is_link:
                errors.append(f"Archive symbolic link is blocked: {name}")

            if item.flag_bits & 0x1:
                errors.append(f"Encrypted archive entry is unsupported: {name}")

            if item.compress_size == 0:
                ratio = float("inf") if item.file_size else 1
            else:
                ratio = item.file_size / item.compress_size
            if item.file_size > 10 * 1024 * 1024 and ratio > self.MAX_COMPRESSION_RATIO:
                errors.append(f"Suspicious compression ratio in: {name}")

        if len(errors) > 20:
            hidden = len(errors) - 20
            errors = errors[:20] + [f"...and {hidden} additional safety errors."]

        executable_files = [
            item.filename
            for item in entries
            if Path(item.filename).suffix.lower() in {".exe", ".bat", ".cmd", ".ps1", ".msi"}
        ]
        if executable_files:
            warnings.append(
                "Package contains standalone executables or scripts; they will never be run automatically."
            )

        seen_paths: set[str] = set()
        for item in entries:
            if item.is_dir():
                continue
            normalized = self._normalize_name(item.filename).casefold()
            if normalized in seen_paths:
                errors.append(f"Duplicate archive path is blocked: {item.filename}")
            seen_paths.add(normalized)

        return errors, warnings

    def _read_publish_metadata(
        self,
        lowercase: dict[str, str],
        read_bytes: ReadBytes,
        metadata: ModMetadata,
        warnings: list[str],
    ) -> None:
        candidates = [
            actual
            for lower, actual in lowercase.items()
            if lower.endswith("properties/publishconfiguration.xml")
        ]
        if not candidates:
            return

        try:
            root = ElementTree.fromstring(read_bytes(candidates[0], self.MAX_METADATA_SIZE))
            metadata.paradox_mod_id = self._xml_value(root, "ModId")
            metadata.display_name = self._xml_value(root, "DisplayName")
            metadata.version = self._xml_value(root, "ModVersion")
            metadata.game_version = self._xml_value(root, "GameVersion")
            metadata.tags = [
                value
                for node in root.findall(".//Tag")
                if (value := (node.attrib.get("Value") or "").strip())
            ]
        except (ElementTree.ParseError, OSError, ScanError) as exc:
            warnings.append(f"Could not parse PublishConfiguration.xml: {exc}")

    def _read_project_metadata(
        self,
        lowercase: dict[str, str],
        read_bytes: ReadBytes,
        metadata: ModMetadata,
        warnings: list[str],
    ) -> None:
        candidates = [actual for lower, actual in lowercase.items() if lower.endswith(".csproj")]
        if not candidates:
            return
        try:
            root = ElementTree.fromstring(read_bytes(candidates[0], self.MAX_METADATA_SIZE))

            def text(name: str) -> str | None:
                node = root.find(f".//{name}")
                return node.text.strip() if node is not None and node.text else None

            metadata.display_name = metadata.display_name or text("Title")
            metadata.version = metadata.version or text("Version")
            metadata.author = metadata.author or text("Authors")
        except (ElementTree.ParseError, OSError, ScanError) as exc:
            warnings.append(f"Could not parse project metadata: {exc}")

    @staticmethod
    def _xml_value(root: ElementTree.Element, name: str) -> str | None:
        node = root.find(f".//{name}")
        if node is None:
            return None
        value = node.attrib.get("Value") or node.text
        return value.strip() if value else None

    @staticmethod
    def _common_root(names: list[str]) -> str | None:
        first_parts = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
        return next(iter(first_parts)) if len(first_parts) == 1 else None

    @staticmethod
    def _infer_mod_name(names: list[str], dlls: list[str]) -> str | None:
        """Infer a primary assembly name from repeated output-file stems.

        Compiled CS2 packages often have no manifest. The main assembly name is
        usually repeated by its UI and Burst outputs (for example Traffic.dll,
        Traffic.mjs, Traffic.css and Traffic_win_x86_64.dll), while dependency
        DLLs tend to appear only once.
        """

        native_suffix = re.compile(r"_(?:win|linux|mac)_x86_64$", re.IGNORECASE)
        candidates: dict[str, tuple[str, int]] = {}
        basenames = [Path(name.replace("\\", "/")).name for name in names]

        for dll in dlls:
            stem = Path(dll).stem
            base = native_suffix.sub("", stem)
            if base.lower().endswith(".resources"):
                continue
            key = base.casefold()
            candidates.setdefault(key, (base, 0))

        for key, (display, _score) in list(candidates.items()):
            score = 0
            for filename in basenames:
                lower = filename.casefold()
                stem = Path(filename).stem.casefold()
                normalized_stem = native_suffix.sub("", stem)
                if normalized_stem == key:
                    score += 3
                if stem == key and Path(filename).suffix.lower() in {".mjs", ".js", ".css"}:
                    score += 20
                if lower.startswith((f"{key}_", f"{key}.", f"{key}-")):
                    score += 1
            candidates[key] = (display, score)

        if not candidates:
            return None
        return max(candidates.values(), key=lambda item: (item[1], -len(item[0])))[0]

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.replace("\\", "/").lstrip("./")

    @staticmethod
    def _invalid(path: Path, source_type: SourceType, message: str) -> ScanReport:
        return ScanReport(
            source_path=path,
            source_type=source_type,
            kind=PackageKind.INVALID,
            errors=[message],
            recommended_action="Select a supported and trustworthy mod package.",
        )
