from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bodynote_agent.events import EventInput, EventRepository
from bodynote_agent.food_library import FoodLibraryService
from bodynote_agent.parsing import ParseError, parse_checkin_text
from bodynote_agent.validation import validate_event


class CheckinService:
    def __init__(self, database_path: Path) -> None:
        self.repository = EventRepository(database_path)
        self.food_library = FoodLibraryService(database_path)

    def record_text(
        self,
        text: str,
        *,
        source: str = "openclaw",
        source_context: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = parse_checkin_text(text, now=now)
        except ParseError as error:
            return {"ok": False, "recorded": False, "error": str(error)}

        payload = self._enrich_meal(parsed.event_type, parsed.payload, text)
        validation = validate_event(parsed.event_type, payload)
        if not validation.ok:
            return {
                "ok": False,
                "recorded": False,
                "event_type": parsed.event_type,
                "errors": list(validation.errors),
                "follow_up_question": parsed.follow_up_question or validation.follow_up_question,
            }

        request_id = idempotency_key or f"req_{uuid4().hex}"
        canonical_key = f"{source}:{idempotency_key}" if idempotency_key else None
        event, duplicate = self.repository.create(
            EventInput(
                event_type=parsed.event_type,
                occurred_at=parsed.occurred_at,
                payload=validation.payload,
                source=source,
                source_context=source_context or {},
                raw_text=text,
                confidence=parsed.confidence,
                idempotency_key=canonical_key,
            ),
            request_id=request_id,
        )
        warnings = list(
            dict.fromkeys([*parsed.warnings, *validation.warnings])
        )
        return self._record_result(
            event,
            duplicate=duplicate,
            follow_up=parsed.follow_up_question or validation.follow_up_question,
            warnings=warnings,
        )

    def record_structured(self, data: dict[str, Any]) -> dict[str, Any]:
        event_type = str(data.get("event_type") or "")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "recorded": False, "errors": ["payload 必须是 JSON object。"]}
        occurred_at = str(data.get("occurred_at") or "")
        if not occurred_at:
            return {"ok": False, "recorded": False, "errors": ["occurred_at 不能为空。"]}
        occurred_error = _occurred_at_error(occurred_at)
        if occurred_error:
            return {"ok": False, "recorded": False, "errors": [occurred_error]}
        raw_text = str(data.get("raw_text") or "")
        payload = self._enrich_meal(event_type, payload, raw_text)
        validation = validate_event(event_type, payload)
        if not validation.ok:
            return {
                "ok": False,
                "recorded": False,
                "event_type": event_type,
                "errors": list(validation.errors),
                "follow_up_question": validation.follow_up_question,
            }

        source = str(data.get("source") or "openclaw")
        raw_key = str(data.get("idempotency_key") or "") or None
        canonical_key = f"{source}:{raw_key}" if raw_key else None
        confidence = data.get("confidence")
        if confidence is not None:
            confidence = max(0.0, min(float(confidence), 1.0))
        event, duplicate = self.repository.create(
            EventInput(
                event_type=event_type,
                occurred_at=occurred_at,
                payload=validation.payload,
                source=source,
                source_context=data.get("source_context") if isinstance(data.get("source_context"), dict) else {},
                raw_text=raw_text or None,
                confidence=confidence,
                idempotency_key=canonical_key,
            ),
            request_id=raw_key or f"req_{uuid4().hex}",
        )
        return self._record_result(
            event,
            duplicate=duplicate,
            follow_up=validation.follow_up_question,
            warnings=list(validation.warnings),
        )

    def list_events(
        self,
        *,
        date: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        events = self.repository.list(
            date=date,
            event_type=event_type,
            limit=limit,
            include_deleted=include_deleted,
        )
        return {"ok": True, "count": len(events), "events": events}

    def get_event(self, event_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
        event = self.repository.get(event_id, include_deleted=include_deleted)
        if event is None:
            return {"ok": False, "error": "记录不存在。", "event_id": event_id}
        return {"ok": True, "event": event}

    def update_event(self, event_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.repository.get(event_id)
        if current is None:
            return {"ok": False, "updated": False, "error": "记录不存在或已删除。"}

        event_type = str(patch.get("event_type") or current["event_type"])
        payload = dict(current["payload"])
        patch_payload = patch.get("payload")
        if patch_payload is not None:
            if not isinstance(patch_payload, dict):
                return {"ok": False, "updated": False, "errors": ["payload 必须是 JSON object。"]}
            payload.update(patch_payload)
        validation = validate_event(event_type, payload)
        if not validation.ok:
            return {"ok": False, "updated": False, "errors": list(validation.errors)}

        confidence = patch.get("confidence", current["confidence"])
        if confidence is not None:
            confidence = max(0.0, min(float(confidence), 1.0))
        occurred_at = str(patch.get("occurred_at") or current["occurred_at"])
        occurred_error = _occurred_at_error(occurred_at)
        if occurred_error:
            return {"ok": False, "updated": False, "errors": [occurred_error]}
        updated = self.repository.update(
            event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=validation.payload,
            raw_text=str(patch.get("raw_text") or current["raw_text"] or "") or None,
            confidence=confidence,
            request_id=str(patch.get("request_id") or f"req_{uuid4().hex}"),
        )
        if updated is None:
            return {"ok": False, "updated": False, "error": "记录更新失败。"}
        return {
            "ok": True,
            "updated": True,
            "event": updated,
            "warnings": list(validation.warnings),
            "follow_up_question": validation.follow_up_question,
        }

    def delete_event(self, event_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        deleted = self.repository.delete(
            event_id,
            request_id=request_id or f"req_{uuid4().hex}",
        )
        if not deleted:
            return {"ok": False, "deleted": False, "error": "记录不存在或已经删除。"}
        return {"ok": True, "deleted": True, "event_id": event_id}

    def _enrich_meal(
        self, event_type: str, payload: dict[str, Any], raw_text: str
    ) -> dict[str, Any]:
        if event_type != "meal" or payload.get("food_library") or not raw_text:
            return payload
        return self.food_library.enrich_meal(payload, raw_text)

    def _record_result(
        self,
        event: dict[str, Any],
        *,
        duplicate: bool,
        follow_up: str | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        safety = None
        if "safety_attention_required" in warnings or any(item.startswith("urgent_") for item in warnings):
            safety = {
                "level": "urgent",
                "message": "这条记录包含需要优先关注的信号。如症状严重、突然出现或持续加重，请及时联系当地急救或医疗机构。",
            }
        return {
            "ok": True,
            "recorded": True,
            "duplicate": duplicate,
            "summary": _event_summary(event),
            "event": event,
            "follow_up_question": follow_up,
            "warnings": warnings,
            "safety": safety,
        }


def _event_summary(event: dict[str, Any]) -> str:
    payload = event["payload"]
    event_type = event["event_type"]
    if event_type == "blood_pressure":
        return f"已记录血压 {payload['systolic']}/{payload['diastolic']}。"
    if event_type == "blood_glucose":
        return f"已记录血糖 {payload['glucose_mmol_l']} mmol/L。"
    if event_type == "body" and "weight_kg" in payload:
        return f"已记录体重 {payload['weight_kg']} kg。"
    if event_type == "sleep":
        detail = f" {payload['duration_hours']} 小时" if "duration_hours" in payload else ""
        return f"已记录睡眠{detail}。"
    if event_type == "exercise":
        detail = f" {payload['steps']} 步" if "steps" in payload else ""
        return f"已记录运动：{payload['activity']}{detail}。"
    if event_type == "meal":
        return f"已记录饮食：{'、'.join(str(item) for item in payload['foods'])}。"
    if event_type == "mood":
        return f"已记录感受：{payload.get('label') or payload['mood']}。"
    if event_type == "symptom":
        return f"已记录症状：{payload.get('label') or payload['symptom']}。"
    if event_type == "menstrual_cycle":
        return "已记录生理周期信息。"
    return f"已记录 {event_type}。"


def _occurred_at_error(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "occurred_at 必须是 ISO 8601 时间。"
    if parsed.tzinfo is None:
        return "occurred_at 必须包含时区偏移。"
    return None
