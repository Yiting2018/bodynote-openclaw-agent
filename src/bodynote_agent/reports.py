from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bodynote_agent.analytics import HealthAnalysisService
from bodynote_agent.database import connect, new_id
from bodynote_agent.html_report import PALETTE, render_report_html
from bodynote_agent.preferences import ALLOWED_REPORT_FORMATS, OnboardingService


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
        key = str(model["period_key"])
        output_dir = self.reports_root / report_type / key
        input_hash = _hash_json({"model": model, "formats": selected})
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
                _write_text(html_path, render_report_html(model))
                artifacts["html"] = _artifact(html_path, "html")
            if "png" in selected:
                png_path = output_dir / "report.png"
                _render_png(model, png_path)
                artifacts["png"] = _artifact(png_path, "png")
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
        _write_text(
            dashboard_path,
            render_report_html(model, dashboard=True, archive=archive),
        )
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


def _render_png(model: dict[str, Any], path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("生成 PNG 需要 Pillow，请先安装项目依赖。") from error

    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), "#F2F4F6")
    draw = ImageDraw.Draw(image)
    accent = PALETTE.get(model["status"], PALETTE["unknown"])
    ink = "#17202A"
    muted = "#697386"
    paper = "#FFFFFF"
    line = "#DDE2E8"
    fonts = _load_pillow_fonts()
    draw.rectangle((0, 0, width, 120), fill=ink)
    draw.text((58, 40), "BodyNote", font=fonts["brand"], fill="white")
    draw.text((width - 350, 45), _period_text(model), font=fonts["small"], fill="#CBD3DC")
    draw.rounded_rectangle((38, 154, width - 38, 510), radius=8, fill=paper)
    draw.ellipse((74, 194, 326, 446), outline="#E5E9ED", width=24)
    score = model["health_score"]
    progress = (score if score is not None else round(model["confidence"] * 100)) * 3.6
    draw.arc((74, 194, 326, 446), start=-90, end=-90 + progress, fill=accent, width=24)
    score_text = str(score) if score is not None else "--"
    score_box = draw.textbbox((0, 0), score_text, font=fonts["score"])
    draw.text((200 - (score_box[2] - score_box[0]) / 2, 270), score_text, font=fonts["score"], fill=accent)
    draw.text((156, 372), "健康状态", font=fonts["small"], fill=muted)
    _draw_wrapped(draw, model["summary"]["headline"], (380, 205), 585, fonts["headline"], ink, 58, max_lines=3)
    draw.text((380, 390), f"数据置信度 {round(model['confidence'] * 100)}%", font=fonts["body"], fill=muted)
    y = 548
    draw.text((48, y), "四个健康维度", font=fonts["section"], fill=ink)
    y += 58
    card_width = 237
    for index, module in enumerate(model["modules"].values()):
        x = 38 + index * (card_width + 18)
        draw.rounded_rectangle((x, y, x + card_width, y + 215), radius=8, fill=paper, outline=line)
        draw.text((x + 20, y + 20), module["label"], font=fonts["small"], fill=muted)
        value = str(module["score"]) if module["score"] is not None else "--"
        draw.text((x + 20, y + 62), value, font=fonts["module"], fill=ink)
        _draw_wrapped(draw, module["summary"], (x + 20, y + 137), card_width - 40, fonts["small"], muted, 26, max_lines=2)
    y += 260
    y = _draw_model_specific_png(draw, model, y, fonts, paper, ink, muted, accent, line)
    draw.text((48, y), "值得注意", font=fonts["section"], fill=ink)
    y += 58
    for insight in model["insights"][:3]:
        color = PALETTE.get(insight["severity"], PALETTE["blue"])
        draw.rounded_rectangle((38, y, width - 38, y + 145), radius=8, fill=paper, outline=line)
        draw.rectangle((38, y, 48, y + 145), fill=color)
        draw.text((70, y + 20), insight["title"], font=fonts["card"], fill=ink)
        _draw_wrapped(draw, insight["explanation"], (70, y + 65), width - 150, fonts["small"], muted, 27, max_lines=2)
        y += 162
        if y > 1640:
            break
    if y < 1700:
        draw.text((48, y + 4), "接下来", font=fonts["section"], fill=ink)
        y += 54
        for number, action in enumerate(model["actions"][:3], 1):
            draw.ellipse((48, y + 3, 82, y + 37), fill=accent)
            draw.text((60, y + 7), str(number), font=fonts["tiny"], fill="white")
            _draw_wrapped(draw, action["title"], (100, y), 860, fonts["body"], ink, 34, max_lines=1)
            y += 54
    if y < 1550 and model["actions"]:
        action = model["actions"][0]
        top = y + 24
        bottom = min(1805, top + 245)
        draw.rounded_rectangle((38, top, width - 38, bottom), radius=8, fill=ink)
        draw.text((72, top + 28), "下一周期的核心小目标", font=fonts["small"], fill="#CBD3DC")
        _draw_wrapped(draw, action["title"], (72, top + 78), width - 150, fonts["headline"], "white", 54, max_lines=2)
        _draw_wrapped(draw, action["rationale"], (72, top + 175), width - 150, fonts["small"], "#CBD3DC", 28, max_lines=2)
    draw.text((48, 1865), "健康状态与数据完整度分开计算 · 不替代专业医疗建议", font=fonts["small"], fill=muted)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    path.chmod(0o600)


def _draw_model_specific_png(draw: Any, model: dict[str, Any], y: int, fonts: dict[str, Any], paper: str, ink: str, muted: str, accent: str, line: str) -> int:
    if model["period_type"] == "daily":
        completeness = model["data_completeness"]
        draw.text((48, y), "今日记录", font=fonts["section"], fill=ink)
        draw.text((270, y), f"完成 {len(completeness['completed'])}/{len(completeness['required'])}", font=fonts["body"], fill=accent)
        draw.text((540, y), f"缺口 {len(completeness['missing'])}", font=fonts["body"], fill=muted)
        return y + 80
    if model["period_type"] == "weekly":
        draw.text((48, y), "七日趋势", font=fonts["section"], fill=ink)
        base = y + 180
        for index, point in enumerate(model["trend"]):
            x = 58 + index * 142
            score = point["score"] or 0
            bar_height = max(8, int(score * 1.1))
            draw.rounded_rectangle((x, base - bar_height, x + 72, base), radius=4, fill=accent)
            draw.text((x + 9, base + 12), point["date"][5:], font=fonts["tiny"], fill=muted)
        return base + 58
    draw.text((48, y), "本月积累", font=fonts["section"], fill=ink)
    consistency = model["consistency"]
    values = [("记录日", consistency["active_days"]), ("活动", consistency["exercise_days"]), ("饮食", consistency["meal_days"]), ("睡眠", consistency["sleep_days"])]
    for index, (label, value) in enumerate(values):
        x = 48 + index * 245
        draw.rounded_rectangle((x, y + 52, x + 220, y + 142), radius=8, fill=paper, outline=line)
        draw.text((x + 18, y + 68), label, font=fonts["small"], fill=muted)
        draw.text((x + 126, y + 61), str(value), font=fonts["module"], fill=accent)
    return y + 185


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
        "section": ImageFont.truetype(font_path, 29),
        "module": ImageFont.truetype(font_path, 42),
        "card": ImageFont.truetype(font_path, 25),
        "body": ImageFont.truetype(font_path, 23),
        "small": ImageFont.truetype(font_path, 19),
        "tiny": ImageFont.truetype(font_path, 16),
    }


def _draw_wrapped(draw: Any, text: str, position: tuple[int, int], max_width: int, font: Any, fill: str, line_height: int, *, max_lines: int) -> int:
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
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
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
    story.extend([summary_table, Spacer(1, 8 * mm), Paragraph("四个健康维度", heading)])
    module_rows = [["维度", "状态分", "证据置信度", "摘要"]]
    for module in model["modules"].values():
        module_rows.append([module["label"], str(module["score"] if module["score"] is not None else "暂无"), f"{round(module['confidence'] * 100)}%", Paragraph(module["summary"], body)])
    modules_table = Table(module_rows, colWidths=[28 * mm, 24 * mm, 29 * mm, 79 * mm], repeatRows=1)
    modules_table.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "STSong-Light"), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F4")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17202A")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE2E8")), ("FONTSIZE", (0, 0), (-1, -1), 9.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([modules_table, Spacer(1, 5 * mm), Paragraph("洞察", heading)])
    for insight in model["insights"]:
        story.extend([Paragraph(f"<b>{insight['title']}</b>", body), Paragraph(insight["explanation"], body), Paragraph(f"下一步：{insight['next_action']}", small), Spacer(1, 3 * mm)])
    story.extend([Paragraph("行动", heading)])
    for index, action in enumerate(model["actions"], 1):
        story.append(Paragraph(f"{index}. <b>{action['title']}</b>（{action['timing']}）<br/>{action['rationale']}", body))
        story.append(Spacer(1, 3 * mm))
    if model["period_type"] != "daily":
        story.extend([PageBreak(), Paragraph("周期结构", heading)])
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
    story.extend([Spacer(1, 7 * mm), Paragraph("健康状态与数据完整度分开计算。BodyNote 不用于诊断、处方或替代专业医疗建议。", small)])

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(colors.HexColor("#697386"))
        canvas.drawString(18 * mm, 10 * mm, "BodyNote 本地健康报告")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    path.chmod(0o600)


def _pdf_period_details(model: dict[str, Any]) -> list[tuple[str, str]]:
    if model["period_type"] == "weekly":
        structure = model["movement_structure"]
        nutrition = model["nutrition_pattern"]
        recovery = model["recovery_pattern"]
        trend = "；".join(
            f"{point['date'][5:]} {point['score'] if point['score'] is not None else '--'}"
            for point in model["trend"]
        )
        next_action = model["actions"][0]["title"] if model["actions"] else "继续稳定记录"
        return [("七日状态", trend), ("运动结构", f"共 {structure['sessions']} 次：有氧 {structure['cardio']}，力量 {structure['strength']}，其他 {structure['other']}。"), ("饮食模式", f"共 {nutrition['meals']} 条记录；工作日均值 {nutrition['weekday_daily_average']}，周末均值 {nutrition['weekend_daily_average']}。"), ("恢复模式", f"平均睡眠 {recovery['average_sleep_hours']} 小时，共 {recovery['sleep_records']} 条睡眠记录。"), ("下周重点", next_action)]
    body = model["body_change"]
    consistency = model["consistency"]
    body_labels = {
        "weight_kg": ("体重", "kg"),
        "body_fat_pct": ("体脂率", "%"),
        "muscle_mass_kg": ("肌肉量", "kg"),
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
    order = ("png", "pdf", "html")
    return [{"path": artifacts[key]["path"], "mime_type": artifacts[key]["mime_type"], "title": f"BodyNote {key.upper()} 报告", "size_bytes": artifacts[key]["size_bytes"], "sha256": artifacts[key]["sha256"]} for key in order if key in artifacts]


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
    for attachment in attachments:
        source = Path(attachment["path"]).resolve()
        extension = source.suffix.lower()
        if extension not in {".png", ".pdf", ".html"}:
            continue
        target = target_dir / f"bodynote-{report_type}-{period_key}{extension}"
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
