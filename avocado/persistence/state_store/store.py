from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from avocado.persistence.state_store.repo_audit import AuditRepoMixin
from avocado.persistence.state_store.repo_mappings import MappingsRepoMixin
from avocado.persistence.state_store.repo_meta import MetaRepoMixin
from avocado.persistence.state_store.repo_new_cleanup import NewCleanupRepoMixin
from avocado.persistence.state_store.repo_snapshots import SnapshotsRepoMixin
from avocado.persistence.state_store.repo_sync_runs import SyncRunsRepoMixin
from avocado.persistence.state_store.repo_tombstones import TombstonesRepoMixin
from avocado.persistence.state_store.schema import SchemaMixin


class StateStore(
    SchemaMixin,
    SyncRunsRepoMixin,
    AuditRepoMixin,
    SnapshotsRepoMixin,
    MetaRepoMixin,
    MappingsRepoMixin,
    TombstonesRepoMixin,
    NewCleanupRepoMixin,
):
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
