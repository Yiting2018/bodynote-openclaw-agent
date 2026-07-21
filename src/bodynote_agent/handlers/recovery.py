from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import HandlerResult, result


def parse_sleep(text: str) -> HandlerResult | None:
    if not any(word in text for word in ("睡了", "睡眠", "失眠", "入睡", "醒了", "起床")):
        return None
    duration = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?小时", text)
    payload = {}
    if duration:
        payload["duration_hours"] = float(duration.group(1))
    quality = next((label for marker, label in (("很好", "good"), ("不错", "good"), ("一般", "fair"), ("很差", "poor"), ("失眠", "poor")) if marker in text), None)
    if quality:
        payload["quality"] = quality
    return result("sleep", payload, 0.82 if payload else 0.55,
                  required_fields=("duration_hours_or_quality",),
                  follow_up=None if payload else "大约睡了多久？睡眠质量怎么样？")


def parse_symptom(text: str) -> HandlerResult | None:
    symptom_map = (("胸痛", "chest_pain"), ("呼吸困难", "breathing_difficulty"), ("头痛", "headache"), ("肚子痛", "abdominal_pain"), ("腹痛", "abdominal_pain"), ("恶心", "nausea"), ("头晕", "dizziness"), ("心慌", "palpitations"), ("酸痛", "soreness"), ("疼", "pain"))
    symptom = next(((marker, code) for marker, code in symptom_map if marker in text), None)
    if symptom is None:
        return None
    severity = re.search(r"(?:强度|程度|疼痛)?\s*(\d{1,2})\s*分", text)
    payload = {"symptom": symptom[1], "label": symptom[0]}
    if severity:
        payload["severity"] = int(severity.group(1))
    red_flags = [marker for marker in ("胸痛", "呼吸困难", "意识不清", "晕厥", "大量出血", "剧烈头痛") if marker in text]
    if red_flags:
        payload["red_flags"] = red_flags
    return result("symptom", payload, 0.88, required_fields=("symptom",),
                  warnings=("urgent_symptom",) if red_flags else ())


def parse_mood(text: str) -> HandlerResult | None:
    mood_map = (("焦虑", "anxious"), ("低落", "low"), ("开心", "happy"), ("平静", "calm"), ("烦躁", "irritable"), ("压力大", "stressed"), ("很累", "fatigued"), ("疲劳", "fatigued"), ("精力充沛", "energetic"))
    self_harm = any(marker in text for marker in ("不想活", "自杀", "伤害自己"))
    mood = next(((marker, code) for marker, code in mood_map if marker in text), None)
    if mood is None and self_harm:
        mood = ("自伤风险", "self_harm_risk")
    if mood is None:
        return None
    intensity = re.search(r"(?:强度|程度)?\s*(\d{1,2})\s*分", text)
    payload = {"mood": mood[1], "label": mood[0]}
    if intensity:
        payload["intensity"] = int(intensity.group(1))
    if self_harm:
        payload["red_flags"] = ["self_harm_risk"]
    return result("mood", payload, 0.86, required_fields=("mood",),
                  warnings=("urgent_mental_health",) if self_harm else ())
