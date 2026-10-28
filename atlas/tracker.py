import sqlite3
import json
import threading
from pathlib import Path
from typing import List, Optional

from .models import WorkOrder, Status, Priority

DB_PATH = Path("atlas_data/work_orders.db")


class WorkOrderTracker:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(exist_ok=True)
        self._db = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self._db)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS work_orders (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    assigned_to TEXT,
                    result TEXT,
                    struggles TEXT DEFAULT '[]',
                    parent_id TEXT,
                    tags TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
            """)
            conn.commit()
            conn.close()

    def save(self, wo: WorkOrder):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT OR REPLACE INTO work_orders
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                wo.id, wo.title, wo.description, wo.created_by,
                wo.status.value, wo.priority.value, wo.assigned_to,
                wo.result, json.dumps(wo.struggles), wo.parent_id,
                json.dumps(wo.tags), wo.created_at, wo.started_at, wo.completed_at
            ))
            conn.commit()
            conn.close()

    def get(self, id: str) -> Optional[WorkOrder]:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT * FROM work_orders WHERE id=?", (id,)).fetchone()
            conn.close()
        return self._row(row) if row else None

    def by_status(self, status: Status) -> List[WorkOrder]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM work_orders WHERE status=? ORDER BY priority ASC, created_at ASC",
                (status.value,)
            ).fetchall()
            conn.close()
        return [self._row(r) for r in rows]

    def children(self, parent_id: str) -> List[WorkOrder]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM work_orders WHERE parent_id=? ORDER BY created_at ASC",
                (parent_id,)
            ).fetchall()
            conn.close()
        return [self._row(r) for r in rows]

    def all(self) -> List[WorkOrder]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM work_orders ORDER BY created_at DESC"
            ).fetchall()
            conn.close()
        return [self._row(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            conn = self._conn()
            cur = conn.execute("SELECT status, COUNT(*) FROM work_orders GROUP BY status")
            result = {row[0]: row[1] for row in cur.fetchall()}
            conn.close()
        return result

    def _row(self, r) -> WorkOrder:
        return WorkOrder(
            id=r[0], title=r[1], description=r[2], created_by=r[3],
            status=Status(r[4]), priority=Priority(r[5]),
            assigned_to=r[6], result=r[7],
            struggles=json.loads(r[8]), parent_id=r[9],
            tags=json.loads(r[10]), created_at=r[11],
            started_at=r[12], completed_at=r[13]
        )
