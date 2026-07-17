from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def infer_occurred_at(
    text: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> tuple[str, str]:
    timezone = ZoneInfo(timezone_name)
    base = now.astimezone(timezone) if now else datetime.now(timezone)
    normalized = text.strip()

    explicit_date = re.search(
        r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?",
        normalized,
    )
    source = "recorded_at"
    if explicit_date:
        day = datetime(
            int(explicit_date.group(1)),
            int(explicit_date.group(2)),
            int(explicit_date.group(3)),
            tzinfo=timezone,
        ).date()
        source = "explicit_date"
    else:
        day = base.date()
        relative_days = (
            (("大前天", "三天前", "3天前"), 3),
            (("前天",), 2),
            (("昨天", "昨晚", "昨夜"), 1),
        )
        for markers, delta in relative_days:
            if any(marker in normalized for marker in markers):
                day -= timedelta(days=delta)
                source = "relative_time"
                break
        if source == "recorded_at" and any(
            marker in normalized for marker in ("今天", "今早", "今晚", "刚刚", "刚才")
        ):
            source = "relative_time"

    hour, minute, clock_found = _infer_clock(normalized, fallback=(base.hour, base.minute))
    if clock_found and source == "recorded_at":
        source = "explicit_time"
    occurred = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone)
    return occurred.isoformat(), source


def _infer_clock(text: str, *, fallback: tuple[int, int]) -> tuple[int, int, bool]:
    explicit = re.search(r"(?<!\d)([01]?\d|2[0-3])(?:[:：点时])\s*([0-5]?\d)?(?:分)?", text)
    if explicit:
        hour = int(explicit.group(1))
        minute = int(explicit.group(2) or 0)
        if any(
            word in text
            for word in ("下午", "晚上", "今晚", "晚饭", "晚餐", "夜宵", "昨晚")
        ) and hour < 12:
            hour += 12
        return hour, minute, True

    phrase_times = (
        (("早餐", "早饭", "今早", "早上"), (8, 0)),
        (("上午",), (10, 0)),
        (("午餐", "午饭", "中午"), (12, 30)),
        (("下午", "加餐"), (15, 30)),
        (("晚餐", "晚饭", "晚上", "今晚", "昨晚", "昨夜"), (19, 0)),
        (("夜宵",), (22, 0)),
    )
    for markers, clock in phrase_times:
        if any(marker in text for marker in markers):
            return clock[0], clock[1], True
    return fallback[0], fallback[1], False
