from __future__ import annotations

import copy
import errno
import os
import threading
from pathlib import Path
from typing import Any

import yaml

from avocado.models import AppConfig, default_app_config


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(self, config_path: str | os.PathLike[str]) -> None:
        self.config_path = Path(config_path)
        self._lock = threading.RLock()
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if self.config_path.exists():
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.save(default_app_config())

    def load(self) -> AppConfig:
        with self._lock:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            config_dict = config.to_dict()
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
