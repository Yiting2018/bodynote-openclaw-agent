from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_EVENT_TYPES = {
    "blood_pressure",
    "blood_glucose",
    "body",
    "sleep",
    "exercise",
    "meal",
    "mood",
    "symptom",
    "menstrual_cycle",
    "medical_report",
}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    payload: dict[str, Any]
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    follow_up_question: str | None = None


def validate_event(event_type: str, payload: dict[str, Any]) -> ValidationResult:
    if event_type not in ALLOWED_EVENT_TYPES:
        return ValidationResult(False, payload, (f"不支持的记录类型：{event_type}",))
    if not isinstance(payload, dict):
        return ValidationResult(False, {}, ("payload 必须是 JSON object。",))

    normalized = dict(payload)
    errors: list[str] = []
    warnings: list[str] = []
    follow_up: str | None = None

    if event_type == "blood_pressure":
        _require_number(normalized, "systolic", errors)
        _require_number(normalized, "diastolic", errors)
        _range(normalized, "systolic", 50, 260, errors)
        _range(normalized, "diastolic", 30, 160, errors)
        _range(normalized, "heart_rate_bpm", 25, 250, errors)
    elif event_type == "blood_glucose":
        _require_number(normalized, "glucose_mmol_l", errors)
        _range(normalized, "glucose_mmol_l", 1, 40, errors)
    elif event_type == "body":
        numeric_fields = {
            "weight_kg": (20, 400),
            "body_fat_pct": (1, 75),
            "waist_cm": (30, 250),
            "bmi": (8, 80),
            "skeletal_muscle_kg": (5, 100),
            "muscle_mass_kg": (5, 200),
        }
        if not any(key in normalized for key in numeric_fields):
            errors.append("身体记录至少需要一个可识别的数值。")
        for key, bounds in numeric_fields.items():
            _range(normalized, key, bounds[0], bounds[1], errors)
    elif event_type == "sleep":
        if "duration_hours" not in normalized and "quality" not in normalized:
            errors.append("睡眠记录至少需要时长或质量。")
        _range(normalized, "duration_hours", 0, 24, errors)
    elif event_type == "exercise":
        if not normalized.get("activity"):
            errors.append("运动记录缺少活动类型。")
        _range(normalized, "steps", 0, 200000, errors)
        _range(normalized, "duration_min", 0, 1440, errors)
        _range(normalized, "distance_km", 0, 500, errors)
        _range(normalized, "calories_kcal", 0, 10000, errors)
        _range(normalized, "avg_heart_rate_bpm", 25, 250, errors)
    elif event_type == "meal":
        foods = normalized.get("foods")
        if not isinstance(foods, list) or not any(str(item).strip() for item in foods):
            errors.append("饮食记录至少需要一种食物或饮品。")
        if not normalized.get("meal_type"):
            normalized["meal_type"] = "unspecified"
            follow_up = "这是早餐、午餐、晚餐还是加餐？不补也可以，日报会标记为餐次未知。"
            warnings.append("meal_type_missing")
        _range(normalized, "calories_kcal", 0, 10000, errors)
        for key in ("protein_g", "fat_g", "carbs_g", "fiber_g"):
            _range(normalized, key, 0, 1000, errors)
    elif event_type == "mood":
        if not normalized.get("mood"):
            errors.append("情绪记录缺少情绪标签。")
        _range(normalized, "intensity", 1, 10, errors)
    elif event_type == "symptom":
        if not normalized.get("symptom"):
            errors.append("症状记录缺少症状名称。")
        _range(normalized, "severity", 1, 10, errors)
    elif event_type == "menstrual_cycle":
        _range(normalized, "cycle_day", 1, 60, errors)
    elif event_type == "medical_report":
        if not str(normalized.get("report_type") or "").strip():
            errors.append("医疗报告缺少报告类型。")
        for key in ("findings", "action_candidates"):
            if key in normalized and not isinstance(normalized[key], list):
                errors.append(f"{key} 必须是 list。")

    if normalized.get("red_flags"):
        warnings.append("safety_attention_required")

    return ValidationResult(
        ok=not errors,
        payload=normalized,
        errors=tuple(errors),
        warnings=tuple(dict.fromkeys(warnings)),
        follow_up_question=follow_up,
    )


def _require_number(payload: dict[str, Any], key: str, errors: list[str]) -> None:
    if key not in payload or not isinstance(payload[key], (int, float)):
        errors.append(f"缺少有效数值：{key}。")


def _range(
    payload: dict[str, Any],
    key: str,
    minimum: float,
    maximum: float,
    errors: list[str],
) -> None:
    if key not in payload:
        return
    value = payload[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{key} 必须是数值。")
        return
    if value < minimum or value > maximum:
        errors.append(f"{key} 超出可接受范围 {minimum}-{maximum}。")
