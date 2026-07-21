from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import HandlerResult, result


def parse_blood_pressure(text: str) -> HandlerResult | None:
    match = re.search(r"(?<!\d)([1-2]?\d{2})\s*/\s*(\d{2,3})(?!\d)", text)
    if "血压" not in text and not match:
        return None
    payload = {}
    if match:
        payload.update(systolic=int(match.group(1)), diastolic=int(match.group(2)))
    heart_rate = re.search(r"(?:心率|脉搏)\s*[:：]?\s*(\d{2,3})", text)
    if heart_rate:
        payload["heart_rate_bpm"] = int(heart_rate.group(1))
    return result("blood_pressure", payload, 0.96 if match else 0.55,
                  required_fields=("systolic", "diastolic"),
                  follow_up=None if match else "请补充收缩压/舒张压，例如 132/86。")


def parse_glucose(text: str) -> HandlerResult | None:
    if "血糖" not in text and "mmol" not in text.lower() and "毫摩尔" not in text:
        return None
    match = re.search(r"(?:血糖)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:mmol(?:/L)?|毫摩尔)?", text, re.I)
    payload = {}
    if match:
        payload["glucose_mmol_l"] = float(match.group(1))
    payload["context"] = "fasting" if "空腹" in text else "postprandial" if "餐后" in text or "饭后" in text else "unspecified"
    return result("blood_glucose", payload, 0.9 if match else 0.55,
                  required_fields=("glucose_mmol_l",),
                  follow_up=None if match else "请补充血糖数值和测量场景，例如“空腹血糖 5.6”。")


def parse_body(text: str) -> HandlerResult | None:
    if not any(marker in text for marker in ("体重", "体脂", "腰围", "BMI", "bmi", "骨骼肌", "肌肉量")):
        return None
    patterns = {
        "weight_kg": r"体重\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)\s*(kg|公斤|斤)?",
        "body_fat_pct": r"体脂(?:率)?\s*[:：]?\s*(\d{1,2}(?:\.\d+)?)\s*%?",
        "waist_cm": r"腰围\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)\s*(?:cm|厘米)?",
        "bmi": r"(?:BMI|bmi)\s*[:：]?\s*(\d{1,2}(?:\.\d+)?)",
        "skeletal_muscle_kg": r"骨骼肌(?:量)?\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*(?:kg|公斤)?",
        "muscle_mass_kg": r"肌肉量\s*[:：]?\s*(\d{1,3}(?:\.\d+)?)\s*(?:kg|公斤)?",
    }
    payload = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            value = float(match.group(1))
            payload[key] = round(value / 2, 2) if key == "weight_kg" and match.lastindex and match.group(2) == "斤" else value
    return result("body", payload, 0.9 if payload else 0.5,
                  required_fields=("one_body_metric",),
                  follow_up=None if payload else "请补充具体数值和单位。")
