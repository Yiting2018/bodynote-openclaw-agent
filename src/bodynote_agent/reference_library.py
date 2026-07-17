from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from bodynote_agent.database import connect, new_id


class ReferenceLibraryService:
    """Stores user-approved, structured guide notes without copying source documents."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def add(self, data: dict[str, Any]) -> dict[str, Any]:
        guide = _normalize(data)
        guide_id = new_id("guide")
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO reference_guides (
                        id, profile_id, title, source_type, source_uri, version,
                        scope_json, rules_json, citations_json, enabled
                    ) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guide_id,
                        guide["title"],
                        guide["source_type"],
                        guide["source_uri"],
                        guide["version"],
                        _json(guide["scope"]),
                        _json(guide["rules"]),
                        _json(guide["citations"]),
                        int(guide["enabled"]),
                    ),
                )
        return {"ok": True, "guide": self.get(guide_id)}

    def list(self, *, enabled_only: bool = False) -> dict[str, Any]:
        clause = " AND enabled = 1" if enabled_only else ""
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM reference_guides
                WHERE profile_id = 'owner'{clause}
                ORDER BY enabled DESC, updated_at DESC
                """
            ).fetchall()
        guides = [_serialize(row) for row in rows]
        return {"ok": True, "count": len(guides), "guides": guides}

    def get(self, guide_id: str) -> dict[str, Any] | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT * FROM reference_guides WHERE profile_id = 'owner' AND id = ?",
                (guide_id,),
            ).fetchone()
        return _serialize(row) if row else None

    def set_enabled(self, guide_id: str, enabled: bool) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE reference_guides
                    SET enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND id = ?
                    """,
                    (int(enabled), guide_id),
                )
        if cursor.rowcount == 0:
            raise ValueError("没有找到这份参考指南。")
        return {"ok": True, "guide": self.get(guide_id)}


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title", "source_type", "source_uri", "version", "scope", "rules",
        "citations", "enabled",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"不支持的参考库字段：{', '.join(unknown)}。")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("参考指南需要 title。")
    source_type = str(data.get("source_type") or "user_upload").strip()
    if source_type not in {"user_upload", "user_note", "public_guideline"}:
        raise ValueError("source_type 必须是 user_upload、user_note 或 public_guideline。")
    normalized: dict[str, Any] = {
        "title": title,
        "source_type": source_type,
        "source_uri": str(data.get("source_uri") or "").strip() or None,
        "version": str(data.get("version") or "").strip() or None,
        "enabled": bool(data.get("enabled", True)),
    }
    for field in ("scope", "rules", "citations"):
        value = data.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"{field} 必须是数组。")
        normalized[field] = value
    return normalized


def _serialize(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "source_type": row["source_type"],
        "source_uri": row["source_uri"],
        "version": row["version"],
        "scope": json.loads(row["scope_json"] or "[]"),
        "rules": json.loads(row["rules_json"] or "[]"),
        "citations": json.loads(row["citations_json"] or "[]"),
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
