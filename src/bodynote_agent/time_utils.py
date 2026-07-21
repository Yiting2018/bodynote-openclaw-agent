from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def infer_occurred_at(
    text: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    event_type: str | None = None,
) -> tuple[str, str]:
    timezone = ZoneInfo(timezone_name)
    base = now.astimezone(timezone) if now else datetime.now(timezone)
    normalized = text.strip()

    explicit_date = re.search(
        r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?",
        normalized,
    )
    explicit_clock = _explicit_clock_match(normalized)

    relative = None if explicit_date or explicit_clock else _relative_duration(normalized)
    if relative is not None:
        return (base - relative).replace(second=0, microsecond=0).isoformat(), "relative_duration"

    # A completed overnight sleep belongs to the day the user woke up.  When no
    # wake time is known we store midnight as a date anchor and render it without
    # a fabricated clock time.
    if event_type == "sleep" and not (explicit_date or explicit_clock) and _is_overnight_sleep(normalized):
        wake_day = base.date()
        if any(marker in normalized for marker in ("前晚", "前天晚上", "前天夜里")):
            wake_day -= timedelta(days=1)
        occurred = datetime(
            wake_day.year, wake_day.month, wake_day.day, tzinfo=timezone
        )
        return occurred.isoformat(), "sleep_wake_date"

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

    hour, minute, clock_found = _infer_clock(
        normalized,
        fallback=(base.hour, base.minute),
        infer_meal_markers=day != base.date(),
    )
    if any(marker in normalized for marker in ("今天很早", "一大早", "很早的时候")):
        source = "fuzzy_time"
    elif clock_found and source == "recorded_at":
        source = "explicit_time"
    occurred = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone)
    return occurred.isoformat(), source


def _relative_duration(text: str) -> timedelta | None:
    half_hour = re.search(r"(?:半个?|0\.5)\s*小时前", text)
    if half_hour:
        return timedelta(minutes=30)
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?小时前", text)
    if hours:
        return timedelta(hours=float(hours.group(1)))
    minutes = re.search(r"(\d{1,3})\s*分钟前", text)
    if minutes:
        return timedelta(minutes=int(minutes.group(1)))
    return None


def _is_overnight_sleep(text: str) -> bool:
    if any(marker in text for marker in ("午睡", "小睡", "打盹")):
        return False
    return any(
        marker in text
        for marker in (
            "昨晚",
            "昨夜",
            "昨天晚上",
            "前晚",
            "前天晚上",
            "今天睡了",
            "睡眠",
            "起床",
        )
    )


def _infer_clock(
    text: str,
    *,
    fallback: tuple[int, int],
    infer_meal_markers: bool,
) -> tuple[int, int, bool]:
    explicit = _explicit_clock_match(text)
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
        (("今天很早", "一大早", "很早的时候"), (6, 30)),
        (("今早", "早上"), (8, 0)),
        (("上午",), (10, 0)),
        (("中午",), (12, 30)),
        (("下午",), (15, 30)),
        (("晚上", "今晚", "昨晚", "昨夜"), (19, 0)),
    )
    for markers, clock in phrase_times:
        if any(marker in text for marker in markers):
            return clock[0], clock[1], True
    if infer_meal_markers:
        meal_times = (
            (("早餐", "早饭"), (8, 0)),
            (("午餐", "午饭"), (12, 30)),
            (("加餐",), (15, 30)),
            (("晚餐", "晚饭"), (19, 0)),
            (("夜宵",), (22, 0)),
        )
        for markers, clock in meal_times:
            if any(marker in text for marker in markers):
                return clock[0], clock[1], True
    return fallback[0], fallback[1], False


def _explicit_clock_match(text: str) -> re.Match[str] | None:
    return re.search(
        r"(?<!\d)([01]?\d|2[0-3])\s*(?:[:：点]|时(?!\s*前))\s*([0-5]?\d)?(?:分)?",
        text,
    )
