from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bodynote_agent.time_utils import infer_occurred_at


@dataclass(frozen=True)
class ParsedCheckin:
    event_type: str
    occurred_at: str
    payload: dict[str, Any]
    confidence: float
    follow_up_question: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


class ParseError(ValueError):
    pass


def parse_checkin_text(text: str, *, now: datetime | None = None) -> ParsedCheckin:
    normalized = " ".join(text.strip().split())
    if not normalized:
        raise ParseError("记录内容不能为空。")
    if _looks_like_question_without_record(normalized):
        raise ParseError("这句话更像健康问题，不会作为健康记录保存。")

    occurred_at, time_source = infer_occurred_at(normalized, now=now)

    parsed = (
        _parse_blood_pressure(normalized)
        or _parse_glucose(normalized)
        or _parse_body(normalized)
        or _parse_sleep(normalized)
        or _parse_cycle(normalized)
        or _parse_symptom(normalized)
        or _parse_exercise(normalized)
        or _parse_meal(normalized)
        or _parse_mood(normalized)
    )
    if parsed is None:
        raise ParseError(
            "暂时无法确定这是一条饮食、运动、身体、睡眠、情绪、症状或生理期记录。"
        )

    payload = dict(parsed.payload)
    payload["occurred_at_source"] = time_source
    return ParsedCheckin(
        event_type=parsed.event_type,
        occurred_at=occurred_at,
        payload=payload,
        confidence=parsed.confidence,
        follow_up_question=parsed.follow_up_question,
        warnings=parsed.warnings,
    )


def _result(
    event_type: str,
    payload: dict[str, Any],
    confidence: float,
    *,
    follow_up: str | None = None,
    warnings: tuple[str, ...] = (),
) -> ParsedCheckin:
    return ParsedCheckin(
        event_type=event_type,
        occurred_at="",
        payload=payload,
        confidence=confidence,
        follow_up_question=follow_up,
        warnings=warnings,
    )


def _parse_blood_pressure(text: str) -> ParsedCheckin | None:
    match = re.search(r"(?<!\d)([1-2]?\d{2})\s*/\s*(\d{2,3})(?!\d)", text)
    if "血压" not in text and not match:
        return None
    payload: dict[str, Any] = {}
    if match:
        payload["systolic"] = int(match.group(1))
        payload["diastolic"] = int(match.group(2))
    heart_rate = re.search(r"(?:心率|脉搏)\s*[:：]?\s*(\d{2,3})", text)
    if heart_rate:
        payload["heart_rate_bpm"] = int(heart_rate.group(1))
    follow_up = None if match else "请补充收缩压/舒张压，例如 132/86。"
    return _result("blood_pressure", payload, 0.96 if match else 0.55, follow_up=follow_up)


def _parse_glucose(text: str) -> ParsedCheckin | None:
    if "血糖" not in text and "mmol" not in text.lower() and "毫摩尔" not in text:
        return None
    match = re.search(r"(?:血糖)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:mmol(?:/L)?|毫摩尔)?", text, re.I)
    payload: dict[str, Any] = {}
    if match:
        payload["glucose_mmol_l"] = float(match.group(1))
    if "空腹" in text:
        payload["context"] = "fasting"
    elif "餐后" in text or "饭后" in text:
        payload["context"] = "postprandial"
    else:
        payload["context"] = "unspecified"
    follow_up = None if match else "请补充血糖数值和测量场景，例如“空腹血糖 5.6”。"
    return _result("blood_glucose", payload, 0.9 if match else 0.55, follow_up=follow_up)


def _parse_body(text: str) -> ParsedCheckin | None:
    markers = ("体重", "体脂", "腰围", "BMI", "bmi", "骨骼肌", "肌肉量")
    if not any(marker in text for marker in markers):
        return None
    patterns = {
        "weight_kg": r"体重\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)\s*(kg|公斤|斤)?",
        "body_fat_pct": r"体脂(?:率)?\s*[:：]?\s*(\d{1,2}(?:\.\d+)?)\s*%?",
        "waist_cm": r"腰围\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)\s*(?:cm|厘米)?",
        "bmi": r"(?:BMI|bmi)\s*[:：]?\s*(\d{1,2}(?:\.\d+)?)",
        "skeletal_muscle_kg": r"骨骼肌(?:量)?\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*(?:kg|公斤)?",
        "muscle_mass_kg": r"肌肉量\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*(?:kg|公斤)?",
    }
    payload: dict[str, Any] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        value = float(match.group(1))
        if key == "weight_kg" and match.lastindex and match.group(2) == "斤":
            value = round(value / 2, 2)
        payload[key] = value
    follow_up = None if payload else "请补充具体数值和单位。"
    return _result("body", payload, 0.9 if payload else 0.5, follow_up=follow_up)


def _parse_sleep(text: str) -> ParsedCheckin | None:
    if not any(word in text for word in ("睡了", "睡眠", "失眠", "入睡", "醒了", "起床")):
        return None
    duration = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?小时", text)
    payload: dict[str, Any] = {}
    if duration:
        payload["duration_hours"] = float(duration.group(1))
    quality = next(
        (label for marker, label in (("很好", "good"), ("不错", "good"), ("一般", "fair"), ("很差", "poor"), ("失眠", "poor")) if marker in text),
        None,
    )
    if quality:
        payload["quality"] = quality
    follow_up = None if payload else "大约睡了多久？睡眠质量怎么样？"
    return _result("sleep", payload, 0.82 if payload else 0.55, follow_up=follow_up)


def _parse_cycle(text: str) -> ParsedCheckin | None:
    markers = ("来月经", "来例假", "经期", "月经第", "姨妈")
    if not any(marker in text for marker in markers):
        return None
    payload: dict[str, Any] = {}
    if any(marker in text for marker in ("来月经", "来例假", "姨妈来了")):
        payload["event"] = "period_start"
    day_match = re.search(r"(?:月经|经期|姨妈)第\s*(\d{1,2})\s*天", text)
    if day_match:
        payload["cycle_day"] = int(day_match.group(1))
    flow = next((label for marker, label in (("量大", "heavy"), ("量少", "light"), ("正常", "normal")) if marker in text), None)
    if flow:
        payload["flow"] = flow
    return _result("menstrual_cycle", payload, 0.85)


def _parse_symptom(text: str) -> ParsedCheckin | None:
    symptom_map = (
        ("胸痛", "chest_pain"),
        ("呼吸困难", "breathing_difficulty"),
        ("头痛", "headache"),
        ("肚子痛", "abdominal_pain"),
        ("腹痛", "abdominal_pain"),
        ("恶心", "nausea"),
        ("头晕", "dizziness"),
        ("心慌", "palpitations"),
        ("疼", "pain"),
        ("酸痛", "soreness"),
    )
    symptom = next(((marker, code) for marker, code in symptom_map if marker in text), None)
    if symptom is None:
        return None
    severity = re.search(r"(?:强度|程度|疼痛)?\s*(\d{1,2})\s*分", text)
    payload: dict[str, Any] = {"symptom": symptom[1], "label": symptom[0]}
    if severity:
        payload["severity"] = int(severity.group(1))
    urgent_markers = ("胸痛", "呼吸困难", "意识不清", "晕厥", "大量出血", "剧烈头痛")
    red_flags = [marker for marker in urgent_markers if marker in text]
    if red_flags:
        payload["red_flags"] = red_flags
    return _result("symptom", payload, 0.88, warnings=("urgent_symptom",) if red_flags else ())


def _parse_exercise(text: str) -> ParsedCheckin | None:
    step_match = re.search(r"(\d{2,6})\s*步", text)
    markers = ("跑步", "走了", "快走", "运动", "训练", "健身", "骑行", "骑车", "游泳", "拉伸", "瑜伽", "椭圆机", "练胸", "练背", "练腿", "练肩", "深蹲", "硬拉")
    if not step_match and not any(marker in text for marker in markers):
        return None
    activity_map = (
        ("跑步", "running"),
        ("快走", "brisk_walking"),
        ("骑行", "cycling"),
        ("骑车", "cycling"),
        ("游泳", "swimming"),
        ("椭圆机", "elliptical"),
        ("拉伸", "stretching"),
        ("瑜伽", "yoga"),
    )
    activity = next((value for marker, value in activity_map if marker in text), None)
    if activity is None:
        activity = "walking" if step_match or "走了" in text else "strength_training"
    payload: dict[str, Any] = {"activity": activity}
    if step_match:
        payload["steps"] = int(step_match.group(1))
    duration = _duration_minutes(text)
    if duration is not None:
        payload["duration_min"] = duration
    distance = re.search(r"(\d+(?:\.\d+)?)\s*(?:公里|km)", text, re.I)
    if distance:
        payload["distance_km"] = float(distance.group(1))
    calories = re.search(r"(?:消耗|燃烧)\s*(\d{2,4})\s*(?:千卡|kcal|卡)", text, re.I)
    if calories:
        payload["calories_kcal"] = int(calories.group(1))
    heart_rate = re.search(r"(?:平均)?心率\s*[:：]?\s*(\d{2,3})", text)
    if heart_rate:
        payload["avg_heart_rate_bpm"] = int(heart_rate.group(1))
    body_parts = [label for marker, label in (("胸", "chest"), ("背", "back"), ("腿", "legs"), ("臀", "glutes"), ("肩", "shoulders"), ("核心", "core"), ("腹", "core")) if marker in text]
    if body_parts:
        payload["body_parts"] = list(dict.fromkeys(body_parts))
    return _result("exercise", payload, 0.9 if len(payload) > 1 else 0.72)


def _parse_meal(text: str) -> ParsedCheckin | None:
    food_markers = ("吃了", "喝了", "早餐", "早饭", "午餐", "午饭", "晚餐", "晚饭", "加餐", "夜宵")
    if not any(marker in text for marker in food_markers):
        return None
    meal_aliases = (
        (("早餐", "早饭", "早上"), "breakfast"),
        (("午餐", "午饭", "中午"), "lunch"),
        (("晚餐", "晚饭", "晚上"), "dinner"),
        (("加餐", "夜宵"), "snack"),
    )
    meal_type = next((value for markers, value in meal_aliases if any(marker in text for marker in markers)), None)
    content_match = re.search(r"(?:吃了|喝了|吃|喝)\s*(.+)", text)
    content = content_match.group(1) if content_match else text
    content = re.split(r"(?:，|,)?\s*(?:感觉|心情|然后|之后)", content, maxsplit=1)[0]
    foods = []
    for item in re.split(r"[、，,和+]", content):
        cleaned = item.strip(" 。.!！")
        cleaned = re.sub(r"^(?:今天|昨天|早餐|早饭|午餐|午饭|晚餐|晚饭|加餐|夜宵)", "", cleaned).strip()
        if cleaned and cleaned not in {"吃了", "喝了", "吃", "喝"}:
            foods.append(cleaned)
    payload: dict[str, Any] = {"foods": foods}
    if meal_type:
        payload["meal_type"] = meal_type
    calories = re.search(r"(\d{2,4})\s*(?:千卡|kcal|大卡)", text, re.I)
    if calories:
        payload["calories_kcal"] = int(calories.group(1))
    protein = re.search(r"蛋白质?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*g", text, re.I)
    if protein:
        payload["protein_g"] = float(protein.group(1))
    follow_up = None if meal_type else "这是早餐、午餐、晚餐还是加餐？不补也可以，日报会标记为餐次未知。"
    confidence = 0.88 if meal_type and foods else 0.7
    return _result("meal", payload, confidence, follow_up=follow_up)


def _parse_mood(text: str) -> ParsedCheckin | None:
    mood_map = (
        ("焦虑", "anxious"),
        ("低落", "low"),
        ("开心", "happy"),
        ("平静", "calm"),
        ("烦躁", "irritable"),
        ("压力大", "stressed"),
        ("很累", "fatigued"),
        ("疲劳", "fatigued"),
        ("精力充沛", "energetic"),
    )
    self_harm_markers = ("不想活", "自杀", "伤害自己")
    self_harm = any(marker in text for marker in self_harm_markers)
    mood = next(((marker, code) for marker, code in mood_map if marker in text), None)
    if mood is None and self_harm:
        mood = ("自伤风险", "self_harm_risk")
    if mood is None:
        return None
    intensity = re.search(r"(?:强度|程度)?\s*(\d{1,2})\s*分", text)
    payload: dict[str, Any] = {"mood": mood[1], "label": mood[0]}
    if intensity:
        payload["intensity"] = int(intensity.group(1))
    if self_harm:
        payload["red_flags"] = ["self_harm_risk"]
    return _result("mood", payload, 0.86, warnings=("urgent_mental_health",) if self_harm else ())


def _duration_minutes(text: str) -> int | None:
    total = 0
    matches = re.findall(r"(\d+(?:\.\d+)?|一|二|两|三)\s*(小时|个小时|分钟|min)", text, re.I)
    for value, unit in matches:
        number = {"一": 1.0, "二": 2.0, "两": 2.0, "三": 3.0}.get(value)
        if number is None:
            number = float(value)
        total += round(number * 60) if "小时" in unit else round(number)
    return total or None


def _looks_like_question_without_record(text: str) -> bool:
    question_markers = ("？", "?", "怎么", "如何", "应该", "能不能", "可以吗", "建议")
    if not any(marker in text for marker in question_markers):
        return False
    record_markers = (
        "吃了",
        "喝了",
        "走了",
        "跑了",
        "练了",
        "睡了",
        "测了",
        "来月经",
        "来例假",
        "感觉",
        "今天很",
        "昨天很",
    )
    has_numeric_measurement = bool(
        re.search(r"(?:血压|血糖|体重|体脂|腰围|心率)\D{0,5}\d", text)
    )
    return not has_numeric_measurement and not any(marker in text for marker in record_markers)
