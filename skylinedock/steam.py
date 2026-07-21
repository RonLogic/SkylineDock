from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


CS2_STEAM_APP_ID = "949230"


@dataclass(slots=True, frozen=True)
class SteamGameInstallation:
    steam_root: Path
    library_root: Path
    game_path: Path
    manifest_path: Path


def detect_cs2_steam_installation(steam_root: str | Path | None = None) -> SteamGameInstallation | None:
    root = Path(steam_root).expanduser() if steam_root else _detect_steam_root()
    if root is None:
        return None
    root = root.resolve()

    for library in _steam_libraries(root):
        manifest = library / "steamapps" / f"appmanifest_{CS2_STEAM_APP_ID}.acf"
        if not manifest.is_file():
            continue
        install_dir = _read_vdf_value(manifest, "installdir") or "Cities Skylines II"
        game_path = library / "steamapps" / "common" / install_dir
        if game_path.is_dir():
            return SteamGameInstallation(root, library, game_path.resolve(), manifest.resolve())
    return None


def _detect_steam_root() -> Path | None:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                value, _kind = winreg.QueryValueEx(key, "SteamPath")
                path = Path(value)
                if path.is_dir():
                    return path
        except (ImportError, OSError):
            pass

    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam",
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    ]
    return next((path for path in candidates if path.is_dir()), None)


def _steam_libraries(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    config = steam_root / "steamapps" / "libraryfolders.vdf"
    if config.is_file():
        try:
            text = config.read_text(encoding="utf-8", errors="replace")
            for value in re.findall(r'"path"\s+"([^"]+)"', text, flags=re.IGNORECASE):
                path = Path(value.replace("\\\\", "\\"))
                if path not in libraries:
                    libraries.append(path)
        except OSError:
            pass
    return libraries


def _read_vdf_value(path: Path, key: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]+)"', text, flags=re.IGNORECASE)
    return match.group(1) if match else None
