from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bodynote_agent.database import connect, new_id


@dataclass(frozen=True)
class EventInput:
    event_type: str
    occurred_at: str
    payload: dict[str, Any]
    source: str = "openclaw"
    source_context: dict[str, Any] = field(default_factory=dict)
    raw_text: str | None = None
    confidence: float | None = None
    idempotency_key: str | None = None


class EventRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def create(self, event: EventInput, *, request_id: str | None = None) -> tuple[dict[str, Any], bool]:
        with closing(connect(self.database_path)) as connection:
            with connection:
                if event.idempotency_key:
                    existing = self._find_by_idempotency(connection, event.idempotency_key)
                    if existing:
                        self._audit(
                            connection,
                            request_id=request_id,
                            action="event_duplicate",
                            target_id=existing["id"],
                            success=True,
                            details={"idempotency_key": event.idempotency_key},
                        )
                        return self._serialize(existing), True

                event_id = new_id("evt")
                try:
                    connection.execute(
                        """
                        INSERT INTO health_events (
                            id, profile_id, event_type, occurred_at, payload_json,
                            source, source_context_json, raw_text, confidence,
                            idempotency_key
                        ) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            event.event_type,
                            event.occurred_at,
                            _json(event.payload),
                            event.source,
                            _json(event.source_context),
                            event.raw_text,
                            event.confidence,
                            event.idempotency_key,
                        ),
                    )
                except sqlite3.IntegrityError:
                    if not event.idempotency_key:
                        raise
                    existing = self._find_by_idempotency(connection, event.idempotency_key)
                    if existing is None:
                        raise
                    return self._serialize(existing), True

                self._audit(
                    connection,
                    request_id=request_id,
                    action="event_create",
                    target_id=event_id,
                    success=True,
                    details={"event_type": event.event_type, "source": event.source},
                )
                row = self._get(connection, event_id, include_deleted=True)
                if row is None:
                    raise RuntimeError("Created event could not be read back.")
                return self._serialize(row), False

    def list(
        self,
        *,
        date: str | None = None,
        timezone_name: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["profile_id = 'owner'"]
        parameters: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if date:
            if timezone_name:
                start, end = _local_day_bounds(date, timezone_name)
                clauses.append("datetime(occurred_at) >= datetime(?)")
                clauses.append("datetime(occurred_at) < datetime(?)")
                parameters.extend((start, end))
            else:
                clauses.append("substr(occurred_at, 1, 10) = ?")
                parameters.append(date)
        if event_type:
            clauses.append("event_type = ?")
            parameters.append(event_type)
        parameters.append(max(1, min(limit, 500)))
        sql = f"""
            SELECT * FROM health_events
            WHERE {' AND '.join(clauses)}
            ORDER BY occurred_at DESC, created_at DESC
            LIMIT ?
        """
        with closing(connect(self.database_path)) as connection:
            return [self._serialize(row) for row in connection.execute(sql, parameters)]

    def get(self, event_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        with closing(connect(self.database_path)) as connection:
            row = self._get(connection, event_id, include_deleted=include_deleted)
            return self._serialize(row) if row else None

    def list_period(
        self,
        *,
        start_date: str,
        end_date: str,
        timezone_name: str,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        start, _ = _local_day_bounds(start_date, timezone_name)
        _, end = _local_day_bounds(end_date, timezone_name)
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT * FROM health_events
                WHERE profile_id = 'owner' AND deleted_at IS NULL
                  AND datetime(occurred_at) >= datetime(?)
                  AND datetime(occurred_at) < datetime(?)
                ORDER BY occurred_at ASC, created_at ASC
                LIMIT ?
                """,
                (start, end, max(1, min(limit, 20000))),
            )
            return [self._serialize(row) for row in rows]

    def update(
        self,
        event_id: str,
        *,
        event_type: str,
        occurred_at: str,
        payload: dict[str, Any],
        raw_text: str | None,
        confidence: float | None,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE health_events
                    SET event_type = ?, occurred_at = ?, payload_json = ?,
                        raw_text = ?, confidence = ?, revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND id = ? AND deleted_at IS NULL
                    """,
                    (
                        event_type,
                        occurred_at,
                        _json(payload),
                        raw_text,
                        confidence,
                        event_id,
                    ),
                )
                if cursor.rowcount == 0:
                    return None
                self._audit(
                    connection,
                    request_id=request_id,
                    action="event_update",
                    target_id=event_id,
                    success=True,
                    details={"event_type": event_type},
                )
                row = self._get(connection, event_id, include_deleted=True)
                return self._serialize(row) if row else None

    def delete(self, event_id: str, *, request_id: str | None = None) -> bool:
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE health_events
                    SET deleted_at = CURRENT_TIMESTAMP, revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND id = ? AND deleted_at IS NULL
                    """,
                    (event_id,),
                )
                if cursor.rowcount == 0:
                    return False
                self._audit(
                    connection,
                    request_id=request_id,
                    action="event_delete",
                    target_id=event_id,
                    success=True,
                    details={},
                )
                return True

    def audit_count(self, *, target_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM audit_log WHERE profile_id = 'owner'"
        parameters: tuple[Any, ...] = ()
        if target_id:
            sql += " AND target_id = ?"
            parameters = (target_id,)
        with closing(connect(self.database_path)) as connection:
            return int(connection.execute(sql, parameters).fetchone()[0])

    def _get(
        self,
        connection: sqlite3.Connection,
        event_id: str,
        *,
        include_deleted: bool,
    ) -> sqlite3.Row | None:
        deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
        return connection.execute(
            f"""
            SELECT * FROM health_events
            WHERE profile_id = 'owner' AND id = ? {deleted_clause}
            """,
            (event_id,),
        ).fetchone()

    def _find_by_idempotency(
        self,
        connection: sqlite3.Connection,
        key: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM health_events
            WHERE profile_id = 'owner' AND idempotency_key = ?
            """,
            (key,),
        ).fetchone()

    def _audit(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: str | None,
        action: str,
        target_id: str,
        success: bool,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_log (
                id, profile_id, request_id, action, target_type, target_id,
                data_types_json, details_json, success
            ) VALUES (?, 'owner', ?, ?, 'health_event', ?, '["health_events"]', ?, ?)
            """,
            (
                new_id("audit"),
                request_id,
                action,
                target_id,
                _json(details),
                1 if success else 0,
            ),
        )

    def _serialize(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"],
            "payload": json.loads(row["payload_json"]),
            "source": row["source"],
            "source_context": json.loads(row["source_context_json"] or "{}"),
            "raw_text": row["raw_text"],
            "confidence": row["confidence"],
            "idempotency_key": row["idempotency_key"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _local_day_bounds(value: str, timezone_name: str) -> tuple[str, str]:
    local_date = date_type.fromisoformat(value)
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(local_date, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).isoformat(),
        end.astimezone(timezone.utc).isoformat(),
    )
