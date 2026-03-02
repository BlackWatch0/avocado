from __future__ import annotations

import copy
import errno
import os
import threading
from pathlib import Path
from typing import Any

import yaml

from avocado.core.models import AppConfig, default_app_config
from avocado.core.models.constants import DEFAULT_AI_SYSTEM_PROMPT


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(
        self,
        config_path: str | os.PathLike[str],
        prompt_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        resolved_prompt_path = (
            Path(prompt_path)
            if prompt_path is not None
            else Path(
                os.getenv(
                    "AVOCADO_PROMPT_PATH",
                    str(self.config_path.parent / "ai_system_prompt.txt"),
                )
            )
        )
        self.prompt_path = resolved_prompt_path
        self._lock = threading.RLock()
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if self.config_path.exists():
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.save(default_app_config())

    def _read_prompt(self) -> str:
        if not self.prompt_path.exists():
            return ""
        try:
            return self.prompt_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _legacy_prompt_path(self) -> Path:
        return self.config_path.parent / "data" / "ai_system_prompt.txt"

    def _write_prompt(self, prompt: str) -> None:
        self.prompt_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompt_path.write_text(str(prompt or "").strip(), encoding="utf-8")

    def _write_config_dict(self, config_dict: dict[str, Any]) -> None:
        tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                config_dict,
                handle,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
        try:
            tmp_path.replace(self.config_path)
        except OSError as exc:
            # Some bind-mounted single files in containers cannot be atomically replaced.
            if exc.errno != errno.EBUSY:
                raise
            with self.config_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    config_dict,
                    handle,
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                )
            if tmp_path.exists():
                tmp_path.unlink()

    def load(self) -> AppConfig:
        with self._lock:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            ai_dict = data.get("ai") if isinstance(data.get("ai"), dict) else {}
            prompt_in_config = str((ai_dict or {}).get("system_prompt", "") or "").strip()
            prompt_in_file = self._read_prompt()
            if not prompt_in_file:
                legacy_path = self._legacy_prompt_path()
                if legacy_path != self.prompt_path and legacy_path.exists():
                    try:
                        prompt_in_file = legacy_path.read_text(encoding="utf-8").strip()
                    except Exception:
                        prompt_in_file = ""
                    if prompt_in_file:
                        self._write_prompt(prompt_in_file)
            resolved_prompt = prompt_in_file or prompt_in_config or DEFAULT_AI_SYSTEM_PROMPT
            data.setdefault("ai", {})["system_prompt"] = resolved_prompt
            if prompt_in_file == "" and prompt_in_config:
                self._write_prompt(prompt_in_config)
                if isinstance(ai_dict, dict) and "system_prompt" in ai_dict:
                    ai_dict.pop("system_prompt", None)
                    self._write_config_dict(data)
                    data.setdefault("ai", {})["system_prompt"] = resolved_prompt
            return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            config_dict = config.to_dict()
            ai_dict = config_dict.get("ai", {}) if isinstance(config_dict.get("ai"), dict) else {}
            self._write_prompt(str(ai_dict.get("system_prompt", DEFAULT_AI_SYSTEM_PROMPT) or DEFAULT_AI_SYSTEM_PROMPT))
            if isinstance(config_dict.get("ai"), dict) and "system_prompt" in config_dict["ai"]:
                config_dict["ai"].pop("system_prompt", None)
            self._write_config_dict(config_dict)

    def update(self, payload: dict[str, Any]) -> AppConfig:
        with self._lock:
            current = self.load().to_dict()
            merged = _deep_merge(current, payload)
            config = AppConfig.from_dict(merged)
            self.save(config)
            return config

    def masked(self) -> dict[str, Any]:
        config = self.load().to_dict()
        if config.get("caldav", {}).get("password"):
            config["caldav"]["password"] = "***"
        if config.get("ai", {}).get("api_key"):
            config["ai"]["api_key"] = "***"
        return config
