from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bodynote_agent.database import connect, new_id


DEFAULT_REQUIRED_DAILY_FIELDS = ("movement", "nutrition", "body", "recovery")
DAILY_FIELD_EVENT_TYPES = {
    "movement": ("exercise",),
    "nutrition": ("meal",),
    "body": ("body",),
    "recovery": ("sleep", "mood"),
    "blood_pressure": ("blood_pressure",),
    "blood_glucose": ("blood_glucose",),
}
DAILY_FIELD_LABELS = {
    "movement": "活动",
    "nutrition": "饮食",
    "body": "身体数据",
    "recovery": "睡眠或感受",
    "blood_pressure": "血压",
    "blood_glucose": "血糖",
}
DAILY_FIELD_EXAMPLES = {
    "movement": "例如走了 8000 步或训练 30 分钟",
    "nutrition": "例如午饭吃了什么",
    "body": "例如今天体重 62.5 kg",
    "recovery": "例如睡了 7 小时或今天有点累",
    "blood_pressure": "例如血压 120/80",
    "blood_glucose": "例如空腹血糖 5.2",
}
ALLOWED_REPORT_FORMATS = ("html", "png", "pdf", "json")
WEEK_DAYS = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class OnboardingService:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def status(self) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            profile = connection.execute(
                "SELECT * FROM profile WHERE id = 'owner'"
            ).fetchone()
            schedule = connection.execute(
                "SELECT * FROM schedule_preferences WHERE profile_id = 'owner'"
            ).fetchone()
        if profile is None or schedule is None:
            raise RuntimeError("BodyNote owner profile is missing. Run init again.")

        primary_goal = profile["primary_goal"] or ""
        missing = [] if primary_goal.strip() else ["primary_goal"]
        return {
            "ok": True,
            "onboarding_completed": bool(profile["onboarding_completed"]),
            "onboarding_completed_at": profile["onboarding_completed_at"],
            "missing_setup_fields": missing,
            "profile": {
                "display_name": profile["display_name"],
                "timezone": profile["timezone"],
                "primary_goal": profile["primary_goal"],
                "details": json.loads(profile["profile_json"] or "{}"),
            },
            "schedule": {
                "gap_check_time": schedule["gap_check_time"],
                "daily_report_time": schedule["daily_report_time"],
                "weekly_report_day": schedule["weekly_report_day"],
                "weekly_report_time": schedule["weekly_report_time"],
                "monthly_report_policy": schedule["monthly_report_policy"],
                "monthly_report_time": schedule["monthly_report_time"],
                "required_daily_fields": json.loads(
                    schedule["required_daily_fields_json"]
                ),
                "not_applicable_daily_fields": json.loads(
                    schedule["not_applicable_daily_fields_json"]
                ),
            },
            "report_formats": json.loads(schedule["output_formats_json"]),
        }

    def configure(self, data: dict[str, Any]) -> dict[str, Any]:
        current = self.status()
        normalized = _normalize_configuration(data, current)
        completed = bool(normalized["primary_goal"].strip())

        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE profile
                    SET display_name = ?, timezone = ?, primary_goal = ?,
                        profile_json = ?, onboarding_completed = ?,
                        onboarding_completed_at = CASE
                            WHEN ? = 1 THEN COALESCE(onboarding_completed_at, CURRENT_TIMESTAMP)
                            ELSE NULL
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 'owner'
                    """,
                    (
                        normalized["display_name"],
                        normalized["timezone"],
                        normalized["primary_goal"] or None,
                        _json(normalized["profile_details"]),
                        1 if completed else 0,
                        1 if completed else 0,
                    ),
                )
                schedule = normalized["schedule"]
                connection.execute(
                    """
                    UPDATE schedule_preferences
                    SET gap_check_time = ?, daily_report_time = ?,
                        weekly_report_day = ?, weekly_report_time = ?,
                        monthly_report_policy = ?, monthly_report_time = ?,
                        output_formats_json = ?, required_daily_fields_json = ?,
                        not_applicable_daily_fields_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner'
                    """,
                    (
                        schedule["gap_check_time"],
                        schedule["daily_report_time"],
                        schedule["weekly_report_day"],
                        schedule["weekly_report_time"],
                        schedule["monthly_report_policy"],
                        schedule["monthly_report_time"],
                        _json(normalized["report_formats"]),
                        _json(schedule["required_daily_fields"]),
                        _json(schedule["not_applicable_daily_fields"]),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO audit_log (
                        id, profile_id, action, target_type, target_id,
                        data_types_json, details_json, success
                    ) VALUES (?, 'owner', 'onboarding_configure', 'profile', 'owner',
                              '["profile","schedule_preferences"]', ?, 1)
                    """,
                    (
                        new_id("audit"),
                        _json(
                            {
                                "onboarding_completed": completed,
                                "timezone": normalized["timezone"],
                                "required_daily_fields": schedule[
                                    "required_daily_fields"
                                ],
                                "not_applicable_daily_fields": schedule[
                                    "not_applicable_daily_fields"
                                ],
                            }
                        ),
                    ),
                )

        result = self.status()
        result["configured"] = True
        return result


def local_date(timezone_name: str, now: datetime | None = None) -> str:
    zone = ZoneInfo(timezone_name)
    value = now or datetime.now(zone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    return value.astimezone(zone).date().isoformat()


def _normalize_configuration(
    data: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    allowed = {
        "display_name",
        "timezone",
        "primary_goal",
        "profile",
        "schedule",
        "reports",
        "report_formats",
        "required_daily_fields",
        "not_applicable_daily_fields",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"不支持的首次设置字段：{', '.join(unknown)}。")

    profile_data = data.get("profile", current["profile"]["details"])
    if not isinstance(profile_data, dict):
        raise ValueError("profile 必须是 JSON object。")
    profile_data = _validate_profile_details(profile_data)
    timezone_name = str(data.get("timezone", current["profile"]["timezone"])).strip()
    _validate_timezone(timezone_name)

    schedule_input = data.get("schedule", {})
    if not isinstance(schedule_input, dict):
        raise ValueError("schedule 必须是 JSON object。")
    allowed_schedule = {
        "gap_check_time",
        "daily_report_time",
        "weekly_report_day",
        "weekly_report_time",
        "monthly_report_policy",
        "monthly_report_time",
        "required_daily_fields",
        "not_applicable_daily_fields",
    }
    unknown_schedule = sorted(set(schedule_input) - allowed_schedule)
    if unknown_schedule:
        raise ValueError(f"不支持的 schedule 字段：{', '.join(unknown_schedule)}。")

    schedule = dict(current["schedule"])
    schedule.update(schedule_input)
    if "required_daily_fields" in data:
        schedule["required_daily_fields"] = data["required_daily_fields"]
    if "not_applicable_daily_fields" in data:
        schedule["not_applicable_daily_fields"] = data[
            "not_applicable_daily_fields"
        ]
    for field in (
        "gap_check_time",
        "daily_report_time",
        "weekly_report_time",
        "monthly_report_time",
    ):
        schedule[field] = _validate_time(str(schedule[field]), field)
    schedule["weekly_report_day"] = _validate_week_day(
        str(schedule["weekly_report_day"])
    )
    if schedule["monthly_report_policy"] != "last_day":
        raise ValueError("monthly_report_policy 当前仅支持 last_day。")
    schedule["required_daily_fields"] = _validate_required_fields(
        schedule["required_daily_fields"], field="required_daily_fields", allow_empty=False
    )
    schedule["not_applicable_daily_fields"] = _validate_required_fields(
        schedule["not_applicable_daily_fields"],
        field="not_applicable_daily_fields",
        allow_empty=True,
    )
    overlap = set(schedule["required_daily_fields"]).intersection(
        schedule["not_applicable_daily_fields"]
    )
    if overlap:
        raise ValueError(
            "每日必填项和不适用项不能重叠：" + ", ".join(sorted(overlap)) + "。"
        )

    report_formats: Any = data.get("report_formats", current["report_formats"])
    reports = data.get("reports")
    if reports is not None:
        if not isinstance(reports, dict):
            raise ValueError("reports 必须是 JSON object。")
        unknown_reports = sorted(set(reports) - {"formats"})
        if unknown_reports:
            raise ValueError(f"不支持的 reports 字段：{', '.join(unknown_reports)}。")
        report_formats = reports.get("formats", report_formats)

    return {
        "display_name": str(
            data.get("display_name", current["profile"]["display_name"])
        ).strip(),
        "timezone": timezone_name,
        "primary_goal": str(
            data.get("primary_goal", current["profile"]["primary_goal"] or "")
        ).strip(),
        "profile_details": profile_data,
        "schedule": schedule,
        "report_formats": _validate_report_formats(report_formats),
    }


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"未知的 IANA 时区：{value}。") from None


def _validate_profile_details(value: dict[str, Any]) -> dict[str, Any]:
    details = dict(value)
    if "birth_date" in details:
        try:
            parsed = date.fromisoformat(str(details["birth_date"]))
        except ValueError:
            raise ValueError("profile.birth_date 必须是 YYYY-MM-DD。") from None
        if parsed >= date.today() or parsed.year < 1900:
            raise ValueError("profile.birth_date 超出合理范围。")
        details["birth_date"] = parsed.isoformat()
    if "height_cm" in details:
        height = details["height_cm"]
        if isinstance(height, bool) or not isinstance(height, (int, float)) or not 80 <= height <= 250:
            raise ValueError("profile.height_cm 必须是 80-250 之间的数值。")
    if "daily_calorie_target_kcal" in details:
        calories = details["daily_calorie_target_kcal"]
        if isinstance(calories, bool) or not isinstance(calories, (int, float)) or not 500 <= calories <= 10000:
            raise ValueError("profile.daily_calorie_target_kcal 必须是 500-10000 之间的数值。")
    if "daily_protein_target_g" in details:
        protein = details["daily_protein_target_g"]
        if isinstance(protein, bool) or not isinstance(protein, (int, float)) or not 10 <= protein <= 500:
            raise ValueError("profile.daily_protein_target_g 必须是 10-500 之间的数值。")
    if "cycle_tracking_enabled" in details and not isinstance(
        details["cycle_tracking_enabled"], bool
    ):
        raise ValueError("profile.cycle_tracking_enabled 必须是布尔值。")
    if "cycle_reminder_days_before" in details:
        days = details["cycle_reminder_days_before"]
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 7:
            raise ValueError("profile.cycle_reminder_days_before 必须是 1-7 的整数。")
    return details


def _validate_time(value: str, field: str) -> str:
    if not TIME_PATTERN.fullmatch(value):
        raise ValueError(f"{field} 必须使用 24 小时制 HH:MM。")
    return value


def _validate_week_day(value: str) -> str:
    normalized = WEEK_DAYS.get(value.strip().lower())
    if normalized is None:
        raise ValueError("weekly_report_day 必须是 Monday 到 Sunday。")
    return normalized


def _validate_required_fields(
    value: Any, *, field: str, allow_empty: bool
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        requirement = "数组" if allow_empty else "非空数组"
        raise ValueError(f"{field} 必须是{requirement}。")
    normalized = list(dict.fromkeys(str(item) for item in value))
    invalid = sorted(set(normalized) - set(DAILY_FIELD_EVENT_TYPES))
    if invalid:
        raise ValueError(f"{field} 包含不支持的项目：{', '.join(invalid)}。")
    return normalized


def _validate_report_formats(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("报告格式必须是非空数组。")
    normalized = list(dict.fromkeys(str(item).lower() for item in value))
    invalid = sorted(set(normalized) - set(ALLOWED_REPORT_FORMATS))
    if invalid:
        raise ValueError(f"不支持的报告格式：{', '.join(invalid)}。")
    return normalized


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
