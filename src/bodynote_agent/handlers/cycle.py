from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import HandlerResult, result


def parse_cycle(text: str) -> HandlerResult | None:
    if not any(marker in text for marker in ("来月经", "来例假", "经期", "月经第", "姨妈")):
        return None
    payload = {}
    if any(marker in text for marker in ("来月经", "来例假", "姨妈来了")):
        payload["event"] = "period_start"
    day_match = re.search(r"(?:月经|经期|姨妈)第\s*(\d{1,2})\s*天", text)
    if day_match:
        payload["cycle_day"] = int(day_match.group(1))
    flow = next((label for marker, label in (("量大", "heavy"), ("量少", "light"), ("正常", "normal")) if marker in text), None)
    if flow:
        payload["flow"] = flow
    return result("menstrual_cycle", payload, 0.85, required_fields=())
