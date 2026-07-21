from __future__ import annotations

from datetime import datetime

from bodynote_agent.handlers.activity import parse_exercise
from bodynote_agent.handlers.contracts import DomainHandler, HandlerResult
from bodynote_agent.handlers.cycle import parse_cycle
from bodynote_agent.handlers.medical import parse_medical_report
from bodynote_agent.handlers.nutrition import parse_meal
from bodynote_agent.handlers.recovery import parse_mood, parse_sleep, parse_symptom
from bodynote_agent.handlers.vitals import parse_blood_pressure, parse_body, parse_glucose
from bodynote_agent.time_utils import infer_occurred_at


# Compatibility name retained for callers that imported the original envelope.
ParsedCheckin = HandlerResult


class ParseError(ValueError):
    pass


DOMAIN_HANDLERS = (
    DomainHandler("BloodPressureHandler", "record_blood_pressure", "blood_pressure", ("systolic", "diastolic"), parse_blood_pressure),
    DomainHandler("BloodGlucoseHandler", "record_blood_glucose", "blood_glucose", ("glucose_mmol_l",), parse_glucose),
    DomainHandler("BodyHandler", "record_body", "body", ("one_body_metric",), parse_body),
    DomainHandler("SleepHandler", "record_sleep", "sleep", ("duration_hours_or_quality",), parse_sleep),
    DomainHandler("CycleHandler", "record_cycle", "menstrual_cycle", (), parse_cycle),
    DomainHandler("SymptomHandler", "record_symptom", "symptom", ("symptom",), parse_symptom),
    DomainHandler("MedicalReportHandler", "record_medical_report", "medical_report", ("report_type",), parse_medical_report),
    DomainHandler("ExerciseHandler", "record_exercise", "exercise", ("activity",), parse_exercise),
    DomainHandler("MealHandler", "record_meal", "meal", ("foods",), parse_meal),
    DomainHandler("MoodHandler", "record_mood", "mood", ("mood",), parse_mood),
)


def parse_checkin_text(text: str, *, now: datetime | None = None) -> HandlerResult:
    normalized = " ".join(text.strip().split())
    if not normalized:
        raise ParseError("记录内容不能为空。")
    if _looks_like_question_without_record(normalized):
        raise ParseError("这句话更像健康问题，不会作为健康记录保存。")
    if _looks_like_sleep_plan(normalized):
        raise ParseError("这句话是睡眠计划，不会保存为已经完成的睡眠记录。")

    handler, parsed, candidates = _route_checkin(normalized)
    if parsed is None:
        raise ParseError("暂时无法确定这是一条饮食、运动、身体、睡眠、情绪、症状、生理期或医疗报告记录。")
    occurred_at, time_source = infer_occurred_at(normalized, now=now, event_type=parsed.event_type)
    payload = dict(parsed.payload)
    payload["occurred_at_source"] = time_source
    if parsed.event_type == "sleep" and time_source == "sleep_wake_date":
        payload["sleep_date"] = occurred_at[:10]
    candidate_names = tuple(item.name for item in candidates)
    ambiguities = list(parsed.ambiguities)
    warnings = list(parsed.warnings)
    if time_source == "fuzzy_time":
        ambiguities.append("fuzzy_occurred_at:early_morning")
        warnings.append("fuzzy_time_assumed_06_30")
    if len(candidates) > 1:
        ambiguities.append("competing_handlers:" + ",".join(candidate_names))
        warnings.append("multiple_domain_intents")
    missing = tuple(field for field in handler.required_fields if not _field_satisfied(field, payload))
    if missing:
        ambiguities.extend(f"missing_required_field:{field}" for field in missing)
    return parsed.routed(
        handler=handler.name,
        occurred_at=occurred_at,
        payload=payload,
        candidates=candidate_names,
        ambiguities=tuple(dict.fromkeys(ambiguities)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _route_checkin(text: str) -> tuple[DomainHandler, HandlerResult | None, list[DomainHandler]]:
    matches = [(handler, parsed) for handler in DOMAIN_HANDLERS if (parsed := handler.parser(text)) is not None]
    if not matches:
        return DomainHandler("UnknownHandler", "unknown", "", (), lambda _: None), None, []
    handler, parsed = matches[0]
    return handler, parsed, [item[0] for item in matches]


def _field_satisfied(field: str, payload: dict[str, object]) -> bool:
    if field == "one_body_metric":
        return any(key in payload for key in ("weight_kg", "body_fat_pct", "waist_cm", "bmi", "skeletal_muscle_kg", "muscle_mass_kg"))
    if field == "duration_hours_or_quality":
        return "duration_hours" in payload or "quality" in payload
    return field in payload and payload[field] not in (None, "", [])


def _looks_like_sleep_plan(text: str) -> bool:
    future = any(marker in text for marker in ("今晚", "今天晚上", "明晚", "明天晚上"))
    intention = any(marker in text for marker in ("想睡", "准备睡", "计划睡", "打算睡", "希望睡", "目标"))
    return future and intention


def _looks_like_question_without_record(text: str) -> bool:
    if not any(marker in text for marker in ("？", "?", "怎么", "如何", "应该", "能不能", "可以吗", "建议")):
        return False
    record_markers = ("吃了", "喝了", "走了", "跑了", "练了", "睡了", "测了", "来月经", "来例假", "感觉", "今天很", "昨天很", "体检报告", "检查报告", "化验单")
    import re
    has_numeric_measurement = bool(re.search(r"(?:血压|血糖|体重|体脂|腰围|心率)\D{0,5}\d", text))
    return not has_numeric_measurement and not any(marker in text for marker in record_markers)
