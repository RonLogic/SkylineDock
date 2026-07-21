from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skylinedock.steam import detect_cs2_steam_installation


class SteamDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_detects_game_in_secondary_library(self) -> None:
        steam = self.root / "Steam"
        secondary = self.root / "Games"
        (steam / "steamapps").mkdir(parents=True)
        (secondary / "steamapps" / "common" / "Cities Skylines II").mkdir(parents=True)
        (steam / "steamapps" / "libraryfolders.vdf").write_text(
            f'"libraryfolders"\n{{\n  "1" {{ "path" "{secondary}" }}\n}}',
            encoding="utf-8",
        )
        (secondary / "steamapps" / "appmanifest_949230.acf").write_text(
            '"AppState" { "appid" "949230" "installdir" "Cities Skylines II" }',
            encoding="utf-8",
        )

        result = detect_cs2_steam_installation(steam)

        self.assertIsNotNone(result)
        self.assertEqual(
            (secondary / "steamapps" / "common" / "Cities Skylines II").resolve(),
            result.game_path,
        )

    def test_returns_none_without_manifest(self) -> None:
        steam = self.root / "Steam"
        (steam / "steamapps").mkdir(parents=True)

        self.assertIsNone(detect_cs2_steam_installation(steam))


if __name__ == "__main__":
    unittest.main()
