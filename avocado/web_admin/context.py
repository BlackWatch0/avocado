from __future__ import annotations

from avocado.config_manager import ConfigManager
from avocado.persistence.state_store import StateStore
from avocado.scheduler import SyncScheduler
from avocado.sync import SyncEngine


class AppContext:
    def __init__(self, config_path: str, state_path: str) -> None:
        self.config_manager = ConfigManager(config_path)
        self.state_store = StateStore(state_path)
        self.sync_engine = SyncEngine(self.config_manager, self.state_store)
        self.scheduler = SyncScheduler(self.sync_engine, self.config_manager)
