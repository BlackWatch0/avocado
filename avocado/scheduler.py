from __future__ import annotations

import threading
from typing import Optional

from avocado.config_manager import ConfigManager
from avocado.sync_engine import SyncEngine


class SyncScheduler:
    def __init__(self, sync_engine: SyncEngine, config_manager: ConfigManager) -> None:
        self.sync_engine = sync_engine
        self.config_manager = config_manager
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._manual_trigger_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="avocado-sync-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._manual_trigger_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def trigger_manual(self) -> None:
        self._manual_trigger_event.set()

    def _loop(self) -> None:
        # Run one sync at startup so state is initialized quickly.
        self.sync_engine.run_once(trigger="startup")

        while not self._stop_event.is_set():
            config = self.config_manager.load()
            interval_seconds = max(30, int(config.sync.interval_seconds))
            manual = self._manual_trigger_event.wait(timeout=interval_seconds)
            self._manual_trigger_event.clear()
            if self._stop_event.is_set():
                break
            if manual:
                self.sync_engine.run_once(trigger="manual")
            else:
                self.sync_engine.run_once(trigger="scheduled")

