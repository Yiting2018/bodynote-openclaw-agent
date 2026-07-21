from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Callable
from zoneinfo import ZoneInfo

from bodynote_agent.analytics import _daily_modules
from bodynote_agent.cycle import CycleForecastService
from bodynote_agent.events import EventRepository
from bodynote_agent.reference_library import ReferenceLibraryService


METRIC_META = {
    "steps": ("步数", "步", "sum"),
    "exercise_min": ("活动时长", "分钟", "sum"),
    "exercise_kcal": ("活动消耗", "kcal", "sum"),
    "strength_sessions": ("抗阻训练", "次", "sum"),
    "strength_volume_kg": ("抗阻总容量", "kg", "sum"),
    "calories_kcal": ("饮食能量", "kcal", "sum"),
    "protein_g": ("蛋白质", "g", "sum"),
    "carbs_g": ("碳水", "g", "sum"),
    "fat_g": ("脂肪", "g", "sum"),
    "fiber_g": ("膳食纤维", "g", "sum"),
    "weight_kg": ("体重", "kg", "last"),
    "body_fat_pct": ("体脂率", "%", "last"),
    "skeletal_muscle_kg": ("骨骼肌", "kg", "last"),
    "waist_cm": ("腰围", "cm", "last"),
    "sleep_hours": ("睡眠", "小时", "mean"),
    "fatigue": ("疲劳强度", "/10", "mean"),
}


class TrendAnalysisService:
    """Builds descriptive trends and association clues without causal claims."""

    def __init__(self, database_path: Path) -> None:
        self.events = EventRepository(database_path)
        self.cycle = CycleForecastService(database_path)
        self.references = ReferenceLibraryService(database_path)

    def analyze(
        self,
        reference_day: str,
        *,
        timezone_name: str,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        reference = date.fromisoformat(reference_day)
        history_start = reference - timedelta(days=370)
        events = self.events.list_period(
            start_date=history_start.isoformat(),
            end_date=reference.isoformat(),
            timezone_name=timezone_name,
            limit=20000,
        )
        daily = _daily_series(events, timezone_name)
        _attach_dimension_scores(
            daily,
            events,
            timezone_name=timezone_name,
            goal=profile.get("primary_goal") or "",
            profile_details=profile.get("details") or {},
        )
        ranges = _period_ranges(reference)
        periods = {
            key: _period_view(key, value, daily, events, timezone_name)
            for key, value in ranges.items()
        }
        details = profile.get("details") or {}
        latest_body = _latest_body(events)
        profile_view = {
            "display_name": profile.get("display_name") or "我的健康",
            "primary_goal": profile.get("primary_goal") or "持续了解身体状态",
            "age": _age(details.get("birth_date"), reference),
            "height_cm": details.get("height_cm"),
            "latest_body": latest_body,
        }
        active_guides = self.references.list(enabled_only=True)["guides"]
        cycle = self.cycle.forecast(
            reference.isoformat(),
            timezone_name=timezone_name,
            profile_details=details,
        )
        cycle["support"] = _cycle_support(
            cycle,
            daily,
            reference,
            profile.get("primary_goal") or "",
        )
        return {
            "reference_day": reference.isoformat(),
            "profile": profile_view,
            "history_series": [
                {"date": day, **daily.get(day, {})}
                for day in _dates(reference - timedelta(days=13), reference)
            ],
            # The dashboard keeps this local history so a user-selected date range
            # can be recalculated in the browser without a network request.
            "daily_series": [
                {"date": day, **daily.get(day, {})}
                for day in _dates(history_start, reference)
            ],
            "periods": periods,
            "cycle": cycle,
            "references": [
                {
                    "id": guide["id"],
                    "title": guide["title"],
                    "version": guide["version"],
                    "scope": guide["scope"],
                    "citations": guide["citations"],
                }
                for guide in active_guides
            ],
            "analysis_policy": {
                "language": "关联线索，不代表因果关系",
                "minimum_pair_samples": 3,
                "guides_can_override_safety": False,
            },
        }


def _period_ranges(reference: date) -> dict[str, dict[str, date]]:
    week_start = reference - timedelta(days=reference.weekday())
    month_start = reference.replace(day=1)
    return {
        "daily": {
            "start": reference,
            "end": reference,
            "previous_start": reference - timedelta(days=1),
            "previous_end": reference - timedelta(days=1),
        },
        "weekly": _with_previous(week_start, reference),
        "monthly": _with_previous(month_start, reference),
    }


def _with_previous(start: date, end: date) -> dict[str, date]:
    days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    return {
        "start": start,
        "end": end,
        "previous_start": previous_end - timedelta(days=days - 1),
        "previous_end": previous_end,
    }


def _daily_series(events: list[dict[str, Any]], timezone_name: str) -> dict[str, dict[str, Any]]:
    series: dict[str, dict[str, Any]] = defaultdict(lambda: {"event_count": 0})
    zone = ZoneInfo(timezone_name)
    for event in events:
        occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=zone)
        day = occurred.astimezone(zone).date().isoformat()
        point = series[day]
        point["event_count"] += 1
        payload = event["payload"]
        if event["event_type"] == "exercise":
            _add(point, "steps", payload.get("steps"))
            _add(point, "exercise_min", payload.get("duration_min"))
            _add(point, "exercise_kcal", payload.get("calories_kcal"))
            point["exercise_sessions"] = point.get("exercise_sessions", 0) + 1
            if _is_strength(payload):
                point["strength_sessions"] = point.get("strength_sessions", 0) + 1
                _add(point, "strength_volume_kg", _strength_volume(payload))
        elif event["event_type"] == "meal":
            point["meal_records"] = point.get("meal_records", 0) + 1
            for field in ("calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"):
                _add(point, field, payload.get(field))
        elif event["event_type"] == "body":
            for field in ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "waist_cm"):
                if _number(payload.get(field)) is not None:
                    point[field] = float(payload[field])
        elif event["event_type"] == "sleep":
            _append(point, "_sleep", payload.get("duration_hours"))
        elif event["event_type"] in {"mood", "symptom"}:
            label = str(payload.get("mood") or payload.get("symptom") or "").lower()
            if any(token in label for token in ("疲", "累", "fatigue", "tired")):
                _append(point, "_fatigue", payload.get("intensity") or payload.get("severity"))
    for point in series.values():
        if point.get("_sleep"):
            point["sleep_hours"] = round(mean(point.pop("_sleep")), 2)
        if point.get("_fatigue"):
            point["fatigue"] = round(mean(point.pop("_fatigue")), 2)
    return dict(series)


def _period_view(
    period_type: str,
    bounds: dict[str, date],
    daily: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    timezone_name: str,
) -> dict[str, Any]:
    current_dates = _dates(bounds["start"], bounds["end"])
    previous_dates = _dates(bounds["previous_start"], bounds["previous_end"])
    current = _summaries(current_dates, daily)
    previous = _summaries(previous_dates, daily)
    metrics = {
        key: _metric_summary(key, current.get(key), previous.get(key), current_dates, daily)
        for key in METRIC_META
        if current.get(key) is not None or previous.get(key) is not None
    }
    period_events = [
        event for event in events
        if bounds["start"] <= _event_date(event, timezone_name) <= bounds["end"]
    ]
    domains = {
        "activity": _domain("活动", ("steps", "exercise_min", "exercise_kcal", "strength_sessions", "strength_volume_kg"), metrics),
        "nutrition": _domain("饮食", ("calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"), metrics),
        "body": _domain("身体变化", ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "waist_cm"), metrics),
        "recovery": _domain("恢复与感受", ("sleep_hours", "fatigue"), metrics),
    }
    relationships = _relationships(metrics)
    dimension_scores = _dimension_score_summary(current_dates, previous_dates, daily)
    completeness = round(sum(1 for day in current_dates if daily.get(day)) / len(current_dates), 2)
    return {
        "period_type": period_type,
        "range": {"start": bounds["start"].isoformat(), "end": bounds["end"].isoformat()},
        "comparison_range": {"start": bounds["previous_start"].isoformat(), "end": bounds["previous_end"].isoformat()},
        "days": len(current_dates),
        "event_count": len(period_events),
        "data_completeness": completeness,
        "series": [{"date": day, **daily.get(day, {})} for day in current_dates],
        "metrics": metrics,
        "domains": domains,
        "dimension_scores": dimension_scores,
        "relationships": relationships,
        "opportunities": _opportunities(metrics, completeness),
        "risks": _risks(metrics, completeness),
    }


def _attach_dimension_scores(
    daily: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    timezone_name: str,
    goal: str,
    profile_details: dict[str, Any],
) -> None:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_day[_event_date(event, timezone_name).isoformat()].append(event)
    score_keys = {
        "movement": "activity_score",
        "nutrition": "nutrition_score",
        "body": "body_score",
        "recovery": "recovery_score",
    }
    for day, day_events in by_day.items():
        modules = _daily_modules(
            day_events,
            events,
            goal=goal,
            profile_details=profile_details,
        )
        point = daily.setdefault(day, {"event_count": len(day_events)})
        for module_key, score_key in score_keys.items():
            point[score_key] = modules[module_key]["score"]


def _dimension_score_summary(
    current_dates: list[str],
    previous_dates: list[str],
    daily: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    definitions = (
        ("activity_score", "活动", "活动频率、时长、抗阻容量与强度"),
        ("nutrition_score", "饮食", "相对个人能量与营养目标；记录覆盖只影响置信度"),
        ("body_score", "身体状态", "相对个人基线的波动复核；测量覆盖只影响置信度"),
        ("recovery_score", "恢复与感受", "睡眠、疲劳、症状与主观感受"),
    )
    result = []
    for key, label, basis in definitions:
        current_values = [daily[day][key] for day in current_dates if daily.get(day, {}).get(key) is not None]
        previous_values = [daily[day][key] for day in previous_dates if daily.get(day, {}).get(key) is not None]
        current = round(mean(current_values)) if current_values else None
        previous = round(mean(previous_values)) if previous_values else None
        result.append({
            "key": key,
            "label": label,
            "basis": basis,
            "current": current,
            "previous": previous,
            "delta": current - previous if current is not None and previous is not None else None,
            "samples": len(current_values),
        })
    return result


def _cycle_support(
    forecast: dict[str, Any],
    daily: dict[str, dict[str, Any]],
    reference: date,
    goal: str,
) -> dict[str, Any]:
    if not forecast.get("enabled"):
        return {"visible": False}
    if forecast.get("status") in {"learning", "irregular_data"}:
        return {
            "visible": True,
            "evidence": "learning",
            "title": "周期规律积累中",
            "note": forecast.get("message", "继续记录经期开始日期和主要感受。"),
            "action": "当前不根据周期调整训练或饮食计划。",
        }
    comparisons = _phase_matched_comparisons(forecast, daily, reference)
    recent_days = _dates(reference - timedelta(days=4), reference)
    baseline_days = _dates(reference - timedelta(days=18), reference - timedelta(days=5))
    for key, label, unit in (
        ("weight_kg", "体重", "kg"),
        ("strength_volume_kg", "抗阻容量", "kg"),
        ("exercise_min", "活动时长", "分钟"),
        ("carbs_g", "碳水记录", "g"),
        ("sleep_hours", "睡眠", "小时"),
        ("fatigue", "疲劳", "/10"),
    ):
        recent = [float(daily[day][key]) for day in recent_days if _number(daily.get(day, {}).get(key)) is not None]
        baseline = [float(daily[day][key]) for day in baseline_days if _number(daily.get(day, {}).get(key)) is not None]
        if len(recent) < 2 or len(baseline) < 3:
            continue
        recent_average, baseline_average = mean(recent), mean(baseline)
        if not baseline_average:
            continue
        if key == "weight_kg":
            change_kg = round(recent_average - baseline_average, 2)
            if abs(change_kg) >= 0.3:
                comparisons.append(f"近5天{label}较个人前期基线{change_kg:+g} kg")
            continue
        change = round((recent_average - baseline_average) / abs(baseline_average) * 100)
        if abs(change) >= 8:
            comparisons.append(f"近5天{label}较个人前期基线{change:+d}%")
    phase = forecast.get("estimated_phase")
    if phase == "luteal":
        general = "部分人此时会有腹胀、短期体重波动或更想吃碳水；这不代表意志力不足。正常安排主食、蛋白质和蔬菜，是否调整训练以个人感受和历史表现为准。"
    elif phase == "menstrual":
        general = "短期体重变化可能与水分有关，不必因单日数字额外节食或加练；如疼痛或疲劳明显，可按感受调整训练量。"
    else:
        general = "保持既定训练与饮食计划，继续记录表现和恢复，为个人周期规律积累证据。"
    if any(token in goal for token in ("增肌", "力量", "抗阻")) and phase == "luteal":
        general = "部分人此时会有腹胀、短期体重波动或更想吃碳水；这不代表意志力不足。增肌目标下正常保证训练日前后的碳水、蛋白质和总能量，不因阶段标签自动降低训练强度。"
    return {
        "visible": True,
        "evidence": "personal" if comparisons else "general",
        "title": f"{forecast.get('phase_label', '周期阶段')} · 第 {forecast.get('current_cycle_day', '--')} 天",
        "note": "；".join(comparisons[:2]) if comparisons else "个人阶段表现样本仍不足，当前仅显示一般参考。",
        "action": general,
    }


def _phase_matched_comparisons(
    forecast: dict[str, Any],
    daily: dict[str, dict[str, Any]],
    reference: date,
) -> list[str]:
    """Compare today with the same personal cycle window in earlier cycles."""
    last_start_text = forecast.get("last_period_start")
    typical = int(forecast.get("typical_cycle_days") or 0)
    cycle_day = int(forecast.get("current_cycle_day") or 0)
    if not last_start_text or not 15 <= typical <= 60 or cycle_day < 1:
        return []
    last_start = date.fromisoformat(str(last_start_text))
    current_center = last_start + timedelta(days=cycle_day - 1)
    if abs((current_center - reference).days) > 3:
        current_center = reference
    results = []
    for key, label, unit in (
        ("weight_kg", "体重", "kg"),
        ("carbs_g", "碳水", "g"),
        ("sleep_hours", "睡眠", "小时"),
        ("fatigue", "疲劳", "/10"),
        ("exercise_min", "活动时长", "分钟"),
    ):
        current_values = [
            float(daily[day][key])
            for day in _dates(current_center - timedelta(days=2), current_center + timedelta(days=2))
            if _number(daily.get(day, {}).get(key)) is not None
        ]
        historical_cycle_values = []
        for cycle_index in range(1, 4):
            center = current_center - timedelta(days=typical * cycle_index)
            values = [
                float(daily[day][key])
                for day in _dates(center - timedelta(days=2), center + timedelta(days=2))
                if _number(daily.get(day, {}).get(key)) is not None
            ]
            if values:
                historical_cycle_values.append(mean(values))
        if not current_values or len(historical_cycle_values) < 2:
            continue
        current_average = mean(current_values)
        historical_average = mean(historical_cycle_values)
        if key == "weight_kg":
            change = current_average - historical_average
            if abs(change) >= 0.2:
                results.append(f"过去 {len(historical_cycle_values)} 个周期相近阶段体重均值约 {historical_average:.1f} kg，本次{change:+.1f} kg，更可能先按短期水分波动观察")
        elif historical_average:
            change_pct = round((current_average - historical_average) / abs(historical_average) * 100)
            if abs(change_pct) >= 10:
                results.append(f"过去 {len(historical_cycle_values)} 个周期相近阶段{label}均值约 {historical_average:.1f}{unit}，本次{change_pct:+d}%")
    return results


def _summaries(days: list[str], daily: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key, (_, _, reducer) in METRIC_META.items():
        values = [float(daily[day][key]) for day in days if _number(daily.get(day, {}).get(key)) is not None]
        if not values:
            result[key] = None
        elif reducer == "sum":
            result[key] = round(sum(values), 2)
        elif reducer == "last":
            result[key] = values[-1]
        else:
            result[key] = round(mean(values), 2)
    return result


def _metric_summary(key: str, current: float | None, previous: float | None, days: list[str], daily: dict[str, dict[str, Any]]) -> dict[str, Any]:
    label, unit, _ = METRIC_META[key]
    delta = round(current - previous, 2) if current is not None and previous is not None else None
    samples = sum(1 for day in days if _number(daily.get(day, {}).get(key)) is not None)
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "current": current,
        "previous": previous,
        "delta": delta,
        "change_pct": round(delta / abs(previous) * 100, 1) if delta is not None and previous else None,
        "samples": samples,
        "confidence": _confidence(samples, len(days)),
    }


def _domain(label: str, keys: tuple[str, ...], metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    available = [metrics[key] for key in keys if key in metrics]
    return {"label": label, "metrics": available, "evidence_count": sum(item["samples"] for item in available)}


def _relationships(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    candidates = [
        ("protein_g", "skeletal_muscle_kg", "蛋白质与骨骼肌同步变化"),
        ("strength_sessions", "skeletal_muscle_kg", "抗阻训练与骨骼肌同步变化"),
        ("steps", "weight_kg", "活动量与体重同步变化"),
        ("sleep_hours", "fatigue", "睡眠与疲劳同步变化"),
    ]
    for left_key, right_key, title in candidates:
        left, right = metrics.get(left_key), metrics.get(right_key)
        if not left or not right or left["delta"] is None or right["delta"] is None:
            continue
        samples = min(left["samples"], right["samples"])
        direction = "同向" if left["delta"] * right["delta"] >= 0 else "反向"
        cards.append({
            "title": title,
            "summary": f"本期{left['label']}变化 {left['delta']:+g} {left['unit']}，{right['label']}变化 {right['delta']:+g} {right['unit']}，呈{direction}线索。",
            "sample_size": samples,
            "confidence": "中" if samples >= 5 else "低",
            "caveat": "同期变化不代表因果，体成分还可能受水分、测量误差和时间滞后影响。",
        })
    return cards


def _opportunities(metrics: dict[str, dict[str, Any]], completeness: float) -> list[str]:
    items: list[str] = []
    if completeness < 0.6:
        items.append("先提高记录连续性，再解释长期变化。")
    if "protein_g" not in metrics:
        items.append("补充蛋白质克数后，可分析摄入与训练、体成分的同步变化。")
    if metrics.get("strength_sessions", {}).get("current", 0) == 0:
        items.append("本期未识别到抗阻训练，可按个人目标安排或补录训练类型。")
    return items[:3] or ["继续保持当前记录节奏，积累可比较的个人基线。"]


def _risks(metrics: dict[str, dict[str, Any]], completeness: float) -> list[str]:
    items: list[str] = []
    sleep = metrics.get("sleep_hours", {}).get("current")
    fatigue = metrics.get("fatigue", {}).get("current")
    if sleep is not None and sleep < 6:
        items.append("有记录日平均睡眠低于 6 小时，训练加量前应优先关注恢复。")
    if fatigue is not None and fatigue >= 7:
        items.append("疲劳记录偏高且可能持续，若伴随异常症状应及时寻求专业评估。")
    if completeness < 0.35:
        items.append("数据覆盖较低，当前趋势结论不稳定。")
    return items


def _latest_body(events: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for event in events:
        if event["event_type"] != "body":
            continue
        for key in ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "waist_cm"):
            if key in event["payload"]:
                result[key] = event["payload"][key]
        result["recorded_at"] = event["occurred_at"]
    return result


def _is_strength(payload: dict[str, Any]) -> bool:
    activity = str(payload.get("activity") or "").lower()
    return any(token in activity for token in ("strength", "resistance", "weight", "力量", "抗阻", "举铁"))


def _strength_volume(payload: dict[str, Any]) -> float | None:
    direct = _number(payload.get("volume_kg"))
    if direct is not None:
        return direct
    sets, reps, weight = (_number(payload.get(key)) for key in ("sets", "reps", "weight_kg"))
    return sets * reps * weight if sets is not None and reps is not None and weight is not None else None


def _event_date(event: dict[str, Any], timezone_name: str) -> date:
    value = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))
    return value.astimezone(ZoneInfo(timezone_name)).date()


def _dates(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def _age(birth_date: Any, reference: date) -> int | None:
    if not birth_date:
        return None
    try:
        born = date.fromisoformat(str(birth_date))
    except ValueError:
        return None
    return reference.year - born.year - ((reference.month, reference.day) < (born.month, born.day))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _add(target: dict[str, Any], key: str, value: Any) -> None:
    number = _number(value)
    if number is not None:
        target[key] = round(float(target.get(key, 0)) + number, 2)


def _append(target: dict[str, Any], key: str, value: Any) -> None:
    number = _number(value)
    if number is not None:
        target.setdefault(key, []).append(number)


def _confidence(samples: int, days: int) -> str:
    ratio = samples / max(1, days)
    if samples >= 5 and ratio >= 0.6:
        return "高"
    if samples >= 2 and ratio >= 0.3:
        return "中"
    return "低"
