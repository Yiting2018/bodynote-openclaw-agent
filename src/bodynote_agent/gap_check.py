from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import Any

from bodynote_agent.events import EventRepository
from bodynote_agent.cycle import CycleForecastService
from bodynote_agent.preferences import (
    DAILY_FIELD_EVENT_TYPES,
    DAILY_FIELD_EXAMPLES,
    DAILY_FIELD_LABELS,
    OnboardingService,
    local_date,
)


class GapCheckService:
    def __init__(self, database_path: Path) -> None:
        self.events = EventRepository(database_path)
        self.onboarding = OnboardingService(database_path)
        self.cycle = CycleForecastService(database_path)

    def check(self, date: str | None = None) -> dict[str, Any]:
        settings = self.onboarding.status()
        if not settings["onboarding_completed"]:
            return {
                "ok": False,
                "complete": False,
                "error": "首次设置尚未完成，请先设置主要健康目标和报告时间。",
                "missing_setup_fields": settings["missing_setup_fields"],
            }

        target_date = date or local_date(settings["profile"]["timezone"])
        _validate_date(target_date)
        events = self.events.list(
            date=target_date,
            timezone_name=settings["profile"]["timezone"],
            limit=500,
        )
        recorded_types = {event["event_type"] for event in events}
        required = settings["schedule"]["required_daily_fields"]
        completed = [
            field
            for field in required
            if recorded_types.intersection(DAILY_FIELD_EVENT_TYPES[field])
        ]
        missing = [field for field in required if field not in completed]
        not_applicable = settings["schedule"]["not_applicable_daily_fields"]
        not_planned = [
            field
            for field in DAILY_FIELD_EVENT_TYPES
            if field not in required and field not in not_applicable
        ]
        coverage = len(completed) / len(required) if required else 1.0
        prompts = [
            {
                "field": field,
                "label": DAILY_FIELD_LABELS[field],
                "example": DAILY_FIELD_EXAMPLES[field],
            }
            for field in missing[:3]
        ]
        cycle = self.cycle.forecast(
            target_date,
            timezone_name=settings["profile"]["timezone"],
            profile_details=settings["profile"]["details"],
        )
        prompt = _build_prompt(prompts)
        if cycle.get("reminder_due"):
            prompt += f" {cycle['message']}"
        return {
            "ok": True,
            "date": target_date,
            "complete": not missing,
            "event_count": len(events),
            "required": required,
            "completed": completed,
            "missing": missing,
            "not_planned": not_planned,
            "not_applicable": not_applicable,
            "not_required": [*not_planned, *not_applicable],
            "prompts": prompts,
            "prompt": prompt,
            "coverage": round(coverage, 3),
            "confidence_hint": _confidence_hint(coverage),
            "report_can_continue": True,
            "cycle_forecast": cycle,
        }


def _validate_date(value: str) -> None:
    try:
        date_type.fromisoformat(value)
    except ValueError:
        raise ValueError("date 必须是 YYYY-MM-DD。") from None


def _build_prompt(prompts: list[dict[str, str]]) -> str:
    if not prompts:
        return "今天需要的记录已经齐了，可以按当前数据生成报告。"
    labels = "、".join(item["label"] for item in prompts)
    examples = "；".join(item["example"] for item in prompts)
    return (
        f"今天的报告还差{labels}。补一句就可以：{examples}。"
        "如果今天不方便补，也可以直接跳过，报告会按现有记录生成并标注置信度。"
    )


def _confidence_hint(coverage: float) -> str:
    if coverage >= 1:
        return "high"
    if coverage >= 0.5:
        return "medium"
    return "low"
