from __future__ import annotations

import json
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from bodynote_agent.database import connect, new_id
from bodynote_agent.events import EventRepository
from bodynote_agent.preferences import DAILY_FIELD_EVENT_TYPES, OnboardingService, local_date


MODULE_WEIGHTS = {
    "movement": 25,
    "nutrition": 25,
    "body": 20,
    "recovery": 15,
}
MODULE_LABELS = {
    "movement": "活动",
    "nutrition": "饮食",
    "body": "身体状态",
    "recovery": "恢复与感受",
}


class HealthAnalysisService:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.events = EventRepository(database_path)
        self.onboarding = OnboardingService(database_path)

    def analyze(
        self,
        period_type: str,
        period_key: str | None = None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        settings = self.onboarding.status()
        if not settings["onboarding_completed"]:
            return {
                "ok": False,
                "error": "首次设置尚未完成，不能生成健康分析。",
                "missing_setup_fields": settings["missing_setup_fields"],
            }
        timezone_name = settings["profile"]["timezone"]
        if period_type == "daily":
            key = period_key or local_date(timezone_name, now)
            _parse_date(key)
            result = self._daily(key, settings)
        elif period_type == "weekly":
            key = period_key or local_date(timezone_name, now)
            _parse_date(key)
            result = self._weekly(key, settings)
        elif period_type == "monthly":
            key = period_key or local_date(timezone_name, now)[:7]
            _parse_month(key)
            result = self._monthly(key, settings)
        else:
            raise ValueError("period_type 必须是 daily、weekly 或 monthly。")
        self._persist(result)
        return result

    def _daily(self, day: str, settings: dict[str, Any]) -> dict[str, Any]:
        timezone_name = settings["profile"]["timezone"]
        events = self.events.list_period(
            start_date=day,
            end_date=day,
            timezone_name=timezone_name,
        )
        previous_start = (_parse_date(day) - timedelta(days=28)).isoformat()
        history = self.events.list_period(
            start_date=previous_start,
            end_date=day,
            timezone_name=timezone_name,
        )
        modules = _daily_modules(events, history)
        required = settings["schedule"]["required_daily_fields"]
        completed = _completed_fields(events, required)
        missing = [field for field in required if field not in completed]
        coverage = len(completed) / len(required) if required else 1.0
        reliability = _event_reliability(events)
        confidence = round(coverage * 0.75 + reliability * 0.25, 3)
        urgent = _urgent_events(events)
        score = _weighted_score(modules)
        if urgent:
            score = min(score if score is not None else 59, 59)
        status = _status(score, urgent=bool(urgent))
        insights = _daily_insights(events, modules, missing, urgent)
        actions = _daily_actions(events, modules, missing, urgent)
        summary = _daily_summary(score, status, confidence, modules, missing, urgent)
        return {
            "ok": True,
            "model": "daily-v1",
            "period_type": "daily",
            "period_key": day,
            "period": {"start": day, "end": day, "days": 1},
            "timezone": timezone_name,
            "goal": settings["profile"]["primary_goal"],
            "health_score": score,
            "confidence": confidence,
            "status": status,
            "data_completeness": {
                "coverage": round(coverage, 3),
                "required": required,
                "completed": completed,
                "missing": missing,
                "event_count": len(events),
            },
            "modules": modules,
            "insights": insights[:3],
            "actions": actions[:3],
            "summary": summary,
            "safety": _safety_block(urgent),
        }

    def _weekly(self, end_day: str, settings: dict[str, Any]) -> dict[str, Any]:
        end = _parse_date(end_day)
        start = end - timedelta(days=6)
        timezone_name = settings["profile"]["timezone"]
        events = self.events.list_period(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            timezone_name=timezone_name,
        )
        by_day = _events_by_local_day(events, timezone_name)
        trend = []
        for offset in range(7):
            day = (start + timedelta(days=offset)).isoformat()
            day_events = by_day.get(day, [])
            day_modules = _daily_modules(day_events, events)
            trend.append(
                {
                    "date": day,
                    "score": _weighted_score(day_modules),
                    "event_count": len(day_events),
                }
            )
        modules = _period_modules(events, days=7, timezone_name=timezone_name)
        days_with_data = sum(1 for point in trend if point["event_count"])
        confidence = round(min(1.0, days_with_data / 7 * 0.8 + _event_reliability(events) * 0.2), 3)
        score = _weighted_score(modules)
        urgent = _urgent_events(events)
        if urgent:
            score = min(score if score is not None else 59, 59)
        structure = _movement_structure(events)
        nutrition_pattern = _nutrition_pattern(events, timezone_name)
        recovery_pattern = _recovery_pattern(events)
        body_change = _body_change(events)
        insights = _weekly_insights(
            days_with_data, structure, nutrition_pattern, recovery_pattern, body_change
        )
        actions = _weekly_actions(structure, nutrition_pattern, recovery_pattern, days_with_data)
        status = _status(score, urgent=bool(urgent))
        return {
            "ok": True,
            "model": "weekly-v1",
            "period_type": "weekly",
            "period_key": end_day,
            "period": {"start": start.isoformat(), "end": end_day, "days": 7},
            "timezone": timezone_name,
            "goal": settings["profile"]["primary_goal"],
            "health_score": score,
            "confidence": confidence,
            "status": status,
            "data_completeness": {
                "days_with_data": days_with_data,
                "days_total": 7,
                "event_count": len(events),
                "coverage": round(days_with_data / 7, 3),
            },
            "modules": modules,
            "trend": trend,
            "movement_structure": structure,
            "nutrition_pattern": nutrition_pattern,
            "recovery_pattern": recovery_pattern,
            "body_change": body_change,
            "insights": insights[:3],
            "actions": actions[:3],
            "summary": {
                "headline": _weekly_headline(days_with_data, score),
                "focus": actions[0]["title"] if actions else "继续稳定记录",
            },
            "safety": _safety_block(urgent),
        }

    def _monthly(self, month: str, settings: dict[str, Any]) -> dict[str, Any]:
        start = _parse_month(month)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        timezone_name = settings["profile"]["timezone"]
        events = self.events.list_period(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            timezone_name=timezone_name,
        )
        by_day = _events_by_local_day(events, timezone_name)
        modules = _period_modules(events, days=end.day, timezone_name=timezone_name)
        days_with_data = len(by_day)
        confidence = round(
            min(1.0, days_with_data / max(14, end.day) * 0.8 + _event_reliability(events) * 0.2),
            3,
        )
        score = _weighted_score(modules)
        urgent = _urgent_events(events)
        if urgent:
            score = min(score if score is not None else 59, 59)
        body_change = _body_change(events)
        capacity = _training_capacity(events)
        consistency = _monthly_consistency(events, by_day)
        cycle = _cycle_summary(events)
        medical = _medical_followups(events)
        evidence_level = "sufficient" if days_with_data >= 8 else "summary_only"
        insights = _monthly_insights(
            evidence_level, body_change, capacity, consistency, cycle, medical
        )
        actions = _monthly_actions(evidence_level, consistency, medical, settings)
        status = _status(score, urgent=bool(urgent))
        return {
            "ok": True,
            "model": "monthly-v1",
            "period_type": "monthly",
            "period_key": month,
            "period": {"start": start.isoformat(), "end": end.isoformat(), "days": end.day},
            "timezone": timezone_name,
            "goal": settings["profile"]["primary_goal"],
            "health_score": score,
            "confidence": confidence,
            "status": status,
            "evidence_level": evidence_level,
            "data_completeness": {
                "days_with_data": days_with_data,
                "days_total": end.day,
                "event_count": len(events),
                "coverage": round(days_with_data / end.day, 3),
            },
            "modules": modules,
            "body_change": body_change,
            "training_capacity": capacity,
            "consistency": consistency,
            "cycle_summary": cycle,
            "medical_followups": medical,
            "insights": insights[:3],
            "actions": actions[:3],
            "summary": {
                "headline": _monthly_headline(evidence_level, score, body_change),
                "primary_next_goal": actions[0]["title"] if actions else settings["profile"]["primary_goal"],
            },
            "safety": _safety_block(urgent),
        }

    def _persist(self, result: dict[str, Any]) -> None:
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO insight_snapshots (
                        id, profile_id, period_type, period_key, health_score,
                        confidence, status, insights_json, modules_json,
                        actions_json, summary_json
                    ) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, period_type, period_key) DO UPDATE SET
                        health_score = excluded.health_score,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        insights_json = excluded.insights_json,
                        modules_json = excluded.modules_json,
                        actions_json = excluded.actions_json,
                        summary_json = excluded.summary_json,
                        generated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        new_id("insight"),
                        result["period_type"],
                        result["period_key"],
                        result["health_score"],
                        result["confidence"],
                        result["status"],
                        _json(result["insights"]),
                        _json(result["modules"]),
                        _json(result["actions"]),
                        _json(result["summary"]),
                    ),
                )


def _daily_modules(events: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
    modules = {
        "movement": _movement_module(events),
        "nutrition": _nutrition_module(events),
        "body": _body_module(events, history),
        "recovery": _recovery_module(events),
    }
    for key, module in modules.items():
        module["label"] = MODULE_LABELS[key]
    return modules


def _movement_module(events: list[dict[str, Any]]) -> dict[str, Any]:
    exercise = _of_type(events, "exercise")
    if not exercise:
        return _module(None, "暂无活动记录", 0.0, {})
    steps = sum(int(event["payload"].get("steps", 0)) for event in exercise)
    duration = sum(float(event["payload"].get("duration_min", 0)) for event in exercise)
    score = 72
    if steps >= 8000 or duration >= 30:
        score = 92
    elif steps >= 4000 or duration >= 15:
        score = 82
    elif steps and steps < 2000 and not duration:
        score = 62
    summary = f"{steps} 步" if steps else f"{round(duration)} 分钟活动"
    return _module(score, summary, _event_reliability(exercise), {"steps": steps, "duration_min": round(duration, 1), "sessions": len(exercise)})


def _nutrition_module(events: list[dict[str, Any]]) -> dict[str, Any]:
    meals = _of_type(events, "meal")
    if not meals:
        return _module(None, "暂无饮食记录", 0.0, {})
    meal_types = {event["payload"].get("meal_type") for event in meals} - {None, "unspecified"}
    score = 68 if len(meals) == 1 else 82 if len(meals) == 2 else 90
    if len(meal_types) >= 3:
        score = max(score, 92)
    protein_records = sum(1 for event in meals if "protein_g" in event["payload"])
    summary = f"记录 {len(meals)} 餐"
    return _module(score, summary, _event_reliability(meals), {"meals": len(meals), "known_meal_types": len(meal_types), "protein_records": protein_records})


def _body_module(events: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
    body = _of_type(events, "body")
    if not body:
        return _module(None, "暂无身体数据", 0.0, {})
    latest = body[-1]["payload"]
    score = 85
    warning = None
    weights = [
        float(event["payload"]["weight_kg"])
        for event in _of_type(history, "body")
        if "weight_kg" in event["payload"]
    ]
    current_weight = latest.get("weight_kg")
    if current_weight is not None and len(weights) >= 3:
        baseline = mean(weights[:-1]) if len(weights) > 1 else weights[0]
        if baseline and abs(float(current_weight) - baseline) / baseline >= 0.03:
            score = 65
            warning = "与近期记录差异较大，先复测并观察水分等影响"
    metrics = {key: latest[key] for key in ("weight_kg", "body_fat_pct", "waist_cm", "skeletal_muscle_kg") if key in latest}
    summary = f"体重 {current_weight} kg" if current_weight is not None else "已记录身体数据"
    if warning:
        summary = warning
    return _module(score, summary, _event_reliability(body), metrics)


def _recovery_module(events: list[dict[str, Any]]) -> dict[str, Any]:
    sleep = _of_type(events, "sleep")
    moods = _of_type(events, "mood")
    symptoms = _of_type(events, "symptom")
    scores: list[int] = []
    metrics: dict[str, Any] = {}
    if sleep:
        durations = [float(event["payload"]["duration_hours"]) for event in sleep if "duration_hours" in event["payload"]]
        if durations:
            hours = durations[-1]
            metrics["sleep_hours"] = hours
            scores.append(92 if 7 <= hours <= 9 else 76 if 6 <= hours <= 10 else 52)
    if moods:
        mood_values = [str(event["payload"].get("mood", "")) for event in moods]
        negative = {"tired", "stressed", "sad", "anxious", "self_harm_risk"}
        scores.append(55 if any(value in negative for value in mood_values) else 82)
        metrics["mood_records"] = len(moods)
    if symptoms:
        max_severity = max(int(event["payload"].get("severity", 3)) for event in symptoms)
        scores.append(50 if max_severity >= 7 else 68)
        metrics["max_symptom_severity"] = max_severity
    relevant = [*sleep, *moods, *symptoms]
    if not scores:
        return _module(None, "暂无睡眠或感受记录", 0.0, {})
    score = round(mean(scores))
    summary = f"睡眠 {metrics['sleep_hours']} 小时" if "sleep_hours" in metrics else "已记录今日感受"
    return _module(score, summary, _event_reliability(relevant), metrics)


def _period_modules(
    events: list[dict[str, Any]], *, days: int, timezone_name: str
) -> dict[str, Any]:
    modules = {
        "movement": _movement_module(events),
        "nutrition": _nutrition_module(events),
        "body": _body_module(events, events),
        "recovery": _recovery_module(events),
    }
    by_day = _events_by_local_day(events, timezone_name)
    for key, module in modules.items():
        count = len([event for event in events if event["event_type"] in _module_event_types(key)])
        daily_scores = []
        record_days = 0
        for day_events in by_day.values():
            daily_module = _daily_modules(day_events, events)[key]
            if daily_module["score"] is not None:
                record_days += 1
                daily_scores.append(daily_module["score"])
        module["label"] = MODULE_LABELS[key]
        module["score"] = round(mean(daily_scores)) if daily_scores else None
        module["status"] = _status(module["score"])
        module["confidence"] = round(
            min(1.0, record_days / days * 0.7 + _event_reliability(
                [event for event in events if event["event_type"] in _module_event_types(key)]
            ) * 0.3),
            3,
        )
        module["record_count"] = count
        module["record_days"] = record_days
        module["period_days"] = days
    return modules


def _module(score: int | None, summary: str, confidence: float, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": "",
        "score": score,
        "status": _status(score),
        "confidence": round(confidence, 3),
        "summary": summary,
        "metrics": metrics,
    }


def _weighted_score(modules: dict[str, Any]) -> int | None:
    available = [(key, module["score"]) for key, module in modules.items() if module["score"] is not None and key in MODULE_WEIGHTS]
    if not available:
        return None
    weighted = sum(float(score) * MODULE_WEIGHTS[key] for key, score in available)
    total_weight = sum(MODULE_WEIGHTS[key] for key, _ in available)
    return round(weighted / total_weight)


def _status(score: int | None, *, urgent: bool = False) -> str:
    if urgent:
        return "red"
    if score is None:
        return "unknown"
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


def _completed_fields(events: list[dict[str, Any]], required: list[str]) -> list[str]:
    types = {event["event_type"] for event in events}
    return [field for field in required if types.intersection(DAILY_FIELD_EVENT_TYPES[field])]


def _event_reliability(events: Iterable[dict[str, Any]]) -> float:
    values = [float(event["confidence"]) if event["confidence"] is not None else 0.85 for event in events]
    return round(mean(values), 3) if values else 0.0


def _urgent_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["payload"].get("red_flags")]


def _daily_insights(events: list[dict[str, Any]], modules: dict[str, Any], missing: list[str], urgent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if urgent:
        cards.append(_insight("risk", "red", "先处理需要关注的信号", "记录中出现了安全关注信号，健康分不会覆盖这项提醒。", [str(urgent[0]["payload"].get("red_flags"))], 1.0, "优先联系当地医疗或紧急支持资源。"))
    recovery = modules["recovery"]
    if recovery["metrics"].get("sleep_hours", 24) < 6:
        cards.append(_insight("explanation", "yellow", "恢复可能不足", "睡眠不足 6 小时，今天的疲劳或训练感受可能受其影响。", [f"睡眠 {recovery['metrics']['sleep_hours']} 小时"], recovery["confidence"], "明天优先保证睡眠窗口，训练降一级强度。"))
    movement = modules["movement"]
    if movement["metrics"].get("steps", 0) >= 8000 or movement["metrics"].get("duration_min", 0) >= 30:
        cards.append(_insight("achievement", "green", "今日活动目标已形成", movement["summary"], [movement["summary"]], movement["confidence"], "保持当前节奏，明天无需额外加量。"))
    if missing:
        labels = [MODULE_LABELS.get(field, field) for field in missing]
        cards.append(_insight("gap", "blue", "数据仍有缺口", "缺少的记录会降低判断置信度，但不会自动判定健康状态差。", labels, 1.0, "方便时补一句；不补也可按现有数据生成报告。"))
    nutrition = modules["nutrition"]
    if nutrition["metrics"].get("meals", 0) >= 3:
        cards.append(_insight("completion", "green", "饮食记录较完整", nutrition["summary"], [f"{nutrition['metrics']['meals']} 餐"], nutrition["confidence"], "继续保留主要餐次和大致份量。"))
    if not cards:
        cards.append(_insight("suggestion", "blue", "今天先从一条记录开始", "当前证据较少，暂不对健康状态下结论。", [f"共 {len(events)} 条记录"], 1.0, "记录最容易完成的一项即可。"))
    return cards


def _daily_actions(events: list[dict[str, Any]], modules: dict[str, Any], missing: list[str], urgent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if urgent:
        actions.append(_action("urgent", "优先确认安全", "现在", "如症状严重、突然出现或加重，及时联系当地急救或医疗机构。"))
    if modules["recovery"]["metrics"].get("sleep_hours", 24) < 6:
        actions.append(_action("recovery", "把明晚睡眠窗口提前 30 分钟", "明晚", "先恢复，再决定是否维持训练强度。"))
    if "movement" in missing:
        actions.append(_action("record", "补记活动或确认休息日", "今天", "缺记录不等于没有活动，补一句即可。"))
    elif modules["movement"]["score"] is not None and modules["movement"]["score"] < 70:
        actions.append(_action("movement", "安排 10-15 分钟轻活动", "明天", "以可持续完成为准，不追求补偿性运动。"))
    if "nutrition" in missing:
        actions.append(_action("record", "补记一顿主要餐食", "今天", "写下食物名称即可，不要求精确热量。"))
    if not actions:
        actions.append(_action("maintain", "保持今天最容易坚持的一项", "明天", "不额外加码，先让行为稳定重复。"))
    return _unique_actions(actions)


def _daily_summary(score: int | None, status: str, confidence: float, modules: dict[str, Any], missing: list[str], urgent: list[dict[str, Any]]) -> dict[str, Any]:
    if urgent:
        headline = "今天先关注安全信号"
    elif score is None:
        headline = "数据还不足，先不评价好坏"
    elif status == "green":
        headline = "今天整体在稳定区间"
    elif status == "yellow":
        headline = "今天有轻度偏移，适合小幅调整"
    else:
        headline = "今天有需要优先关注的部分"
    available = [module for module in modules.values() if module["score"] is not None]
    best = max(available, key=lambda item: item["score"])["summary"] if available else "暂无足够证据"
    return {"headline": headline, "best_signal": best, "missing_count": len(missing), "confidence_label": _confidence_label(confidence)}


def _movement_structure(events: list[dict[str, Any]]) -> dict[str, Any]:
    exercise = _of_type(events, "exercise")
    counts = Counter()
    body_parts = Counter()
    for event in exercise:
        payload = event["payload"]
        activity = str(payload.get("activity", "other")).lower()
        if any(token in activity for token in ("run", "walk", "cycle", "swim", "cardio", "跑", "走", "骑", "游")):
            counts["cardio"] += 1
        elif any(token in activity for token in ("strength", "weight", "squat", "deadlift", "力量", "深蹲", "硬拉")) or payload.get("sets"):
            counts["strength"] += 1
        else:
            counts["other"] += 1
        for part in payload.get("body_parts", []):
            body_parts[str(part)] += 1
    return {"sessions": len(exercise), "cardio": counts["cardio"], "strength": counts["strength"], "other": counts["other"], "body_parts": dict(body_parts)}


def _nutrition_pattern(events: list[dict[str, Any]], timezone_name: str) -> dict[str, Any]:
    meals = _of_type(events, "meal")
    zone = ZoneInfo(timezone_name)
    weekday = Counter()
    weekend = Counter()
    meal_types = Counter()
    for event in meals:
        local = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")).astimezone(zone)
        bucket = weekend if local.weekday() >= 5 else weekday
        bucket[local.date().isoformat()] += 1
        meal_types[str(event["payload"].get("meal_type", "unspecified"))] += 1
    return {"meals": len(meals), "meal_types": dict(meal_types), "weekday_daily_average": _counter_mean(weekday), "weekend_daily_average": _counter_mean(weekend)}


def _recovery_pattern(events: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(event["payload"]["duration_hours"]) for event in _of_type(events, "sleep") if "duration_hours" in event["payload"]]
    symptom_days = len(_of_type(events, "symptom"))
    return {"sleep_records": len(durations), "average_sleep_hours": round(mean(durations), 2) if durations else None, "symptom_records": symptom_days}


def _body_change(events: list[dict[str, Any]]) -> dict[str, Any]:
    body = _of_type(events, "body")
    result: dict[str, Any] = {"records": len(body), "sufficient": False}
    for field in ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "waist_cm"):
        values = [float(event["payload"][field]) for event in body if field in event["payload"]]
        if values:
            result[field] = {"first": values[0], "latest": values[-1], "change": round(values[-1] - values[0], 2), "records": len(values)}
    result["sufficient"] = any(item.get("records", 0) >= 2 for item in result.values() if isinstance(item, dict))
    return result


def _weekly_insights(days: int, structure: dict[str, Any], nutrition: dict[str, Any], recovery: dict[str, Any], body: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if days < 3:
        cards.append(_insight("gap", "blue", "本周证据仍偏少", f"7 天中有 {days} 天留下记录，暂时只做记录摘要。", [f"{days}/7 天"], 1.0, "下周优先稳定记录 3 天，不追求一次记全。"))
    if structure["sessions"]:
        cards.append(_insight("trend", "green" if structure["sessions"] >= 3 else "yellow", "本周运动结构", f"有氧 {structure['cardio']} 次，力量 {structure['strength']} 次，其他 {structure['other']} 次。", [f"共 {structure['sessions']} 次"], 0.9, "下周补上缺少的训练类型，保持休息日。"))
    if recovery["average_sleep_hours"] is not None:
        hours = recovery["average_sleep_hours"]
        cards.append(_insight("trend", "green" if 7 <= hours <= 9 else "yellow", "恢复节奏", f"有记录日平均睡眠 {hours} 小时。", [f"{recovery['sleep_records']} 条睡眠记录"], min(1.0, recovery["sleep_records"] / 5), "把睡眠时段稳定性放在训练加量之前。"))
    if body.get("sufficient") and "weight_kg" in body:
        change = body["weight_kg"]["change"]
        cards.append(_insight("trend", "blue", "体重周内变化", f"首末记录相差 {change:+.2f} kg，短期可能含水分波动。", [str(body["weight_kg"])], 0.65, "继续观察，不从单周变化推断脂肪或肌肉。"))
    return cards or [_insight("suggestion", "blue", "先建立可持续基线", "本周尚不足以识别稳定模式。", [f"{nutrition['meals']} 条饮食记录"], 0.5, "下周选择三天完成基础记录。")]


def _weekly_actions(structure: dict[str, Any], nutrition: dict[str, Any], recovery: dict[str, Any], days: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if days < 3:
        actions.append(_action("record", "下周完成 3 天基础记录", "下周", "每次只记活动、主要餐食和睡眠中的一项也可以。"))
    if structure["strength"] == 0 and structure["cardio"] > 0:
        actions.append(_action("movement", "加入 1 次基础力量训练", "下周", "选择熟悉动作，保留余力。"))
    elif structure["cardio"] == 0 and structure["strength"] > 0:
        actions.append(_action("movement", "加入 1 次低强度有氧", "下周", "20-30 分钟能对话的强度即可。"))
    if recovery["average_sleep_hours"] is not None and recovery["average_sleep_hours"] < 7:
        actions.append(_action("recovery", "固定 2 个较早入睡日", "下周", "先增加可执行的睡眠机会。"))
    if nutrition["meals"] < 7:
        actions.append(_action("nutrition", "至少记录 5 顿主要餐食", "下周", "用食物名称代替精确称重。"))
    return _unique_actions(actions) or [_action("maintain", "延续本周最稳定的行为", "下周", "保持可持续，不同时增加多个目标。")]


def _training_capacity(events: list[dict[str, Any]]) -> dict[str, Any]:
    exercise = _of_type(events, "exercise")
    return {"sessions": len(exercise), "max_steps": max((int(event["payload"].get("steps", 0)) for event in exercise), default=0), "max_duration_min": max((float(event["payload"].get("duration_min", 0)) for event in exercise), default=0), "total_duration_min": round(sum(float(event["payload"].get("duration_min", 0)) for event in exercise), 1)}


def _monthly_consistency(events: list[dict[str, Any]], by_day: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    type_days: dict[str, set[str]] = defaultdict(set)
    for day, day_events in by_day.items():
        for event in day_events:
            type_days[event["event_type"]].add(day)
    return {"active_days": len(by_day), "exercise_days": len(type_days["exercise"]), "meal_days": len(type_days["meal"]), "sleep_days": len(type_days["sleep"]), "body_days": len(type_days["body"])}


def _cycle_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    cycle = _of_type(events, "menstrual_cycle")
    return {"records": len(cycle), "sufficient_for_pattern": len(cycle) >= 2, "note": "至少两个周期后再判断规律" if len(cycle) < 2 else "已有基础周期证据，仍需结合主观感受"}


def _medical_followups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for event in _of_type(events, "medical_report"):
        payload = event["payload"]
        result.append({"date": event["occurred_at"][:10], "type": payload.get("report_type", "medical_report"), "findings": payload.get("findings", []), "actions": payload.get("action_candidates", [])})
    return result


def _monthly_insights(level: str, body: dict[str, Any], capacity: dict[str, Any], consistency: dict[str, Any], cycle: dict[str, Any], medical: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if level == "summary_only":
        return [_insight("gap", "blue", "本月以记录摘要为主", f"有记录的日期为 {consistency['active_days']} 天，证据不足以判断长期变化。", [f"{consistency['active_days']} 个记录日"], 1.0, "下月先稳定 8 个记录日。")]
    cards: list[dict[str, Any]] = []
    if body.get("sufficient") and "weight_kg" in body:
        change = body["weight_kg"]["change"]
        cards.append(_insight("trend", "blue", "身体变化", f"月内首末体重记录相差 {change:+.2f} kg；不单独解释为脂肪或肌肉变化。", [str(body["weight_kg"])], 0.75, "结合体脂、腰围和训练表现继续观察。"))
    if capacity["sessions"]:
        cards.append(_insight("achievement", "green", "本月训练积累", f"共 {capacity['sessions']} 次活动，累计 {capacity['total_duration_min']} 分钟。", [f"单次最长 {capacity['max_duration_min']} 分钟"], 0.9, "下月优先提高稳定性，不急于提高峰值。"))
    if medical:
        cards.append(_insight("risk", "yellow", "有体检事项待跟进", f"本月录入 {len(medical)} 份医疗报告。", [item["type"] for item in medical], 0.9, "按报告或医生建议确认复查事项。"))
    if cycle["records"] and not cycle["sufficient_for_pattern"]:
        cards.append(_insight("gap", "purple", "周期证据仍在积累", cycle["note"], [f"{cycle['records']} 条周期记录"], 0.5, "继续记录日期和主要症状，不提前判断规律。"))
    return cards or [_insight("trend", "blue", "本月行为开始形成基线", f"活动 {consistency['exercise_days']} 天，饮食 {consistency['meal_days']} 天，睡眠 {consistency['sleep_days']} 天。", [str(consistency)], 0.8, "选择一个最稳定的行为作为下月核心。")]


def _monthly_actions(level: str, consistency: dict[str, Any], medical: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    if medical:
        actions.append(_action("medical", "确认体检复查事项", "下月", "遵循医生或报告建议，不自行调整药物。"))
    if level == "summary_only":
        actions.append(_action("record", "建立 8 天基础记录", "下月", "分散到整月，比连续突击更有价值。"))
    else:
        candidates = {"exercise_days": "稳定活动日", "meal_days": "稳定主要餐食记录", "sleep_days": "稳定睡眠记录"}
        weakest = min(candidates, key=lambda key: consistency[key])
        actions.append(_action("goal", candidates[weakest], "下月", f"围绕主要目标“{settings['profile']['primary_goal']}”只增加一个可执行行为。"))
    return _unique_actions(actions)


def _weekly_headline(days: int, score: int | None) -> str:
    if days < 3:
        return "本周先建立记录基线"
    if score is not None and score >= 80:
        return "本周节奏整体稳定"
    return "本周出现了可调整的模式"


def _monthly_headline(level: str, score: int | None, body: dict[str, Any]) -> str:
    if level == "summary_only":
        return "本月证据较少，先看记录而非结论"
    if body.get("sufficient"):
        return "本月已有可比较的身体与行为变化"
    if score is not None and score >= 80:
        return "本月健康行为整体稳定"
    return "本月已经形成下一步行动线索"


def _insight(kind: str, severity: str, title: str, explanation: str, evidence: list[str], confidence: float, next_action: str) -> dict[str, Any]:
    return {"type": kind, "severity": severity, "title": title, "explanation": explanation, "evidence": evidence, "confidence": round(confidence, 3), "next_action": next_action}


def _action(kind: str, title: str, timing: str, rationale: str) -> dict[str, str]:
    return {"type": kind, "title": title, "timing": timing, "rationale": rationale}


def _unique_actions(actions: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result = []
    for action in actions:
        if action["title"] not in seen:
            seen.add(action["title"])
            result.append(action)
    return result


def _safety_block(urgent: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not urgent:
        return None
    return {"level": "urgent", "message": "记录中包含需要优先关注的安全信号。如症状严重、突然出现或持续加重，请及时联系当地急救或医疗机构。", "event_ids": [event["id"] for event in urgent]}


def _events_by_local_day(events: list[dict[str, Any]], timezone_name: str) -> dict[str, list[dict[str, Any]]]:
    zone = ZoneInfo(timezone_name)
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        result[occurred.astimezone(zone).date().isoformat()].append(event)
    return dict(result)


def _module_event_types(module: str) -> tuple[str, ...]:
    return {"movement": ("exercise",), "nutrition": ("meal",), "body": ("body",), "recovery": ("sleep", "mood", "symptom", "menstrual_cycle")}[module]


def _of_type(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in events if event["event_type"] == event_type]


def _counter_mean(counter: Counter[str]) -> float | None:
    return round(mean(counter.values()), 2) if counter else None


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "高"
    if value >= 0.5:
        return "中"
    return "低"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("日期必须是 YYYY-MM-DD。") from None


def _parse_month(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError:
        raise ValueError("月份必须是 YYYY-MM。") from None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
