from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    game_path: str | None = None


def default_settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "SkylineDock" / "settings.json"


def load_settings(path: str | Path | None = None) -> AppSettings:
    target = Path(path) if path is not None else default_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return AppSettings()

    game_path = data.get("game_path") if isinstance(data, dict) else None
    return AppSettings(game_path=game_path if isinstance(game_path, str) else None)


def save_settings(settings: AppSettings, path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"schema_version": 1, **asdict(settings)}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target
