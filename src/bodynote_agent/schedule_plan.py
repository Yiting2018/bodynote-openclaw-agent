from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from bodynote_agent.preferences import OnboardingService


WEEKDAY_CRON = {
    "Sunday": 0,
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6,
}


class SchedulePlanService:
    def __init__(self, database_path: Path, home: Path) -> None:
        self.onboarding = OnboardingService(database_path)
        self.home = home

    def plan(self) -> dict[str, Any]:
        settings = self.onboarding.status()
        schedule = settings["schedule"]
        timezone = settings["profile"]["timezone"]
        onboarding_ready = settings["onboarding_completed"]
        gap_command = [
            "bodynote-agent",
            "--home",
            str(self.home),
            "gap-check",
        ]
        gap_argv = _cron_command_argv(
            cron=_daily_cron(schedule["gap_check_time"]),
            name="BodyNote 查漏补缺",
            timezone=timezone,
            command=gap_command,
        )
        jobs = [
            {
                "id": "gap_check",
                "name": "BodyNote 查漏补缺",
                "schedule": _daily_cron(schedule["gap_check_time"]),
                "timezone": timezone,
                "ready": onboarding_ready,
                "blocker": None if onboarding_ready else "onboarding_incomplete",
                "execution": "command",
                "install_argv": gap_argv if onboarding_ready else None,
                "install_command": shlex.join(gap_argv) if onboarding_ready else None,
            },
            _report_job(
                "daily_report",
                "BodyNote 每日报告",
                _daily_cron(schedule["daily_report_time"]),
                timezone,
                report_type="daily",
                home=self.home,
                ready=onboarding_ready,
            ),
            _report_job(
                "weekly_report",
                "BodyNote 每周报告",
                _weekly_cron(
                    schedule["weekly_report_time"], schedule["weekly_report_day"]
                ),
                timezone,
                report_type="weekly",
                home=self.home,
                ready=onboarding_ready,
            ),
            _report_job(
                "monthly_report",
                "BodyNote 每月报告",
                _last_day_candidate_cron(schedule["monthly_report_time"]),
                timezone,
                report_type="monthly",
                home=self.home,
                ready=onboarding_ready,
                note="每月 28-31 日触发候选任务，报告命令需仅在当地月末实际生成。",
            ),
        ]
        return {
            "ok": True,
            "onboarding_completed": onboarding_ready,
            "requires_operator_admin": True,
            "mutates_openclaw": False,
            "delivery": {
                "mode": "announce",
                "channel": "last",
                "note": "安装前由 OpenClaw 预览并确认当前聊天路由。",
            },
            "channel_compatibility": {
                "feishu": "支持图片和文件；受 channels.feishu.mediaMaxMb 限制。",
                "qqbot_c2c_group": "支持本地图片和文件；大文件由 QQBot 分块上传。",
                "qqbot_guild": "仅支持文本和远程 URL 图片；本地 PNG/PDF 应降级为文字摘要。",
            },
            "jobs": jobs,
        }


def _cron_command_argv(
    *, cron: str, name: str, timezone: str, command: list[str]
) -> list[str]:
    return [
        "openclaw",
        "cron",
        "create",
        cron,
        "--name",
        name,
        "--tz",
        timezone,
        "--command-argv",
        json.dumps(command, ensure_ascii=False, separators=(",", ":")),
        "--announce",
        "--channel",
        "last",
    ]


def _report_job(
    job_id: str,
    name: str,
    cron: str,
    timezone: str,
    *,
    report_type: str,
    home: Path,
    ready: bool,
    note: str | None = None,
) -> dict[str, Any]:
    prompt = (
        "使用 BodyNote Skill 生成并交付本地健康报告。运行 "
        f"bodynote-agent --home {str(home)!r} report generate --type {report_type} "
        "--scheduled --delivery-dir .bodynote-delivery --json。若返回 skipped，最终只回复 NO_REPLY。否则先发送 summary，"
        "再使用 message 工具的结构化 filePath/path 媒体字段发送 attachments：优先 PNG，"
        "然后 PDF；只发送清单内文件，不发送数据库、原始记录目录或 manifest。"
    )
    argv = [
        "openclaw",
        "cron",
        "create",
        cron,
        prompt,
        "--name",
        name,
        "--tz",
        timezone,
        "--session",
        "isolated",
        "--announce",
        "--channel",
        "last",
    ]
    return {
        "id": job_id,
        "name": name,
        "schedule": cron,
        "timezone": timezone,
        "ready": ready,
        "blocker": None if ready else "onboarding_incomplete",
        "execution": "agent",
        "install_argv": argv if ready else None,
        "install_command": shlex.join(argv) if ready else None,
        "delivery_contract": {
            "summary_field": "summary",
            "attachment_field": "attachments",
            "structured_media_fields": ["filePath", "path"],
        },
        "note": note,
    }


def _daily_cron(value: str) -> str:
    hour, minute = value.split(":")
    return f"{int(minute)} {int(hour)} * * *"


def _weekly_cron(value: str, week_day: str) -> str:
    hour, minute = value.split(":")
    return f"{int(minute)} {int(hour)} * * {WEEKDAY_CRON[week_day]}"


def _last_day_candidate_cron(value: str) -> str:
    hour, minute = value.split(":")
    return f"{int(minute)} {int(hour)} 28-31 * *"
