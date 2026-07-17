from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import median, pstdev
from typing import Any

from bodynote_agent.events import EventRepository


class CycleForecastService:
    def __init__(self, database_path: Path) -> None:
        self.events = EventRepository(database_path)

    def forecast(
        self,
        reference_day: str,
        *,
        timezone_name: str,
        profile_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        details = profile_details or {}
        if details.get("cycle_tracking_enabled") is not True:
            return {"enabled": False, "status": "disabled", "message": "生理周期追踪已关闭。"}
        reference = date.fromisoformat(reference_day)
        events = self.events.list_period(
            start_date=(reference - timedelta(days=400)).isoformat(),
            end_date=reference.isoformat(),
            timezone_name=timezone_name,
        )
        starts = sorted(
            {
                date.fromisoformat(event["occurred_at"][:10])
                for event in events
                if event["event_type"] == "menstrual_cycle"
                and _is_period_start(event["payload"])
            }
        )
        if len(starts) < 2:
            return {
                "enabled": True,
                "status": "learning",
                "recorded_starts": len(starts),
                "message": "至少记录两次经期开始日期后，才能建立个人周期预测。",
                "confidence": 0.0,
            }
        intervals = [(right - left).days for left, right in zip(starts, starts[1:])]
        plausible = [value for value in intervals[-6:] if 15 <= value <= 60]
        if not plausible:
            return {
                "enabled": True,
                "status": "irregular_data",
                "recorded_starts": len(starts),
                "message": "现有周期间隔不足以形成稳定预测，请继续记录。",
                "confidence": 0.2,
            }
        typical = int(round(median(plausible)))
        predicted = starts[-1] + timedelta(days=typical)
        variability = round(pstdev(plausible), 1) if len(plausible) > 1 else None
        reminder_days = int(details.get("cycle_reminder_days_before", 3))
        days_until = (predicted - reference).days
        confidence = min(0.9, 0.45 + 0.1 * len(plausible))
        if variability is not None:
            confidence *= max(0.45, 1 - variability / 14)
        status = "upcoming" if 0 <= days_until <= reminder_days else "forecast"
        if days_until < 0:
            status = "overdue_window"
        cycle_day = max(1, (reference - starts[-1]).days + 1)
        ovulation_day = max(8, typical - 14)
        if cycle_day <= 5:
            estimated_phase = "menstrual"
            phase_label = "经期"
        elif cycle_day <= ovulation_day:
            estimated_phase = "follicular"
            phase_label = "卵泡期"
        else:
            estimated_phase = "luteal"
            phase_label = "黄体期"
        return {
            "enabled": True,
            "status": status,
            "recorded_starts": len(starts),
            "interval_samples": len(plausible),
            "typical_cycle_days": typical,
            "variability_days": variability,
            "last_period_start": starts[-1].isoformat(),
            "current_cycle_day": cycle_day,
            "estimated_phase": estimated_phase,
            "phase_label": phase_label,
            "predicted_next_start": predicted.isoformat(),
            "prediction_window": {
                "start": (predicted - timedelta(days=max(2, round(variability or 2)))).isoformat(),
                "end": (predicted + timedelta(days=max(2, round(variability or 2)))).isoformat(),
            },
            "days_until": days_until,
            "reminder_days_before": reminder_days,
            "reminder_due": status == "upcoming",
            "confidence": round(confidence, 2),
            "message": _message(status, predicted, days_until, typical, variability),
            "disclaimer": "这是根据个人历史记录估算的时间窗，不用于避孕、诊断或替代医疗建议。",
        }


def _is_period_start(payload: dict[str, Any]) -> bool:
    phase = str(payload.get("phase") or payload.get("status") or "").lower()
    return bool(
        payload.get("period_started") is True
        or payload.get("cycle_day") == 1
        or phase in {"menstrual", "period", "经期", "月经期"}
        and payload.get("cycle_day") in {None, 1}
    )


def _message(
    status: str,
    predicted: date,
    days_until: int,
    typical: int,
    variability: float | None,
) -> str:
    spread = f"，历史波动约 {variability:g} 天" if variability is not None else ""
    if status == "upcoming":
        return f"预计约 {days_until} 天后进入经期，可提前安排恢复与用品准备。"
    if status == "overdue_window":
        return f"已超过估算日期 {abs(days_until)} 天；周期本身可能波动，如有疑虑请结合实际情况处理。"
    return f"按最近记录估算，下次经期约在 {predicted.isoformat()}；典型周期 {typical} 天{spread}。"
