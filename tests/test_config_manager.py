import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from avocado.config_manager import ConfigManager
from avocado.core.models import AppConfig


class ConfigManagerTests(unittest.TestCase):
    def test_save_fallback_when_replace_ebusy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            manager = ConfigManager(str(config_path))
            config = AppConfig.from_dict(
                {
                    "caldav": {"base_url": "https://dav.example.com", "username": "u", "password": "p"},
                    "ai": {"base_url": "https://api.example.com/v1", "api_key": "k", "model": "gpt-4o-mini"},
                }
            )

            original_replace = Path.replace

            def replace_side_effect(self: Path, target: Path) -> Path:
                if str(self).endswith(".tmp"):
                    raise OSError(errno.EBUSY, "Device or resource busy")
                return original_replace(self, target)

            with mock.patch("pathlib.Path.replace", new=replace_side_effect):
                manager.save(config)

            self.assertTrue(config_path.exists())
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(data["caldav"]["base_url"], "https://dav.example.com")
            self.assertEqual(data["ai"]["api_key"], "k")

    def test_system_prompt_is_persisted_in_separate_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            prompt_path = Path(temp_dir) / "data" / "ai_system_prompt.txt"
            manager = ConfigManager(str(config_path), prompt_path=str(prompt_path))

            manager.update({"ai": {"system_prompt": "Prompt from test"}})

            self.assertTrue(prompt_path.exists())
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "Prompt from test")
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("system_prompt", data.get("ai", {}))
            loaded = manager.load()
            self.assertEqual(loaded.ai.system_prompt, "Prompt from test")

    def test_load_migrates_system_prompt_from_config_to_prompt_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            prompt_path = Path(temp_dir) / "data" / "ai_system_prompt.txt"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "caldav": {"base_url": "https://dav.example.com", "username": "u", "password": "p"},
                        "ai": {
                            "base_url": "https://api.example.com/v1",
                            "api_key": "k",
                            "model": "gpt-4o-mini",
                            "system_prompt": "Legacy prompt in config",
                        },
                    },
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            manager = ConfigManager(str(config_path), prompt_path=str(prompt_path))
            loaded = manager.load()
            self.assertEqual(loaded.ai.system_prompt, "Legacy prompt in config")
            self.assertTrue(prompt_path.exists())
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "Legacy prompt in config")


if __name__ == "__main__":
    unittest.main()

