from __future__ import annotations

import html
from typing import Any


PALETTE = {
    "green": "#16865B",
    "yellow": "#D18B00",
    "red": "#D84A4A",
    "blue": "#2F6FED",
    "purple": "#8A5BB5",
    "unknown": "#697386",
}


def render_report_html(
    model: dict[str, Any], *, dashboard: bool = False, archive: list[dict[str, str]] | None = None
) -> str:
    accent = PALETTE.get(model["status"], PALETTE["unknown"])
    title = "BodyNote 健康驾驶舱" if dashboard else _report_title(model)
    period_label = _period_label(model)
    score = model["health_score"] if model["health_score"] is not None else "--"
    sections = _daily_sections(model) if model["period_type"] == "daily" else _weekly_sections(model) if model["period_type"] == "weekly" else _monthly_sections(model)
    archive_html = _archive_html(archive or []) if dashboard else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --accent: {accent}; --ink: #17202A; --muted: #697386; --line: #DDE2E8; --paper: #FFFFFF; --canvas: #F2F4F6; }}
    * {{ box-sizing: border-box; }}
    html {{ background: var(--canvas); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; letter-spacing: 0; }}
    body {{ margin: 0; min-width: 320px; }}
    .topbar {{ background: #17202A; color: white; }}
    .topbar-inner {{ max-width: 1080px; margin: 0 auto; padding: 18px 28px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .brand {{ font-size: 18px; font-weight: 760; }}
    .period {{ color: #CBD3DC; font-size: 13px; white-space: nowrap; }}
    main {{ max-width: 1080px; margin: 0 auto; background: var(--paper); min-height: 100vh; }}
    .hero {{ display: grid; grid-template-columns: 220px minmax(0, 1fr); align-items: center; gap: 34px; padding: 42px 34px; border-bottom: 1px solid var(--line); }}
    .score-ring {{ width: 190px; height: 190px; border-radius: 50%; display: grid; place-items: center; background: conic-gradient(var(--accent) calc(var(--confidence) * 1%), #E5E9ED 0); position: relative; }}
    .score-ring::after {{ content: ""; width: 150px; height: 150px; border-radius: 50%; background: white; position: absolute; }}
    .score-value {{ z-index: 1; font-size: 56px; font-weight: 780; color: var(--accent); line-height: 1; }}
    .score-label {{ z-index: 1; position: absolute; margin-top: 82px; font-size: 12px; color: var(--muted); }}
    h1 {{ margin: 0 0 12px; font-size: 34px; line-height: 1.25; letter-spacing: 0; }}
    .subhead {{ margin: 0; color: var(--muted); font-size: 16px; line-height: 1.7; }}
    .confidence {{ display: flex; align-items: center; gap: 10px; margin-top: 20px; font-size: 13px; color: var(--muted); }}
    .confidence-track {{ width: 180px; height: 8px; background: #E8EBEF; border-radius: 4px; overflow: hidden; }}
    .confidence-fill {{ height: 100%; background: #2F6FED; width: calc(var(--confidence) * 1%); }}
    section {{ padding: 30px 34px; border-bottom: 1px solid var(--line); }}
    .section-title {{ margin: 0 0 18px; font-size: 19px; line-height: 1.3; }}
    .module-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .module {{ border: 1px solid var(--line); border-radius: 8px; padding: 17px; min-height: 138px; }}
    .module-name {{ color: var(--muted); font-size: 12px; }}
    .module-score {{ font-size: 30px; font-weight: 760; margin: 12px 0 8px; }}
    .module-summary {{ font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }}
    .card-list {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
    .insight {{ border: 1px solid var(--line); border-top: 4px solid var(--card-accent); border-radius: 8px; padding: 17px; min-height: 190px; }}
    .eyebrow {{ color: var(--card-accent); font-size: 11px; font-weight: 760; text-transform: uppercase; }}
    .insight h3 {{ font-size: 16px; line-height: 1.45; margin: 10px 0; }}
    .insight p {{ color: var(--muted); font-size: 13px; line-height: 1.65; margin: 0; }}
    .action-list {{ display: grid; gap: 10px; }}
    .action {{ display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 14px; align-items: start; padding: 14px 0; border-top: 1px solid var(--line); }}
    .action:first-child {{ border-top: 0; }}
    .timing {{ color: var(--accent); font-size: 12px; font-weight: 760; }}
    .action-title {{ font-size: 15px; font-weight: 720; margin-bottom: 5px; }}
    .action-note {{ color: var(--muted); font-size: 13px; line-height: 1.55; }}
    .trend {{ height: 190px; display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px; align-items: end; padding-top: 20px; }}
    .trend-col {{ height: 100%; display: flex; flex-direction: column; justify-content: end; align-items: center; gap: 8px; }}
    .trend-bar {{ width: min(44px, 80%); min-height: 4px; background: var(--accent); border-radius: 4px 4px 0 0; opacity: .88; }}
    .trend-date, .trend-score {{ font-size: 11px; color: var(--muted); }}
    .split {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }}
    .metric-band {{ border-left: 4px solid var(--accent); padding: 12px 16px; background: #F7F8FA; border-radius: 0 8px 8px 0; }}
    .metric-band strong {{ display: block; font-size: 24px; margin: 7px 0; }}
    .metric-band span {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .change-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .change {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .change-value {{ font-size: 26px; font-weight: 760; margin: 9px 0; }}
    .empty {{ color: var(--muted); font-size: 14px; padding: 16px 0; }}
    .archive a {{ color: #2F6FED; text-decoration: none; }}
    .archive-row {{ display: flex; justify-content: space-between; gap: 16px; padding: 11px 0; border-top: 1px solid var(--line); font-size: 13px; }}
    footer {{ padding: 22px 34px 34px; color: var(--muted); font-size: 11px; line-height: 1.6; }}
    @media (max-width: 760px) {{
      .topbar-inner {{ padding: 15px 18px; }}
      .hero {{ grid-template-columns: 1fr; justify-items: center; text-align: center; padding: 28px 20px; gap: 22px; }}
      .score-ring {{ width: 164px; height: 164px; }}
      .score-ring::after {{ width: 130px; height: 130px; }}
      h1 {{ font-size: 27px; }}
      .confidence {{ justify-content: center; }}
      section {{ padding: 24px 18px; }}
      .module-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .card-list, .split {{ grid-template-columns: 1fr; }}
      .insight {{ min-height: 0; }}
      footer {{ padding: 20px 18px 28px; }}
    }}
    @media (max-width: 390px) {{
      .module-grid {{ grid-template-columns: 1fr; }}
      .period {{ max-width: 150px; white-space: normal; text-align: right; }}
    }}
    @media print {{ html {{ background: white; }} main {{ max-width: none; }} .topbar {{ print-color-adjust: exact; }} }}
  </style>
</head>
<body style="--confidence:{round(model['confidence'] * 100)}">
  <header class="topbar"><div class="topbar-inner"><div class="brand">BodyNote</div><div class="period">{html.escape(period_label)}</div></div></header>
  <main>
    <div class="hero">
      <div class="score-ring"><div class="score-value">{score}</div><div class="score-label">健康状态</div></div>
      <div><h1>{html.escape(str(model['summary']['headline']))}</h1><p class="subhead">{html.escape(_hero_detail(model))}</p><div class="confidence"><span>数据置信度 {round(model['confidence'] * 100)}%</span><div class="confidence-track"><div class="confidence-fill"></div></div></div></div>
    </div>
    {_module_section(model)}
    {sections}
    {_insight_section(model)}
    {_action_section(model)}
    {archive_html}
    <footer>健康分反映当前已有证据，数据缺失主要降低置信度。BodyNote 不用于诊断、处方或替代专业医疗建议。</footer>
  </main>
</body>
</html>
"""


def _module_section(model: dict[str, Any]) -> str:
    items = []
    for module in model["modules"].values():
        score = module["score"] if module["score"] is not None else "--"
        items.append(f'<div class="module"><div class="module-name">{html.escape(module["label"])}</div><div class="module-score">{score}</div><div class="module-summary">{html.escape(str(module["summary"]))}</div></div>')
    return f'<section><h2 class="section-title">四个健康维度</h2><div class="module-grid">{"".join(items)}</div></section>'


def _daily_sections(model: dict[str, Any]) -> str:
    completeness = model["data_completeness"]
    completed = len(completeness["completed"])
    total = len(completeness["required"])
    missing = "、".join(completeness["missing"]) or "无"
    return f'<section><h2 class="section-title">今日记录</h2><div class="split"><div class="metric-band"><span>已完成</span><strong>{completed}/{total}</strong><span>按首次设置中的每日范围计算</span></div><div class="metric-band"><span>仍缺少</span><strong>{len(completeness["missing"])}</strong><span>{html.escape(missing)}</span></div></div></section>'


def _weekly_sections(model: dict[str, Any]) -> str:
    bars = []
    for point in model["trend"]:
        score = point["score"]
        height = 8 if score is None else max(8, int(score * 1.35))
        label = "--" if score is None else str(score)
        bars.append(f'<div class="trend-col"><div class="trend-score">{label}</div><div class="trend-bar" style="height:{height}px"></div><div class="trend-date">{html.escape(point["date"][5:])}</div></div>')
    structure = model["movement_structure"]
    recovery = model["recovery_pattern"]
    sleep = recovery["average_sleep_hours"] if recovery["average_sleep_hours"] is not None else "--"
    return f'<section><h2 class="section-title">七日趋势</h2><div class="trend">{"".join(bars)}</div></section><section><h2 class="section-title">本周结构</h2><div class="split"><div class="metric-band"><span>运动结构</span><strong>{structure["sessions"]} 次</strong><span>有氧 {structure["cardio"]} · 力量 {structure["strength"]} · 其他 {structure["other"]}</span></div><div class="metric-band"><span>平均睡眠</span><strong>{sleep} 小时</strong><span>基于 {recovery["sleep_records"]} 条睡眠记录</span></div></div></section>'


def _monthly_sections(model: dict[str, Any]) -> str:
    changes = []
    labels = {"weight_kg": "体重", "body_fat_pct": "体脂率", "skeletal_muscle_kg": "骨骼肌", "waist_cm": "腰围"}
    units = {"weight_kg": "kg", "body_fat_pct": "%", "skeletal_muscle_kg": "kg", "waist_cm": "cm"}
    for key, label in labels.items():
        value = model["body_change"].get(key)
        if value:
            changes.append(f'<div class="change"><div class="module-name">{label}</div><div class="change-value">{value["change"]:+.2f} {units[key]}</div><div class="module-summary">{value["first"]} → {value["latest"]}</div></div>')
    if not changes:
        changes.append('<div class="empty">本月没有可比较的身体成分记录。</div>')
    consistency = model["consistency"]
    return f'<section><h2 class="section-title">身体变化</h2><div class="change-grid">{"".join(changes)}</div></section><section><h2 class="section-title">行为稳定性</h2><div class="split"><div class="metric-band"><span>有记录日期</span><strong>{consistency["active_days"]} 天</strong><span>活动 {consistency["exercise_days"]} · 饮食 {consistency["meal_days"]}</span></div><div class="metric-band"><span>恢复与身体</span><strong>{consistency["sleep_days"] + consistency["body_days"]} 天</strong><span>睡眠 {consistency["sleep_days"]} · 身体 {consistency["body_days"]}</span></div></div></section>'


def _insight_section(model: dict[str, Any]) -> str:
    type_labels = {
        "achievement": "成就",
        "completion": "完成",
        "gap": "数据缺口",
        "risk": "优先关注",
        "explanation": "可能解释",
        "trend": "趋势",
        "correlation": "关联",
        "suggestion": "建议",
    }
    cards = []
    for insight in model["insights"]:
        color = PALETTE.get(insight["severity"], PALETTE["blue"])
        label = type_labels.get(insight["type"], insight["type"])
        cards.append(f'<article class="insight" style="--card-accent:{color}"><div class="eyebrow">{html.escape(label)}</div><h3>{html.escape(insight["title"])}</h3><p>{html.escape(insight["explanation"])}</p></article>')
    return f'<section><h2 class="section-title">值得注意</h2><div class="card-list">{"".join(cards)}</div></section>'


def _action_section(model: dict[str, Any]) -> str:
    actions = []
    for action in model["actions"]:
        actions.append(f'<div class="action"><div class="timing">{html.escape(action["timing"])}</div><div><div class="action-title">{html.escape(action["title"])}</div><div class="action-note">{html.escape(action["rationale"])}</div></div></div>')
    return f'<section><h2 class="section-title">接下来做什么</h2><div class="action-list">{"".join(actions)}</div></section>'


def _archive_html(archive: list[dict[str, str]]) -> str:
    if not archive:
        return ""
    rows = "".join(f'<div class="archive-row"><a href="{html.escape(item["href"])}">{html.escape(item["label"])}</a><span>{html.escape(item["period"])}</span></div>' for item in archive[:12])
    return f'<section class="archive"><h2 class="section-title">近期报告</h2>{rows}</section>'


def _report_title(model: dict[str, Any]) -> str:
    return {"daily": "BodyNote 日报", "weekly": "BodyNote 周报", "monthly": "BodyNote 月报"}[model["period_type"]]


def _period_label(model: dict[str, Any]) -> str:
    period = model["period"]
    if model["period_type"] == "monthly":
        return f"{model['period_key']} 月报"
    if period["start"] == period["end"]:
        return period["start"]
    return f"{period['start']} 至 {period['end']}"


def _hero_detail(model: dict[str, Any]) -> str:
    if model["period_type"] == "daily":
        return f"今天共有 {model['data_completeness']['event_count']} 条记录，数据置信度与健康状态分开计算。"
    if model["period_type"] == "weekly":
        return f"7 天中有 {model['data_completeness']['days_with_data']} 天留下记录，重点观察行为结构和可持续性。"
    level = "已有趋势证据" if model["evidence_level"] == "sufficient" else "当前仅做记录摘要"
    return f"本月有 {model['data_completeness']['days_with_data']} 个记录日，{level}。"
