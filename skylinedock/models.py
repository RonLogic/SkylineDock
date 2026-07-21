from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PackageKind(str, Enum):
    READY_CODE_MOD = "ready_code_mod"
    ASSET_PACKAGE = "asset_package"
    SOURCE_REPOSITORY = "source_repository"
    MIXED_SOURCE_PACKAGE = "mixed_source_package"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class SourceType(str, Enum):
    ZIP = "zip"
    DIRECTORY = "directory"
    DIRECT_FILE = "direct_file"
    UNSUPPORTED_ARCHIVE = "unsupported_archive"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ModMetadata:
    display_name: str | None = None
    version: str | None = None
    game_version: str | None = None
    author: str | None = None
    paradox_mod_id: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def paradox_url(self) -> str | None:
        if not self.paradox_mod_id:
            return None
        return f"https://mods.paradoxplaza.com/mods/{self.paradox_mod_id}/Windows"


@dataclass(slots=True)
class ScanReport:
    source_path: Path
    source_type: SourceType
    kind: PackageKind
    metadata: ModMetadata = field(default_factory=ModMetadata)
    common_root: str | None = None
    file_count: int = 0
    uncompressed_size: int = 0
    dll_files: list[str] = field(default_factory=list)
    asset_files: list[str] = field(default_factory=list)
    project_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    recommended_action: str = ""

    @property
    def can_install(self) -> bool:
        return self.kind in {
            PackageKind.READY_CODE_MOD,
            PackageKind.ASSET_PACKAGE,
        } and not self.errors

    @property
    def display_name(self) -> str:
        if self.metadata.display_name:
            return self.metadata.display_name
        return self.source_path.stem.removesuffix("-main").removesuffix("-master")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        data["source_type"] = self.source_type.value
        data["kind"] = self.kind.value
        data["can_install"] = self.can_install
        data["paradox_url"] = self.metadata.paradox_url
        return data
