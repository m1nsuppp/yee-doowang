from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workout_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    performed_at TEXT NOT NULL,
    notes TEXT,
    client_request_id TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workout_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL,
    exercise_name TEXT NOT NULL,
    set_index INTEGER NOT NULL,
    weight_kg REAL NOT NULL,
    reps INTEGER NOT NULL,
    rpe REAL,
    is_warmup INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_workout_sets_session
    ON workout_sets(session_id);
CREATE INDEX IF NOT EXISTS idx_workout_sets_exercise
    ON workout_sets(exercise_id);
CREATE INDEX IF NOT EXISTS idx_workout_sessions_performed
    ON workout_sessions(performed_at);

CREATE TABLE IF NOT EXISTS body_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_at TEXT NOT NULL,
    body_weight_kg REAL,
    body_fat_percent REAL,
    sleep_hours REAL,
    fatigue INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_body_metrics_measured
    ON body_metrics(measured_at);
"""


def default_db_path() -> Path:
    configured = os.environ.get("YEE_DOOWANG_DB")
    if configured:
        return Path(configured).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "yee-doowang" / "coach.db"


class WorkoutStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_db_path()).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.export_dir = self.path.parent / "exports"
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)

    def find_session_by_request_id(self, request_id: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM workout_sessions WHERE client_request_id = ?",
                (request_id,),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    def insert_session(
        self,
        *,
        performed_at: str,
        notes: str | None,
        client_request_id: str | None,
        created_at: str,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO workout_sessions "
                "(performed_at, notes, client_request_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (performed_at, notes, client_request_id, created_at),
            )
            return int(cursor.lastrowid)

    def insert_sets(self, session_id: int, sets: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO workout_sets "
                "(session_id, exercise_id, exercise_name, set_index, weight_kg, "
                "reps, rpe, is_warmup) "
                "VALUES (:session_id, :exercise_id, :exercise_name, :set_index, "
                ":weight_kg, :reps, :rpe, :is_warmup)",
                [{**item, "session_id": session_id} for item in sets],
            )

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workout_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_sets(
        self,
        *,
        session_id: int | None = None,
        exercise_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if session_id is not None:
            clauses.append("sets.session_id = ?")
            parameters.append(session_id)
        if exercise_id is not None:
            clauses.append("sets.exercise_id = ?")
            parameters.append(exercise_id)
        if start_date is not None:
            clauses.append("date(sessions.performed_at) >= ?")
            parameters.append(start_date)
        if end_date is not None:
            clauses.append("date(sessions.performed_at) <= ?")
            parameters.append(end_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sets.*, sessions.performed_at, sessions.notes, "
                "sessions.id AS session_id "
                "FROM workout_sets AS sets "
                "JOIN workout_sessions AS sessions ON sessions.id = sets.session_id "
                f"{where} "
                "ORDER BY sessions.performed_at, sets.session_id, sets.set_index",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_sessions(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workout_sessions "
                "ORDER BY performed_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_session(self) -> dict[str, Any] | None:
        sessions = self.recent_sessions(1)
        return sessions[0] if sessions else None

    def delete_session(self, session_id: int) -> dict[str, Any] | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM workout_sessions WHERE id = ?", (session_id,))
        return session

    def insert_body_metric(
        self,
        *,
        measured_at: str,
        created_at: str,
        body_weight_kg: float | None,
        body_fat_percent: float | None,
        sleep_hours: float | None,
        fatigue: int | None,
        notes: str | None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO body_metrics "
                "(measured_at, body_weight_kg, body_fat_percent, sleep_hours, "
                "fatigue, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    measured_at,
                    body_weight_kg,
                    body_fat_percent,
                    sleep_hours,
                    fatigue,
                    notes,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def get_body_metric(self, metric_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM body_metrics WHERE id = ?", (metric_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def body_metrics(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if start_date is not None:
            clauses.append("date(measured_at) >= ?")
            parameters.append(start_date)
        if end_date is not None:
            clauses.append("date(measured_at) <= ?")
            parameters.append(end_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM body_metrics {where} "
                "ORDER BY measured_at, id",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_body_metric(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM body_metrics ORDER BY measured_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def previous_body_metric(self, measured_at: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM body_metrics WHERE measured_at <= ? "
                "ORDER BY measured_at DESC, id DESC LIMIT 1",
                (measured_at,),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_body_metric(self, metric_id: int) -> dict[str, Any] | None:
        metric = self.get_body_metric(metric_id)
        if metric is None:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM body_metrics WHERE id = ?", (metric_id,))
        return metric

    def all_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workout_sessions ORDER BY performed_at, id"
            ).fetchall()
        return [dict(row) for row in rows]

    def all_body_metrics(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM body_metrics ORDER BY measured_at, id"
            ).fetchall()
        return [dict(row) for row in rows]
