"""Session-scoped conversation storage. Clients own labels and retention policy."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from ..contracts import ConversationSnapshot
from ..errors import InvalidRequestError


class ConversationSnapshotStore:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS snapshots "
            "(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        return connection

    def put(self, snapshot: ConversationSnapshot):
        reference = {"snapshot_id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat()}
        payload = snapshot.model_dump_json()
        with closing(self._connect()) as connection, connection:
            connection.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?)",
                               (reference["snapshot_id"], snapshot.session_id, reference["created_at"], payload))
        return reference

    def get(self, session_id: str, snapshot_id: str):
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload FROM snapshots WHERE id = ? AND session_id = ?",
                                     (snapshot_id, session_id)).fetchone()
        if row is None:
            raise InvalidRequestError("Snapshot not found in this session")
        return ConversationSnapshot.model_validate_json(row[0])

    def delete(self, session_id: str, snapshot_ids: list[str]):
        with closing(self._connect()) as connection, connection:
            connection.executemany("DELETE FROM snapshots WHERE id = ? AND session_id = ?",
                                   [(snapshot_id, session_id) for snapshot_id in snapshot_ids])
