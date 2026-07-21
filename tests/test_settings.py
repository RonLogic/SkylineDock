from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skylinedock.settings import AppSettings, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "settings.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_round_trips_manual_game_path(self) -> None:
        save_settings(AppSettings(game_path="D:/Steam/Cities Skylines II"), self.path)

        loaded = load_settings(self.path)

        self.assertEqual("D:/Steam/Cities Skylines II", loaded.game_path)

    def test_ignores_malformed_settings(self) -> None:
        self.path.write_text("not json", encoding="utf-8")

        self.assertIsNone(load_settings(self.path).game_path)
