from __future__ import annotations

import hashlib
import html as stdlib_html
import json
import os
import shutil
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bodynote_agent.analytics import HealthAnalysisService
from bodynote_agent.dashboard import dashboard_snapshot, render_dashboard_html
from bodynote_agent.database import connect, new_id
from bodynote_agent.food_library import FoodLibraryService
from bodynote_agent.html_report import (
    EVENT_LABELS,
    PALETTE,
    event_summary,
    event_time_label,
    render_report_html,
)
from bodynote_agent.preferences import ALLOWED_REPORT_FORMATS, OnboardingService, local_date
from bodynote_agent.trends import TrendAnalysisService


MIME_TYPES = {
    "html": "text/html",
    "png": "image/png",
    "pdf": "application/pdf",
    "json": "application/json",
}


class ReportService:
    def __init__(self, database_path: Path, reports_root: Path) -> None:
        self.database_path = database_path
        self.reports_root = reports_root
        self.analytics = HealthAnalysisService(database_path)
        self.onboarding = OnboardingService(database_path)

    def generate(
        self,
        report_type: str,
        period_key: str | None = None,
        *,
        formats: list[str] | None = None,
        scheduled: bool = False,
        now: datetime | None = None,
        delivery_dir: Path | None = None,
    ) -> dict[str, Any]:
        if report_type not in {"daily", "weekly", "monthly"}:
            raise ValueError("report_type 必须是 daily、weekly 或 monthly。")
        settings = self.onboarding.status()
        if scheduled and report_type == "monthly" and not _is_local_month_end(
            settings["profile"]["timezone"], now
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "not_local_month_end",
                "summary": "NO_REPLY",
                "attachments": [],
            }
        selected = _normalize_formats(formats or settings["report_formats"])
        model = self.analytics.analyze(report_type, period_key, now=now)
        if not model.get("ok"):
            return model
        reference_day = _dashboard_reference_day(
            model, settings["profile"]["timezone"], now
        )
        model = dict(model)
        trend_bundle = TrendAnalysisService(self.database_path).analyze(
            reference_day,
            timezone_name=settings["profile"]["timezone"],
            profile=settings["profile"],
        )
        model["trend_analysis"] = trend_bundle["periods"][report_type]
        model["cycle_support"] = trend_bundle["cycle"]
        model["analysis_references"] = trend_bundle["references"]
        key = str(model["period_key"])
        events = self.analytics.events.list_period(
            start_date=model["period"]["start"],
            end_date=model["period"]["end"],
            timezone_name=model["timezone"],
        )
        output_dir = self.reports_root / report_type / key
        input_hash = _hash_json(
            {"model": model, "events": events, "formats": selected, "renderer": 12}
        )
        duplicate = self._existing_result(report_type, key, input_hash)
        if duplicate:
            duplicate["attachments"] = _delivery_attachments(
                duplicate.get("artifacts", {})
            )
            duplicate["delivery_staged"] = False
            if delivery_dir:
                duplicate["attachments"] = _stage_attachments(
                    duplicate["attachments"], delivery_dir, report_type, key
                )
                duplicate["delivery_staged"] = True
            duplicate["duplicate"] = True
            return duplicate

        for directory in (self.reports_root, output_dir.parent, output_dir):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
        self._mark_running(report_type, key, input_hash)
        try:
            artifacts: dict[str, dict[str, Any]] = {}
            data_path = output_dir / "report.json"
            _write_text(data_path, json.dumps(model, ensure_ascii=False, indent=2))
            artifacts["json"] = _artifact(data_path, "json")

            if "html" in selected:
                html_path = output_dir / "report.html"
                _write_text(html_path, render_report_html(model, events=events))
                artifacts["html"] = _artifact(html_path, "html")
            if "png" in selected:
                png_path = output_dir / "report.png"
                for legacy_page in output_dir.glob("report-[0-9]*.png"):
                    legacy_page.unlink(missing_ok=True)
                png_paths = _render_png(model, png_path, events=events)
                for index, rendered_path in enumerate(png_paths, start=1):
                    artifact_key = "png" if index == 1 else f"png_{index}"
                    artifacts[artifact_key] = _artifact(rendered_path, "png")
            if "pdf" in selected:
                pdf_path = output_dir / "report.pdf"
                _render_pdf(model, pdf_path)
                artifacts["pdf"] = _artifact(pdf_path, "pdf")

            dashboard_path = self.build_dashboard(model)
            summary = _summary_text(model)
            attachments = _delivery_attachments(artifacts)
            if delivery_dir:
                attachments = _stage_attachments(
                    attachments, delivery_dir, report_type, key
                )
            manifest = {
                "report_type": report_type,
                "period_key": key,
                "input_hash": input_hash,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "artifacts": artifacts,
                "attachments": attachments,
                "delivery_staged": delivery_dir is not None,
                "dashboard": str(dashboard_path),
            }
            manifest_path = output_dir / "manifest.json"
            _write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
            self._mark_complete(report_type, key, input_hash, manifest, model["confidence"])
            return {"ok": True, "duplicate": False, **manifest}
        except Exception as error:
            self._mark_error(report_type, key, input_hash, str(error))
            raise

    def build_dashboard(self, model: dict[str, Any] | None = None) -> Path:
        if model is None:
            model = self.analytics.analyze("daily")
            if not model.get("ok"):
                raise ValueError(str(model.get("error")))
        dashboard_dir = self.reports_root / "dashboard"
        dashboard_dir.mkdir(parents=True, exist_ok=True)
        dashboard_dir.chmod(0o700)
        dashboard_path = dashboard_dir / "index.html"
        archive = []
        for item in self.list_reports(limit=12)["reports"]:
            html_artifact = item["artifacts"].get("html")
            if not html_artifact:
                continue
            target = Path(html_artifact["path"])
            archive.append(
                {
                    "label": {"daily": "日报", "weekly": "周报", "monthly": "月报"}[
                        item["report_type"]
                    ],
                    "period": item["period_key"],
                    "href": os.path.relpath(target, dashboard_dir),
                }
            )
        profile = self.onboarding.status()["profile"]
        selected_day = _dashboard_reference_day(
            model, profile["timezone"], None
        )
        daily = (
            model
            if model.get("period_type") == "daily" and model.get("period_key") == selected_day
            else self.analytics.analyze("daily", selected_day)
        )
        weekly = self.analytics.analyze("weekly", selected_day)
        monthly = self.analytics.analyze("monthly", selected_day[:7])
        events = self.analytics.events.list(limit=500)
        trends = TrendAnalysisService(self.database_path).analyze(
            selected_day,
            timezone_name=profile["timezone"],
            profile=profile,
        )
        library = FoodLibraryService(self.database_path)
        snapshot = dashboard_snapshot(
            daily=daily,
            weekly=weekly,
            monthly=monthly,
            events=events,
            archive=archive,
            profile=profile,
            trends=trends,
            food_library={
                "foods": library.list_foods()["foods"],
                "templates": library.list_templates()["templates"],
            },
        )
        _write_text(dashboard_path, render_dashboard_html(snapshot))
        return dashboard_path

    def list_reports(self, *, limit: int = 50) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT report_type, period_key, status, confidence,
                       artifact_manifest_json, generated_at, updated_at
                FROM report_runs
                WHERE profile_id = 'owner'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        reports = []
        for row in rows:
            manifest = json.loads(row["artifact_manifest_json"] or "{}")
            reports.append(
                {
                    "report_type": row["report_type"],
                    "period_key": row["period_key"],
                    "status": row["status"],
                    "confidence": row["confidence"],
                    "artifacts": manifest.get("artifacts", {}),
                    "attachments": manifest.get("attachments", []),
                    "generated_at": row["generated_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return {"ok": True, "count": len(reports), "reports": reports}

    def _existing_result(
        self, report_type: str, period_key: str, input_hash: str
    ) -> dict[str, Any] | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT status, input_hash, artifact_manifest_json
                FROM report_runs
                WHERE profile_id = 'owner' AND report_type = ? AND period_key = ?
                """,
                (report_type, period_key),
            ).fetchone()
        if row is None or row["status"] != "complete" or row["input_hash"] != input_hash:
            return None
        manifest = json.loads(row["artifact_manifest_json"] or "{}")
        paths = [Path(item["path"]) for item in manifest.get("artifacts", {}).values()]
        if not paths or not all(path.exists() for path in paths):
            return None
        return {"ok": True, **manifest}

    def _mark_running(self, report_type: str, period_key: str, input_hash: str) -> None:
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO report_runs (
                        id, profile_id, report_type, period_key, status, input_hash
                    ) VALUES (?, 'owner', ?, ?, 'running', ?)
                    ON CONFLICT(profile_id, report_type, period_key) DO UPDATE SET
                        status = 'running', input_hash = excluded.input_hash,
                        error_message = NULL, updated_at = CURRENT_TIMESTAMP
                    """,
                    (new_id("report"), report_type, period_key, input_hash),
                )

    def _mark_complete(
        self,
        report_type: str,
        period_key: str,
        input_hash: str,
        manifest: dict[str, Any],
        confidence: float,
    ) -> None:
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE report_runs
                    SET status = 'complete', confidence = ?,
                        artifact_manifest_json = ?, input_hash = ?,
                        error_message = NULL, generated_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND report_type = ? AND period_key = ?
                    """,
                    (
                        confidence,
                        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                        input_hash,
                        report_type,
                        period_key,
                    ),
                )

    def _mark_error(
        self, report_type: str, period_key: str, input_hash: str, error: str
    ) -> None:
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE report_runs
                    SET status = 'error', input_hash = ?, error_message = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND report_type = ? AND period_key = ?
                    """,
                    (input_hash, error[:1000], report_type, period_key),
                )


def _normalize_formats(formats: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(str(item).lower() for item in formats))
    invalid = sorted(set(normalized) - set(ALLOWED_REPORT_FORMATS))
    if invalid:
        raise ValueError(f"不支持的报告格式：{', '.join(invalid)}。")
    return normalized


def _render_png(
    model: dict[str, Any], path: Path, *, events: list[dict[str, Any]] | None = None
) -> list[Path]:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("生成 PNG 需要 Pillow，请先安装项目依赖。") from error

    events = events or []
    if model["period_type"] == "daily":
        _render_daily_long_png(model, path, events=events)
        return [path]

    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), "#08090D")
    draw = ImageDraw.Draw(image)
    accent = PALETTE.get(model["status"], PALETTE["unknown"])
    ink = "#F6F7F9"
    muted = "#9298A5"
    paper = "#111318"
    paper_2 = "#181B22"
    line = "#2B3039"
    fonts = _load_pillow_fonts()
    events = events or []

    for row in range(0, 610, 4):
        ratio = row / 610
        base = (10, 12, 16)
        accent_rgb = tuple(int(accent[index : index + 2], 16) for index in (1, 3, 5))
        color = tuple(int(base[i] * ratio + accent_rgb[i] * (1 - ratio) * 0.18) for i in range(3))
        draw.rectangle((0, row, width, row + 4), fill=color)
    draw.rectangle((48, 45, 94, 91), outline=accent, width=3)
    draw.text((62, 52), "B", font=fonts["body"], fill=accent)
    draw.text((112, 48), "BodyNote", font=fonts["brand"], fill=ink)
    period_text = _period_text(model)
    period_width = draw.textlength(period_text, font=fonts["small"])
    draw.text((width - 48 - period_width, 55), period_text, font=fonts["small"], fill="#C4C8D0")
    kicker = {"daily": "TODAY SIGNAL", "weekly": "WEEKLY RHYTHM", "monthly": "MONTHLY CHANGE"}[model["period_type"]]
    draw.text((48, 142), kicker, font=fonts["small"], fill=accent)
    _draw_wrapped(draw, model["summary"]["headline"], (48, 188), 650, fonts["headline"], ink, 58, max_lines=3)
    insight_overview = " · ".join(
        str(item.get("title") or item.get("explanation") or "")
        for item in model.get("insights", [])
        if item.get("title") or item.get("explanation")
    ) or "数据正在形成你的个人健康脉络。"
    _draw_wrapped(draw, insight_overview, (48, 380), 630, fonts["small"], "#B1B6C0", 30, max_lines=3)

    score = model["health_score"]
    progress = (score if score is not None else round(model["confidence"] * 100)) * 3.6
    draw.ellipse((760, 158, 1012, 410), outline=line, width=22)
    draw.arc((760, 158, 1012, 410), start=-90, end=-90 + progress, fill=accent, width=22)
    score_text = str(score) if score is not None else "--"
    score_box = draw.textbbox((0, 0), score_text, font=fonts["score"])
    draw.text((886 - (score_box[2] - score_box[0]) / 2, 232), score_text, font=fonts["score"], fill=accent)
    draw.text((839, 335), "健康状态", font=fonts["small"], fill=muted)
    draw.text((760, 448), f"数据置信度  {round(model['confidence'] * 100)}%", font=fonts["small"], fill=muted)
    draw.rounded_rectangle((760, 486, 1012, 496), radius=5, fill=line)
    draw.rounded_rectangle((760, 486, 760 + int(252 * model["confidence"]), 496), radius=5, fill="#42D7E8")

    y = 642
    overview_title = {
        "daily": "今日关键指标",
        "weekly": "本周关键变化",
        "monthly": "本月关键变化",
    }[model["period_type"]]
    draw.text((48, y), overview_title, font=fonts["section"], fill=ink)
    y += 52
    metrics = _png_metrics(model, events)
    card_width = 237
    for index, (label, value, note) in enumerate(metrics[:4]):
        x = 38 + index * (card_width + 18)
        draw.rounded_rectangle((x, y, x + card_width, y + 172), radius=8, fill=paper, outline=line)
        draw.text((x + 18, y + 18), label, font=fonts["small"], fill=muted)
        _draw_wrapped(draw, value, (x + 18, y + 60), card_width - 36, fonts["module"], [accent, "#42D7E8", "#A982FF", "#FFC857"][index], 45, max_lines=1)
        _draw_wrapped(draw, note, (x + 18, y + 120), card_width - 36, fonts["tiny"], "#747B87", 22, max_lines=2)

    y = _draw_png_cycle(draw, model, 890, fonts, ink, muted, paper_2, line)
    if model["period_type"] == "weekly":
        draw.text((48, y), "跨维度关联线索", font=fonts["section"], fill=ink)
        y += 54
        relationships = model.get("trend_analysis", {}).get("relationships", [])
        if not relationships:
            draw.rounded_rectangle((38, y, width - 38, y + 150), radius=8, fill=paper_2, outline=line)
            draw.text((70, y + 30), "关联证据积累中", font=fonts["card"], fill=ink)
            draw.text((70, y + 82), "需要前后两期的配对指标，才能形成跨维度线索。", font=fonts["small"], fill=muted)
            y += 170
        else:
            for item in relationships[:2]:
                draw.rounded_rectangle((38, y, width - 38, y + 126), radius=8, fill=paper_2, outline=line)
                draw.text((66, y + 20), item["title"], font=fonts["card"], fill="#42D7E8")
                _draw_wrapped(draw, item["summary"], (66, y + 60), width - 132, fonts["tiny"], muted, 24, max_lines=2)
                y += 142
    else:
        draw.text((48, y), "身体与行为变化", font=fonts["section"], fill=ink)
        y += 56
        changes = [(key, item) for key, item in model["body_change"].items() if isinstance(item, dict) and "change" in item]
        labels = {"weight_kg": ("体重", "kg"), "body_fat_pct": ("体脂", "%"), "body_fat_percent": ("体脂", "%"), "skeletal_muscle_kg": ("骨骼肌", "kg"), "waist_cm": ("腰围", "cm")}
        if not changes:
            draw.rounded_rectangle((38, y, width - 38, y + 170), radius=8, fill=paper_2, outline=line)
            draw.text((70, y + 34), "趋势证据积累中", font=fonts["card"], fill=ink)
            draw.text((70, y + 88), "至少两次可比较记录后，这里会显示身体成分变化。", font=fonts["small"], fill=muted)
            y += 190
        else:
            for index, (key, item) in enumerate(changes[:3]):
                x = 38 + index * 340
                label, unit = labels.get(key, (key, ""))
                draw.rounded_rectangle((x, y, x + 320, y + 170), radius=8, fill=paper_2, outline=line)
                draw.text((x + 22, y + 22), label, font=fonts["small"], fill=muted)
                draw.text((x + 22, y + 66), f"{item['change']:+.2f} {unit}", font=fonts["module"], fill=accent)
                draw.text((x + 22, y + 127), f"{item['first']} → {item['latest']}", font=fonts["tiny"], fill=muted)
            y += 190

        relationships = model.get("trend_analysis", {}).get("relationships", [])
        if relationships:
            draw.text((48, y), "跨维度关联线索", font=fonts["small"], fill=ink)
            _draw_wrapped(draw, relationships[0]["summary"], (300, y), 730, fonts["tiny"], muted, 24, max_lines=2)
            y += 64

    y = max(y + 12, 1280)
    draw.text((48, y), "维度评分", font=fonts["section"], fill=ink)
    y += 55
    module_colors = [accent, "#42D7E8", "#FF7082", "#A982FF"]
    for index, module in enumerate(model["modules"].values()):
        draw.text((48, y), module["label"], font=fonts["small"], fill=muted)
        draw.rounded_rectangle((190, y + 6, 900, y + 20), radius=7, fill=line)
        fill_width = int(710 * (module["score"] or 0) / 100)
        if fill_width:
            draw.rounded_rectangle((190, y + 6, 190 + fill_width, y + 20), radius=7, fill=module_colors[index])
        value = str(module["score"] if module["score"] is not None else "--")
        draw.text((938, y - 4), value, font=fonts["body"], fill=ink)
        basis = " · ".join(str(item["label"]) for item in module.get("basis", [])[:3]) or "评分证据积累中"
        draw.text((190, y + 27), basis, font=fonts["tiny"], fill="#747B87")
        y += 57

    y += 12
    draw.text((48, y), "下一步行动", font=fonts["section"], fill=ink)
    y += 52
    action = model["actions"][0] if model["actions"] else {"title": "继续稳定记录", "rationale": "让趋势逐步变得可靠。", "timing": "接下来"}
    draw.rounded_rectangle((38, y, width - 38, min(y + 150, 1835)), radius=8, fill=paper_2, outline="#66552D")
    draw.text((70, y + 25), action["timing"], font=fonts["tiny"], fill="#FFC857")
    _draw_wrapped(draw, action["title"], (70, y + 56), width - 140, fonts["card"], ink, 35, max_lines=1)
    _draw_wrapped(draw, action["rationale"], (70, y + 98), width - 140, fonts["tiny"], muted, 23, max_lines=2)
    draw.text((48, 1872), "本地生成 · 健康状态与数据完整度分开计算 · 不替代专业医疗建议", font=fonts["small"], fill="#656C77")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    path.chmod(0o600)
    return [path]


def _render_daily_long_png(
    model: dict[str, Any], path: Path, *, events: list[dict[str, Any]]
) -> None:
    from PIL import Image, ImageDraw

    width = 1080
    fonts = _load_pillow_fonts()
    measure = ImageDraw.Draw(Image.new("RGB", (width, 32), "#08090D"))
    cycle = model.get("cycle_support") or {}
    cycle_visible = bool(
        cycle.get("enabled")
        and (cycle.get("support") or {}).get("visible") is not False
    )

    event_rows: list[tuple[dict[str, Any], str, int, int]] = []
    for event in events:
        label = EVENT_LABELS.get(event["event_type"], event["event_type"])
        summary = f"{label} · {event_summary(event)}"
        line_count = len(_wrapped_lines(measure, summary, 820, fonts["body"], 3))
        event_rows.append((event, summary, line_count, max(90, line_count * 34 + 52)))

    insight_rows: list[tuple[dict[str, Any], int, int]] = []
    for insight in model.get("insights", []):
        title_lines = len(_wrapped_lines(measure, insight.get("title") or "关键洞察", 910, fonts["card"], 2))
        explanation_lines = len(_wrapped_lines(measure, insight.get("explanation") or "", 910, fonts["tiny"], 4))
        insight_rows.append((insight, title_lines, max(116, 42 + title_lines * 35 + explanation_lines * 26)))

    actions = model.get("actions") or [
        {"title": "继续稳定记录", "rationale": "让趋势逐步变得可靠。", "timing": "接下来"}
    ]
    action_rows: list[tuple[dict[str, Any], int, int]] = []
    for action in actions:
        title_lines = len(_wrapped_lines(measure, action.get("title") or "下一步行动", 900, fonts["card"], 2))
        rationale_lines = len(_wrapped_lines(measure, action.get("rationale") or "", 900, fonts["tiny"], 3))
        action_rows.append((action, title_lines, max(140, 54 + title_lines * 35 + rationale_lines * 26)))

    timeline_start = 1040 if cycle_visible else 890
    y_after_timeline = timeline_start + 64 + sum(row[3] for row in event_rows)
    modules_start = max(y_after_timeline + 28, 1280)
    modules_end = modules_start + 58 + len(model["modules"]) * 64
    insights_start = modules_end + 28
    insights_end = insights_start + 58 + sum(row[2] + 14 for row in insight_rows)
    actions_start = insights_end + 18
    actions_end = actions_start + 58 + sum(row[2] + 14 for row in action_rows)
    height = max(1920, actions_end + 100)

    image = Image.new("RGB", (width, height), "#08090D")
    draw = ImageDraw.Draw(image)
    accent = PALETTE.get(model["status"], PALETTE["unknown"])
    ink, muted, paper, paper_2, line = "#F6F7F9", "#9298A5", "#111318", "#181B22", "#2B3039"

    for row in range(0, 610, 4):
        ratio = row / 610
        base = (10, 12, 16)
        accent_rgb = tuple(int(accent[index : index + 2], 16) for index in (1, 3, 5))
        color = tuple(int(base[i] * ratio + accent_rgb[i] * (1 - ratio) * 0.18) for i in range(3))
        draw.rectangle((0, row, width, row + 4), fill=color)
    draw.rectangle((48, 45, 94, 91), outline=accent, width=3)
    draw.text((62, 52), "B", font=fonts["body"], fill=accent)
    draw.text((112, 48), "BodyNote", font=fonts["brand"], fill=ink)
    period_text = _period_text(model)
    draw.text((width - 48 - draw.textlength(period_text, font=fonts["small"]), 55), period_text, font=fonts["small"], fill="#C4C8D0")
    draw.text((48, 142), "TODAY SIGNAL", font=fonts["small"], fill=accent)
    _draw_wrapped(draw, model["summary"]["headline"], (48, 188), 650, fonts["headline"], ink, 58, max_lines=3)
    overview = " · ".join(str(item.get("title") or "") for item in model.get("insights", []) if item.get("title")) or "数据正在形成你的个人健康脉络。"
    _draw_wrapped(draw, overview, (48, 380), 630, fonts["small"], "#B1B6C0", 30, max_lines=3)

    score = model["health_score"]
    progress = (score if score is not None else round(model["confidence"] * 100)) * 3.6
    draw.ellipse((760, 158, 1012, 410), outline=line, width=22)
    draw.arc((760, 158, 1012, 410), start=-90, end=-90 + progress, fill=accent, width=22)
    score_text = str(score) if score is not None else "--"
    score_box = draw.textbbox((0, 0), score_text, font=fonts["score"])
    draw.text((886 - (score_box[2] - score_box[0]) / 2, 232), score_text, font=fonts["score"], fill=accent)
    draw.text((839, 335), "健康状态", font=fonts["small"], fill=muted)
    draw.text((760, 448), f"数据置信度  {round(model['confidence'] * 100)}%", font=fonts["small"], fill=muted)
    draw.rounded_rectangle((760, 486, 1012, 496), radius=5, fill=line)
    draw.rounded_rectangle((760, 486, 760 + int(252 * model["confidence"]), 496), radius=5, fill="#42D7E8")

    draw.text((48, 642), "今日关键指标", font=fonts["section"], fill=ink)
    metrics = _png_metrics(model, events)
    for index, (label, value, note) in enumerate(metrics[:4]):
        x, card_y, card_width = 38 + index * 255, 694, 237
        draw.rounded_rectangle((x, card_y, x + card_width, card_y + 172), radius=8, fill=paper, outline=line)
        draw.text((x + 18, card_y + 18), label, font=fonts["small"], fill=muted)
        _draw_wrapped(draw, value, (x + 18, card_y + 60), card_width - 36, fonts["module"], [accent, "#42D7E8", "#A982FF", "#FFC857"][index], 45, max_lines=1)
        _draw_wrapped(draw, note, (x + 18, card_y + 120), card_width - 36, fonts["tiny"], "#747B87", 22, max_lines=2)

    y = _draw_png_cycle(draw, model, 890, fonts, ink, muted, paper_2, line)
    draw.text((48, y), "今天发生了什么", font=fonts["section"], fill=ink)
    count_text = f"共 {len(events)} 条"
    draw.text((width - 48 - draw.textlength(count_text, font=fonts["small"]), y + 5), count_text, font=fonts["small"], fill=muted)
    y += 64
    if not event_rows:
        draw.text((48, y), "今天暂无记录；未记录不等于异常。", font=fonts["small"], fill=muted)
        y += 90
    for event, summary, line_count, row_height in event_rows:
        draw.text((48, y + 4), event_time_label(event), font=fonts["tiny"], fill=accent)
        draw.ellipse((142, y + 9, 156, y + 23), fill=accent)
        draw.line((149, y + 24, 149, y + row_height - 8), fill=line, width=2)
        _draw_wrapped(draw, summary, (176, y), 820, fonts["body"], ink, 34, max_lines=3)
        draw.text((176, y + line_count * 34 + 5), f"来源：{event.get('source') or '本地记录'}", font=fonts["tiny"], fill=muted)
        y += row_height

    y = max(y + 28, modules_start)
    draw.text((48, y), "维度评分", font=fonts["section"], fill=ink)
    y += 58
    module_colors = [accent, "#42D7E8", "#FF7082", "#A982FF"]
    for index, module in enumerate(model["modules"].values()):
        draw.text((48, y), module["label"], font=fonts["small"], fill=muted)
        draw.rounded_rectangle((190, y + 7, 900, y + 22), radius=7, fill=line)
        fill_width = int(710 * (module["score"] or 0) / 100)
        if fill_width:
            draw.rounded_rectangle((190, y + 7, 190 + fill_width, y + 22), radius=7, fill=module_colors[index])
        draw.text((938, y - 4), str(module["score"] if module["score"] is not None else "--"), font=fonts["body"], fill=ink)
        basis = " · ".join(str(item["label"]) for item in module.get("basis", [])[:3]) or "评分证据积累中"
        draw.text((190, y + 31), basis, font=fonts["tiny"], fill="#747B87")
        y += 64

    y += 28
    draw.text((48, y), "关键洞察", font=fonts["section"], fill=ink)
    y += 58
    insight_colors = {"red": "#FF7082", "yellow": "#FFC857", "green": accent, "blue": "#42D7E8"}
    for insight, title_lines, card_height in insight_rows:
        color = insight_colors.get(str(insight.get("severity")), "#42D7E8")
        draw.rounded_rectangle((38, y, width - 38, y + card_height), radius=8, fill=paper_2, outline=line)
        draw.rectangle((38, y, 44, y + card_height), fill=color)
        _draw_wrapped(draw, insight.get("title") or "关键洞察", (70, y + 20), 910, fonts["card"], ink, 35, max_lines=2)
        _draw_wrapped(draw, insight.get("explanation") or "", (70, y + 25 + title_lines * 35), 910, fonts["tiny"], muted, 26, max_lines=4)
        y += card_height + 14

    y += 18
    draw.text((48, y), "下一步行动", font=fonts["section"], fill=ink)
    y += 58
    for action, title_lines, card_height in action_rows:
        draw.rounded_rectangle((38, y, width - 38, y + card_height), radius=8, fill=paper_2, outline="#66552D")
        draw.text((70, y + 18), str(action.get("timing") or "接下来"), font=fonts["tiny"], fill="#FFC857")
        _draw_wrapped(draw, action.get("title") or "继续稳定记录", (70, y + 48), 900, fonts["card"], ink, 35, max_lines=2)
        _draw_wrapped(draw, action.get("rationale") or "", (70, y + 53 + title_lines * 35), 900, fonts["tiny"], muted, 26, max_lines=3)
        y += card_height + 14

    draw.text((48, height - 55), "本地生成 · 健康状态与数据完整度分开计算 · 不替代专业医疗建议", font=fonts["small"], fill="#656C77")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    path.chmod(0o600)


def _draw_png_cycle(
    draw: Any,
    model: dict[str, Any],
    y: int,
    fonts: dict[str, Any],
    ink: str,
    muted: str,
    paper: str,
    line: str,
) -> int:
    cycle = model.get("cycle_support") or {}
    support = cycle.get("support") or {}
    if not cycle.get("enabled") or support.get("visible") is False:
        return y
    draw.rounded_rectangle((38, y, 1042, y + 122), radius=8, fill=paper, outline=line)
    draw.text((66, y + 18), "周期支持", font=fonts["small"], fill="#A982FF")
    draw.text((190, y + 18), str(support.get("title") or "规律积累中"), font=fonts["body"], fill=ink)
    _draw_wrapped(draw, str(support.get("action") or support.get("note") or cycle.get("message") or ""), (66, y + 60), 930, fonts["tiny"], muted, 23, max_lines=2)
    return y + 150


def _png_metrics(
    model: dict[str, Any], events: list[dict[str, Any]]
) -> list[tuple[str, str, str]]:
    if model["period_type"] == "daily":
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            grouped.setdefault(event["event_type"], []).append(event)
        exercises = grouped.get("exercise", [])
        meals = grouped.get("meal", [])
        sleep = (grouped.get("sleep") or [None])[-1]
        body = (grouped.get("body") or [None])[-1]
        steps = sum(int(event["payload"].get("steps") or 0) for event in exercises)
        minutes = sum(float(event["payload"].get("duration_min") or 0) for event in exercises)
        totals = {
            field: sum(float(event["payload"].get(field) or 0) for event in meals)
            for field in ("calories_kcal", "protein_g", "carbs_g", "fat_g")
        }
        sleep_hours = sleep["payload"].get("duration_hours") if sleep else None
        weight = body["payload"].get("weight_kg") if body else None
        return [
            ("饮食能量", f"{totals['calories_kcal']:g} kcal" if totals["calories_kcal"] else f"{len(meals)} 餐", "来自已记录饮食"),
            ("三大营养素", f"P {totals['protein_g']:g} g" if any(totals.values()) else "待补充", f"C {totals['carbs_g']:g} g · F {totals['fat_g']:g} g" if any(totals.values()) else "蛋白 · 碳水 · 脂肪"),
            ("今日活动", f"{steps:,} 步" if steps else f"{minutes:g} 分" if minutes else "未记录", f"{len(exercises)} 条活动记录"),
            ("恢复与身体", f"{sleep_hours} h" if sleep_hours is not None else "未记录", f"体重 {weight} kg" if weight is not None else "睡眠 · 体重趋势"),
        ]
    trend = model.get("trend_analysis", {})
    trend_metrics = trend.get("metrics", {})
    keys = {
        "daily": ("steps", "exercise_kcal", "protein_g", "weight_kg"),
        "weekly": ("steps", "strength_sessions", "protein_g", "sleep_hours"),
        "monthly": ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "protein_g"),
    }[model["period_type"]]
    rich = []
    for key in keys:
        item = trend_metrics.get(key)
        if not item:
            continue
        current = item.get("current")
        delta = item.get("delta")
        value = "--" if current is None else f"{current:g} {item['unit']}"
        note = "暂无前期对照" if delta is None else f"较前期 {delta:+g} {item['unit']}"
        rich.append((item["label"], value, note))
    if len(rich) == 4:
        return rich
    if model["period_type"] == "weekly":
        movement = model["movement_structure"]
        recovery = model["recovery_pattern"]
        return [
            ("记录日", f"{model['data_completeness']['days_with_data']} / 7", "本周数据覆盖"),
            ("活动", f"{movement['sessions']} 次", f"力量 {movement['strength']} · 有氧 {movement['cardio']}"),
            ("平均睡眠", f"{recovery['average_sleep_hours'] or '--'} h", f"{recovery['sleep_records']} 条记录"),
            ("健康分", str(model["health_score"] or "--"), "综合状态参考"),
        ]
    if model["period_type"] == "monthly":
        consistency = model["consistency"]
        capacity = model["training_capacity"]
        return [
            ("记录日", f"{consistency['active_days']} 天", "本月有证据的日期"),
            ("活动", f"{capacity['sessions']} 次", f"累计 {capacity['total_duration_min']} 分钟"),
            ("饮食", f"{consistency['meal_days']} 天", "饮食模式覆盖"),
            ("睡眠", f"{consistency['sleep_days']} 天", "恢复趋势覆盖"),
        ]
    return rich


def _load_pillow_fonts() -> dict[str, Any]:
    from PIL import ImageFont

    candidates = [
        os.getenv("BODYNOTE_CJK_FONT", ""),
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    font_path = next((path for path in candidates if path and Path(path).exists()), None)
    if font_path is None:
        raise RuntimeError("未找到可用的中文字体。请通过 BODYNOTE_CJK_FONT 指定字体文件。")
    return {
        "brand": ImageFont.truetype(font_path, 34),
        "score": ImageFont.truetype(font_path, 76),
        "headline": ImageFont.truetype(font_path, 42),
        "section": ImageFont.truetype(font_path, 34),
        "module": ImageFont.truetype(font_path, 42),
        "card": ImageFont.truetype(font_path, 29),
        "body": ImageFont.truetype(font_path, 28),
        "small": ImageFont.truetype(font_path, 24),
        "tiny": ImageFont.truetype(font_path, 20),
    }


def _wrapped_lines(
    draw: Any, text: str, max_width: int, font: Any, max_lines: int
) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in str(text):
        candidate = current + char
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _draw_wrapped(draw: Any, text: str, position: tuple[int, int], max_width: int, font: Any, fill: str, line_height: int, *, max_lines: int) -> int:
    lines = _wrapped_lines(draw, str(text), max_width, font, max_lines)
    x, y = position
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _render_pdf(model: dict[str, Any], path: Path) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise RuntimeError("生成 PDF 需要 reportlab，请先安装项目依赖。") from error

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    title = ParagraphStyle("BodyNoteTitle", parent=styles["Title"], fontName="STSong-Light", fontSize=23, leading=31, textColor=colors.HexColor("#17202A"), alignment=TA_CENTER, spaceAfter=12)
    heading = ParagraphStyle("BodyNoteHeading", parent=styles["Heading2"], fontName="STSong-Light", fontSize=15, leading=21, textColor=colors.HexColor("#17202A"), spaceBefore=12, spaceAfter=9)
    body = ParagraphStyle("BodyNoteBody", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17, textColor=colors.HexColor("#3F4A56"))
    small = ParagraphStyle("BodyNoteSmall", parent=body, fontSize=8.5, leading=13, textColor=colors.HexColor("#697386"))
    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=_period_text(model), author="BodyNote")
    story: list[Any] = [Paragraph(_pdf_title(model), title), Paragraph(model["summary"]["headline"], heading)]
    score = model["health_score"] if model["health_score"] is not None else "暂无"
    summary_table = Table([["健康状态", "数据置信度", "记录范围"], [str(score), f"{round(model['confidence'] * 100)}%", _period_text(model)]], colWidths=[50 * mm, 50 * mm, 60 * mm])
    summary_table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "STSong-Light"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17202A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE2E8"))]))
    story.extend([summary_table, Spacer(1, 8 * mm)])
    cycle = model.get("cycle_support") or {}
    support = cycle.get("support") or {}
    if cycle.get("enabled") and support.get("visible") is not False:
        story.extend(
            [
                Paragraph("周期支持", heading),
                Paragraph(f"<b>{stdlib_html.escape(_pdf_text(support.get('title') or '周期规律积累中'))}</b>", body),
                Paragraph(stdlib_html.escape(_pdf_text(support.get("note") or cycle.get("message") or "")), body),
                Paragraph(stdlib_html.escape(_pdf_text(support.get("action") or "继续记录周期和主观感受。")), body),
                Paragraph(stdlib_html.escape(str(cycle.get("disclaimer") or "")), small),
            ]
        )
    story.append(Paragraph("维度评分", heading))
    module_rows = [["维度", "状态分", "证据置信度", "摘要"]]
    for module in model["modules"].values():
        basis = "；".join(
            f"{item['label']} {item['score'] if item['score'] is not None else '--'}：{item['evidence']}"
            for item in module.get("basis", [])
        ) or "评分证据积累中"
        module_rows.append([module["label"], str(module["score"] if module["score"] is not None else "暂无"), f"{round(module['confidence'] * 100)}%", Paragraph(f"{stdlib_html.escape(_pdf_text(module['summary']))}<br/><font size='8'>{stdlib_html.escape(_pdf_text(basis))}</font>", body)])
    modules_table = Table(module_rows, colWidths=[28 * mm, 24 * mm, 29 * mm, 79 * mm], repeatRows=1)
    modules_table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "STSong-Light"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F4")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17202A")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE2E8")), ("FONTSIZE", (0, 0), (-1, -1), 9.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([modules_table, Spacer(1, 5 * mm), Paragraph("洞察", heading)])
    for insight in model["insights"]:
        story.extend([Paragraph(f"<b>{insight['title']}</b>", body), Paragraph(insight["explanation"], body), Paragraph(f"下一步：{insight['next_action']}", small), Spacer(1, 3 * mm)])
    relationships = model.get("trend_analysis", {}).get("relationships", [])
    if relationships:
        story.append(Paragraph("跨维度关联线索", heading))
        for item in relationships[:4]:
            story.extend(
                [
                    Paragraph(f"<b>{stdlib_html.escape(str(item['title']))}</b>", body),
                    Paragraph(stdlib_html.escape(f"{item['summary']} {item['caveat']}"), small),
                    Spacer(1, 2 * mm),
                ]
            )
    story.extend([Paragraph("行动", heading)])
    for index, action in enumerate(model["actions"], 1):
        story.append(Paragraph(f"{index}. <b>{action['title']}</b>（{action['timing']}）<br/>{action['rationale']}", body))
        story.append(Spacer(1, 3 * mm))
    if model["period_type"] != "daily":
        story.append(Paragraph("周期结构", heading))
        detail_rows = [
            [Paragraph(f"<b>{label}</b>", body), Paragraph(value, body)]
            for label, value in _pdf_period_details(model)
        ]
        detail_table = Table(detail_rows, colWidths=[35 * mm, 125 * mm])
        detail_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF1F4")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE2E8")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(detail_table)
    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(colors.HexColor("#697386"))
        canvas.drawString(18 * mm, 10 * mm, "BodyNote 不用于诊断、处方或替代专业医疗建议。")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    path.chmod(0o600)


def _pdf_text(value: Any) -> str:
    return str(value).replace(" · ", "，").replace("·", "，")


def _pdf_period_details(model: dict[str, Any]) -> list[tuple[str, str]]:
    if model["period_type"] == "weekly":
        structure = model["movement_structure"]
        nutrition = model["nutrition_pattern"]
        recovery = model["recovery_pattern"]
        selected_metrics = model.get("trend_analysis", {}).get("metrics", {})
        trend = "；".join(
            f"{selected_metrics[key]['label']} {selected_metrics[key]['current']:g} "
            f"{selected_metrics[key]['unit']}（较前期 {selected_metrics[key]['delta']:+g} "
            f"{selected_metrics[key]['unit']}）"
            for key in ("steps", "strength_sessions", "protein_g", "sleep_hours")
            if key in selected_metrics
            and selected_metrics[key].get("current") is not None
            and selected_metrics[key].get("delta") is not None
        ) or "当前没有足够的前期对照。"
        next_action = model["actions"][0]["title"] if model["actions"] else "继续稳定记录"
        return [("关键变化", trend), ("运动结构", f"共 {structure['sessions']} 次：有氧 {structure['cardio']}，力量 {structure['strength']}，其他 {structure['other']}。"), ("饮食模式", f"共 {nutrition['meals']} 条记录；工作日均值 {nutrition['weekday_daily_average']}，周末均值 {nutrition['weekend_daily_average']}。"), ("恢复模式", f"平均睡眠 {recovery['average_sleep_hours']} 小时，共 {recovery['sleep_records']} 条睡眠记录。"), ("下周重点", next_action)]
    body = model["body_change"]
    consistency = model["consistency"]
    body_labels = {
        "weight_kg": ("体重", "kg"),
        "body_fat_pct": ("体脂率", "%"),
        "body_fat_percent": ("体脂率", "%"),
        "skeletal_muscle_kg": ("骨骼肌", "kg"),
        "muscle_mass_kg": ("肌肉量", "kg"),
        "waist_cm": ("腰围", "cm"),
    }
    body_text = "；".join(
        f"{body_labels.get(key, (key, ''))[0]} "
        f"{value['first']} → {value['latest']} "
        f"({value['change']:+.2f} {body_labels.get(key, (key, ''))[1]})"
        for key, value in body.items()
        if isinstance(value, dict) and "change" in value
    ) or "没有足够的首末身体数据用于比较。"
    capacity = model["training_capacity"]
    cycle = model["cycle_summary"]
    next_action = model["actions"][0]["title"] if model["actions"] else "继续稳定记录"
    return [("身体变化", body_text), ("行为稳定性", f"记录日 {consistency['active_days']}，活动日 {consistency['exercise_days']}，饮食日 {consistency['meal_days']}，睡眠日 {consistency['sleep_days']}。"), ("训练积累", f"活动 {capacity['sessions']} 次，累计 {capacity['total_duration_min']} 分钟，单次最长 {capacity['max_duration_min']} 分钟。"), ("周期证据", cycle["note"]), ("证据等级", "已有趋势证据。" if model["evidence_level"] == "sufficient" else "证据不足，本月仅做记录摘要。"), ("下月重点", next_action)]


def _delivery_attachments(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    png_keys = sorted(
        (key for key in artifacts if key == "png" or key.startswith("png_")),
        key=lambda key: 1 if key == "png" else int(key.split("_", 1)[1]),
    )
    order = [*png_keys, *(key for key in ("pdf", "html") if key in artifacts)]
    return [{"path": artifacts[key]["path"], "mime_type": artifacts[key]["mime_type"], "title": f"BodyNote {key.upper()} 报告", "size_bytes": artifacts[key]["size_bytes"], "sha256": artifacts[key]["sha256"]} for key in order]


def _stage_attachments(
    attachments: list[dict[str, Any]],
    destination: Path,
    report_type: str,
    period_key: str,
) -> list[dict[str, Any]]:
    root = destination.expanduser().resolve()
    target_dir = root / report_type / period_key
    for directory in (root, target_dir.parent, target_dir):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    staged = []
    for legacy_page in target_dir.glob(
        f"bodynote-{report_type}-{period_key}-[0-9]*.png"
    ):
        legacy_page.unlink(missing_ok=True)
    extension_counts: dict[str, int] = {}
    for attachment in attachments:
        source = Path(attachment["path"]).resolve()
        extension = source.suffix.lower()
        if extension not in {".png", ".pdf", ".html"}:
            continue
        extension_counts[extension] = extension_counts.get(extension, 0) + 1
        suffix = "" if extension_counts[extension] == 1 else f"-{extension_counts[extension]}"
        target = target_dir / f"bodynote-{report_type}-{period_key}{suffix}{extension}"
        shutil.copy2(source, target)
        target.chmod(0o600)
        item = dict(attachment)
        item["path"] = str(target)
        item["size_bytes"] = target.stat().st_size
        item["sha256"] = _sha256(target)
        staged.append(item)
    return staged


def _artifact(path: Path, file_format: str) -> dict[str, Any]:
    return {"path": str(path.resolve()), "mime_type": MIME_TYPES[file_format], "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _dashboard_reference_day(
    model: dict[str, Any], timezone_name: str, now: datetime | None
) -> str:
    end = str(model["period"]["end"])
    today = local_date(timezone_name, now)
    start = str(model["period"]["start"])
    return today if start <= today <= end else end


def _summary_text(model: dict[str, Any]) -> str:
    score = model["health_score"] if model["health_score"] is not None else "暂无"
    action = model["actions"][0]["title"] if model["actions"] else "继续稳定记录"
    return f"{model['summary']['headline']} 健康分：{score}，数据置信度：{round(model['confidence'] * 100)}%。下一步：{action}。"


def _period_text(model: dict[str, Any]) -> str:
    period = model["period"]
    return period["start"] if period["start"] == period["end"] else f"{period['start']} - {period['end']}"


def _pdf_title(model: dict[str, Any]) -> str:
    return {"daily": "BodyNote 每日健康报告", "weekly": "BodyNote 每周健康报告", "monthly": "BodyNote 每月健康报告"}[model["period_type"]]


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_local_month_end(timezone_name: str, now: datetime | None) -> bool:
    zone = ZoneInfo(timezone_name)
    value = now or datetime.now(zone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    local = value.astimezone(zone).date()
    return (local + timedelta(days=1)).month != local.month
