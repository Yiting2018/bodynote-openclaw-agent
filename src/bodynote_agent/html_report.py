from __future__ import annotations

import html
from typing import Any


PALETTE = {
    "green": "#A8F34A",
    "yellow": "#FFC857",
    "red": "#FF7082",
    "blue": "#42D7E8",
    "purple": "#A982FF",
    "unknown": "#9099A6",
}

EVENT_LABELS = {
    "exercise": "活动",
    "meal": "饮食",
    "sleep": "睡眠",
    "body": "身体",
    "mood": "感受",
    "symptom": "症状",
    "menstrual_cycle": "周期",
    "blood_pressure": "血压",
    "blood_glucose": "血糖",
    "medical_report": "医疗报告",
}


def render_report_html(
    model: dict[str, Any], *, events: list[dict[str, Any]] | None = None
) -> str:
    accent = PALETTE.get(model["status"], PALETTE["unknown"])
    score = model["health_score"] if model["health_score"] is not None else "--"
    confidence = round(model["confidence"] * 100)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(_report_title(model))}</title>
  <style>
    :root {{ color-scheme:dark; --accent:{accent}; --bg:#08090c; --paper:#111318; --paper2:#181b22; --line:#2b3039; --text:#f6f7f9; --muted:#9298a5; --cyan:#42d7e8; --violet:#a982ff; --coral:#ff7082; --amber:#ffc857; }}
    * {{ box-sizing:border-box; }}
    html {{ background:#000; color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; letter-spacing:0; }}
    body {{ margin:0; min-width:320px; }}
    .sheet {{ width:min(100%,560px); min-height:100vh; margin:0 auto; overflow:hidden; background:var(--bg); box-shadow:0 0 80px rgba(0,0,0,.7); }}
    .hero {{ min-height:440px; padding:28px 25px 32px; position:relative; overflow:hidden; border-bottom:1px solid var(--line); background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 16%,#0a0b0e) 0%,#0a0b0e 46%,#12151b 100%); }}
    .hero::after {{ content:""; position:absolute; width:310px; height:310px; right:-180px; bottom:-190px; border:70px solid color-mix(in srgb,var(--cyan) 10%,transparent); border-radius:50%; }}
    .topline {{ display:flex; justify-content:space-between; align-items:center; gap:12px; color:#c4c8d0; font-size:11px; }}
    .brand {{ display:flex; align-items:center; gap:8px; color:white; font-weight:800; }} .brand i {{ width:24px; height:24px; display:grid; place-items:center; border:1px solid var(--accent); border-radius:6px; color:var(--accent); font-style:normal; }}
    .period-label {{ margin-top:42px; color:var(--accent); font-size:12px; font-weight:800; }}
    h1 {{ margin:13px 0 0; max-width:450px; font-size:42px; line-height:1.06; overflow-wrap:anywhere; }}
    .hero-copy {{ margin:15px 0 0; max-width:465px; color:#aeb3bd; font-size:13px; line-height:1.7; }}
    .score-row {{ display:flex; align-items:end; justify-content:space-between; gap:18px; margin-top:29px; }}
    .score {{ display:flex; align-items:end; gap:8px; }} .score b {{ color:var(--accent); font-size:68px; line-height:.8; }} .score span {{ padding-bottom:3px; color:var(--muted); font-size:11px; }}
    .confidence {{ width:180px; }} .confidence-label {{ display:flex; justify-content:space-between; color:var(--muted); font-size:10px; }} .track {{ height:6px; margin-top:7px; overflow:hidden; border-radius:3px; background:#2a2e35; }} .track i {{ display:block; height:100%; background:var(--cyan); }}
    section {{ padding:25px 20px; border-bottom:1px solid var(--line); }}
    .section-title {{ display:flex; align-items:center; gap:8px; margin:0 0 15px; font-size:15px; }} .section-title::before {{ content:""; width:4px; height:17px; border-radius:2px; background:var(--accent); }}
    .metric-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
    .metric {{ min-height:106px; padding:14px; border:1px solid var(--line); border-radius:8px; background:var(--paper); }} .metric span {{ color:var(--muted); font-size:10px; }} .metric b {{ display:block; margin:11px 0 5px; font-size:24px; overflow-wrap:anywhere; }} .metric small {{ color:#747b87; font-size:10px; line-height:1.45; }}
    .metric:nth-child(1) b {{ color:var(--accent); }} .metric:nth-child(2) b {{ color:var(--cyan); }} .metric:nth-child(3) b {{ color:var(--violet); }} .metric:nth-child(4) b {{ color:var(--amber); }}
    .module-list {{ display:grid; gap:17px; }} .module {{ display:grid; grid-template-columns:64px 1fr 30px; gap:9px; align-items:center; font-size:11px; }} .module>span {{ color:var(--muted); }} .module>b {{ text-align:right; }} .module .track {{ margin:0; height:8px; }} .module-detail {{ grid-column:1/-1; color:#9ba3ae; font-size:9px; line-height:1.55; }} .module-basis {{ grid-column:1/-1; display:flex; flex-wrap:wrap; gap:5px; }} .module-basis i {{ padding:4px 6px; border:1px solid var(--line); border-radius:4px; color:#bdc3cd; font-size:8px; font-style:normal; }}
    .module:nth-child(2) .track i {{ background:var(--cyan); }} .module:nth-child(3) .track i {{ background:var(--coral); }} .module:nth-child(4) .track i {{ background:var(--violet); }}
    .timeline {{ display:grid; }} .event {{ display:grid; grid-template-columns:42px 12px minmax(0,1fr); gap:8px; min-height:65px; }} .event time {{ padding-top:2px; color:var(--accent); font-size:10px; font-weight:700; }} .rail {{ position:relative; }} .rail::before {{ content:""; position:absolute; top:0; bottom:0; left:5px; width:1px; background:var(--line); }} .rail i {{ position:absolute; top:5px; left:2px; width:7px; height:7px; border-radius:50%; background:var(--event-color,var(--accent)); box-shadow:0 0 0 3px var(--bg); }} .event h3 {{ margin:0; font-size:12px; }} .event p {{ margin:4px 0 0; color:var(--muted); font-size:10px; line-height:1.5; }}
    .trend {{ height:180px; display:grid; grid-template-columns:repeat(7,1fr); gap:6px; align-items:end; }} .trend-col {{ height:100%; display:flex; flex-direction:column; justify-content:end; align-items:center; gap:6px; color:var(--muted); font-size:9px; }} .trend-bar {{ width:min(30px,70%); min-height:4px; border-radius:3px 3px 0 0; background:linear-gradient(180deg,var(--accent),var(--cyan)); }}
    .change-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }} .change {{ padding:14px; border:1px solid var(--line); border-radius:8px; background:var(--paper); }} .change span {{ color:var(--muted); font-size:10px; }} .change b {{ display:block; margin:9px 0 4px; font-size:22px; color:var(--accent); }} .change small {{ color:#747b87; font-size:9px; }}
    .insights {{ display:grid; gap:8px; }} .insight {{ padding:14px; border-left:3px solid var(--card-color); border-radius:0 7px 7px 0; background:var(--paper2); }} .insight span {{ color:var(--card-color); font-size:9px; font-weight:800; }} .insight h3 {{ margin:7px 0 5px; font-size:13px; }} .insight p {{ margin:0; color:var(--muted); font-size:10px; line-height:1.6; }} .cycle-support {{ padding:15px; border-left:3px solid var(--violet); background:var(--paper2); }} .cycle-support header {{ display:flex; justify-content:space-between; gap:10px; }} .cycle-support strong {{ font-size:13px; }} .cycle-support span {{ color:var(--violet); font-size:9px; }} .cycle-support p {{ margin:8px 0 0; color:#b7bdc7; font-size:10px; line-height:1.6; }} .cycle-support small {{ display:block; margin-top:7px; color:#717986; font-size:8px; line-height:1.5; }}
    .actions {{ display:grid; gap:8px; }} .action {{ padding:14px; border:1px solid color-mix(in srgb,var(--amber) 34%,var(--line)); border-radius:8px; background:color-mix(in srgb,var(--amber) 7%,var(--paper)); }} .action header {{ display:flex; justify-content:space-between; gap:12px; }} .action strong {{ font-size:12px; }} .action span {{ color:var(--amber); font-size:9px; font-weight:700; }} .action p {{ margin:6px 0 0; color:var(--muted); font-size:10px; line-height:1.55; }}
    footer {{ padding:22px 20px 30px; color:#656c77; font-size:9px; line-height:1.6; text-align:center; }}
    @media(min-width:561px) {{ body {{ padding:24px; }} .sheet {{ border:1px solid #252932; border-radius:8px; }} }}
    @media(max-width:370px) {{ h1 {{ font-size:35px; }} .score-row {{ align-items:flex-start; flex-direction:column; }} .confidence {{ width:100%; }} }}
    @media print {{ html,body {{ background:white; padding:0; }} .sheet {{ width:100%; box-shadow:none; }} }}
  </style>
</head>
<body>
  <main class="sheet">
    <header class="hero">
      <div class="topline"><div class="brand"><i>B</i>BodyNote</div><span>{html.escape(_period_label(model))}</span></div>
      <div class="period-label">{html.escape(_kicker(model))}</div>
      <h1>{html.escape(str(model['summary']['headline']))}</h1>
      <p class="hero-copy">{html.escape(_hero_detail(model))}</p>
      <div class="score-row"><div class="score"><b>{score}</b><span>健康状态</span></div><div class="confidence"><div class="confidence-label"><span>数据置信度</span><b>{confidence}%</b></div><div class="track"><i style="width:{confidence}%"></i></div></div></div>
    </header>
    {_snapshot_section(model, events or [])}
    {_cycle_section(model)}
    {_module_section(model)}
    {_period_section(model)}
    {_relationship_section(model)}
    {_insight_section(model)}
    {_action_section(model)}
    <footer>健康状态与数据完整度分开计算。BodyNote 不用于诊断、处方或替代专业医疗建议。</footer>
  </main>
</body>
</html>"""


def _snapshot_section(model: dict[str, Any], events: list[dict[str, Any]]) -> str:
    if model["period_type"] == "daily":
        metrics = _daily_metrics(events)
        timeline = "".join(_event_html(event) for event in events[:6])
        if not timeline:
            timeline = '<div class="metric"><span>今天暂无记录</span><b>等待发生</b><small>未记录不等于异常。</small></div>'
        cards = "".join(
            f'<div class="metric"><span>{html.escape(label)}</span><b>{html.escape(value)}</b><small>{html.escape(note)}</small></div>'
            for label, value, note in metrics
        )
        return f'<section><h2 class="section-title">今日身体快照</h2><div class="metric-grid">{cards}</div></section><section><h2 class="section-title">今天发生了什么</h2><div class="timeline">{timeline}</div></section>'
    if model["period_type"] == "weekly":
        structure = model["movement_structure"]
        recovery = model["recovery_pattern"]
        metrics = [
            ("记录日", f"{model['data_completeness']['days_with_data']} / 7", "数据覆盖"),
            ("活动", f"{structure['sessions']} 次", f"力量 {structure['strength']} · 有氧 {structure['cardio']}"),
            ("睡眠", f"{recovery['average_sleep_hours'] or '--'} 小时", f"{recovery['sleep_records']} 条记录"),
            ("事件", f"{model['data_completeness']['event_count']} 条", "本周累计"),
        ]
    else:
        consistency = model["consistency"]
        capacity = model["training_capacity"]
        metrics = [
            ("记录日", f"{consistency['active_days']} 天", "本月有证据的日期"),
            ("活动", f"{capacity['sessions']} 次", f"累计 {capacity['total_duration_min']} 分钟"),
            ("饮食", f"{consistency['meal_days']} 天", "饮食模式覆盖"),
            ("睡眠", f"{consistency['sleep_days']} 天", "恢复趋势覆盖"),
        ]
    cards = "".join(
        f'<div class="metric"><span>{html.escape(label)}</span><b>{html.escape(value)}</b><small>{html.escape(note)}</small></div>'
        for label, value, note in metrics
    )
    section_title = "本周结构" if model["period_type"] == "weekly" else "行为稳定性"
    return f'<section><h2 class="section-title">{section_title}</h2><div class="metric-grid">{cards}</div></section>'


def _daily_metrics(events: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(event)
    exercises = by_type.get("exercise", [])
    meals = by_type.get("meal", [])
    sleep = (by_type.get("sleep") or [None])[-1]
    body = (by_type.get("body") or [None])[-1]
    steps = sum(int(item["payload"].get("steps") or 0) for item in exercises)
    minutes = sum(int(item["payload"].get("duration_min") or 0) for item in exercises)
    exercise_kcal = sum(float(item["payload"].get("calories_kcal") or 0) for item in exercises)
    meal_kcal = sum(float(item["payload"].get("calories_kcal") or item["payload"].get("calories") or 0) for item in meals)
    protein = sum(float(item["payload"].get("protein_g") or 0) for item in meals)
    sleep_hours = sleep["payload"].get("duration_hours") if sleep else None
    weight = body["payload"].get("weight_kg") if body else None
    return [
        ("活动步数", f"{steps:,} 步" if steps else "未记录", f"活动 {minutes} 分钟"),
        ("活动消耗", f"{exercise_kcal:g} kcal" if exercise_kcal else "未记录", "与步数分开统计"),
        ("饮食能量", f"{meal_kcal:g} kcal" if meal_kcal else f"{len(meals)} 餐", "来自已记录饮食"),
        ("蛋白质", f"{protein:g} g" if protein else "待补充", "用于营养与体成分趋势"),
        ("睡眠", f"{sleep_hours} 小时" if sleep_hours is not None else "未记录", "恢复证据"),
        ("体重", f"{weight} kg" if weight is not None else "未记录", "身体趋势基线"),
    ]


def _event_html(event: dict[str, Any]) -> str:
    color = {
        "exercise": "var(--accent)", "meal": "var(--amber)", "sleep": "var(--violet)",
        "body": "var(--cyan)", "mood": "var(--coral)", "symptom": "var(--coral)",
        "menstrual_cycle": "var(--violet)",
    }.get(event["event_type"], "var(--cyan)")
    return f'<article class="event" style="--event-color:{color}"><time>{html.escape(event["occurred_at"][11:16])}</time><div class="rail"><i></i></div><div><h3>{html.escape(EVENT_LABELS.get(event["event_type"], event["event_type"]))} · {html.escape(event_summary(event))}</h3><p>{html.escape(event.get("raw_text") or f"来源：{event.get("source") or "本地记录"}")}</p></div></article>'


def event_summary(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    event_type = event.get("event_type")
    if event_type == "exercise":
        parts = [payload.get("activity") or payload.get("exercise_type") or "运动"]
        if payload.get("steps"):
            parts.append(f"{payload['steps']} 步")
        if payload.get("duration_min"):
            parts.append(f"{payload['duration_min']} 分钟")
        return " · ".join(parts)
    if event_type == "meal":
        foods = payload.get("foods") or []
        food_text = "、".join(map(str, foods)) if isinstance(foods, list) else str(foods)
        parts = [payload.get("meal_type") or "饮食", food_text]
        calories = payload.get("calories") or payload.get("calories_kcal")
        if calories:
            parts.append(f"{calories} kcal")
        return " · ".join(str(item) for item in parts if item)
    if event_type == "sleep":
        return " · ".join(str(item) for item in [f"{payload.get('duration_hours')} 小时" if payload.get("duration_hours") is not None else None, payload.get("quality")] if item) or "睡眠记录"
    if event_type == "body":
        parts = []
        if payload.get("weight_kg") is not None:
            parts.append(f"体重 {payload['weight_kg']} kg")
        fat = payload.get("body_fat_percent") or payload.get("body_fat_pct")
        if fat is not None:
            parts.append(f"体脂 {fat}%")
        return " · ".join(parts) or "身体记录"
    if event_type == "mood":
        return str(payload.get("mood") or payload.get("feeling") or "感受记录")
    if event_type == "menstrual_cycle":
        parts = [payload.get("phase") or "周期记录"]
        if payload.get("cycle_day"):
            parts.append(f"第 {payload['cycle_day']} 天")
        return " · ".join(parts)
    return " · ".join(f"{key}: {value}" for key, value in list(payload.items())[:3]) or "已记录"


def _module_section(model: dict[str, Any]) -> str:
    rows = "".join(_module_html(module) for module in model["modules"].values())
    return f'<section><h2 class="section-title">维度评分</h2><div class="module-list">{rows}</div><p style="margin:14px 0 0;color:var(--muted);font-size:10px;line-height:1.6">缺失数据只降低置信度，不自动判定状态较差；分数用于个人趋势参考，不是医疗评价。</p></section>'


def _module_html(module: dict[str, Any]) -> str:
    basis = "".join(
        f'<i>{html.escape(str(item["label"]))} {item["score"]} · {html.escape(str(item["evidence"]))}</i>'
        for item in module.get("basis", [])
    ) or "<i>评分证据积累中</i>"
    score = module["score"] if module["score"] is not None else "--"
    return f'<div class="module"><span>{html.escape(module["label"])}</span><div class="track"><i style="width:{module["score"] or 0}%"></i></div><b>{score}</b><div class="module-detail">{html.escape(module["summary"])} · 数据置信度 {round((module.get("confidence") or 0) * 100)}%</div><div class="module-basis">{basis}</div></div>'


def _cycle_section(model: dict[str, Any]) -> str:
    cycle = model.get("cycle_support") or {}
    support = cycle.get("support") or {}
    if not cycle.get("enabled") or support.get("visible") is False:
        return ""
    evidence = {"personal": "个人历史", "learning": "积累中"}.get(support.get("evidence"), "一般参考")
    window = cycle.get("prediction_window")
    meta = ""
    if window:
        meta = f"预计经期 {cycle.get('predicted_next_start')} · 估算窗口 {window['start']} 至 {window['end']} · 置信度 {round((cycle.get('confidence') or 0) * 100)}%"
    return f'<section><h2 class="section-title">周期支持</h2><div class="cycle-support"><header><strong>{html.escape(str(support.get("title") or "周期规律积累中"))}</strong><span>{evidence}</span></header><p>{html.escape(str(support.get("note") or cycle.get("message") or ""))}</p><p>{html.escape(str(support.get("action") or "继续记录周期和主观感受。"))}</p><small>{html.escape(meta)}</small><small>{html.escape(str(cycle.get("disclaimer") or ""))}</small></div></section>'


def _relationship_section(model: dict[str, Any]) -> str:
    relationships = model.get("trend_analysis", {}).get("relationships", [])
    if not relationships:
        return ""
    cards = "".join(
        f'<article class="insight" style="--card-color:var(--cyan)"><span>关联线索 · {html.escape(str(item["confidence"]))}置信</span><h3>{html.escape(str(item["title"]))}</h3><p>{html.escape(str(item["summary"]))} {html.escape(str(item["caveat"]))}</p></article>'
        for item in relationships[:3]
    )
    return f'<section><h2 class="section-title">跨维度关联线索</h2><div class="insights">{cards}</div></section>'


def _period_section(model: dict[str, Any]) -> str:
    if model["period_type"] == "daily":
        missing = "、".join(model["data_completeness"]["missing"]) or "无"
        return f'<section><h2 class="section-title">记录完整度</h2><div class="change-grid"><div class="change"><span>已完成</span><b>{len(model["data_completeness"]["completed"])}/{len(model["data_completeness"]["required"])}</b><small>按个人设置计算</small></div><div class="change"><span>仍缺少</span><b>{len(model["data_completeness"]["missing"])}</b><small>{html.escape(missing)}</small></div></div></section>'
    if model["period_type"] == "weekly":
        cards = _true_trend_cards(model, ("steps", "exercise_min", "protein_g", "sleep_hours"))
        return f'<section><h2 class="section-title">本周真实指标变化</h2><div class="change-grid">{cards}</div></section>'
    trend_cards = _true_trend_cards(
        model, ("weight_kg", "body_fat_pct", "skeletal_muscle_kg", "protein_g")
    )
    if trend_cards:
        return f'<section><h2 class="section-title">本月关键变化</h2><div class="change-grid">{trend_cards}</div></section>'
    labels = {"weight_kg": ("体重", "kg"), "body_fat_pct": ("体脂", "%"), "body_fat_percent": ("体脂", "%"), "skeletal_muscle_kg": ("骨骼肌", "kg"), "waist_cm": ("腰围", "cm")}
    cards = []
    for key, item in model["body_change"].items():
        if key in labels and isinstance(item, dict) and "change" in item:
            label, unit = labels[key]
            cards.append(f'<div class="change"><span>{label}</span><b>{item["change"]:+.2f} {unit}</b><small>{item["first"]} → {item["latest"]}</small></div>')
    return f'<section><h2 class="section-title">身体变化</h2><div class="change-grid">{"".join(cards) or "<div class=\"metric\"><span>趋势证据</span><b>积累中</b><small>需要至少两次可比较记录</small></div>"}</div></section>'


def _true_trend_cards(model: dict[str, Any], keys: tuple[str, ...]) -> str:
    metrics = model.get("trend_analysis", {}).get("metrics", {})
    cards = []
    for key in keys:
        item = metrics.get(key)
        if not item:
            continue
        current = item.get("current")
        delta = item.get("delta")
        value = "--" if current is None else f"{current:g} {item['unit']}"
        note = "暂无前期对照" if delta is None else f"较前期 {delta:+g} {item['unit']} · {item['samples']} 样本"
        cards.append(
            f'<div class="change"><span>{html.escape(item["label"])}</span><b>{html.escape(value)}</b><small>{html.escape(note)}</small></div>'
        )
    return "".join(cards)


def _insight_section(model: dict[str, Any]) -> str:
    labels = {"achievement": "成就", "completion": "完成", "gap": "数据缺口", "risk": "优先关注", "explanation": "可能解释", "trend": "趋势", "correlation": "关联", "suggestion": "建议"}
    cards = "".join(
        f'<article class="insight" style="--card-color:{PALETTE.get(item["severity"], PALETTE["blue"])}"><span>{html.escape(labels.get(item["type"], item["type"]))}</span><h3>{html.escape(item["title"])}</h3><p>{html.escape(item["explanation"])}</p></article>'
        for item in model["insights"]
    )
    return f'<section><h2 class="section-title">值得注意</h2><div class="insights">{cards}</div></section>'


def _action_section(model: dict[str, Any]) -> str:
    actions = "".join(
        f'<article class="action"><header><strong>{html.escape(item["title"])}</strong><span>{html.escape(item["timing"])}</span></header><p>{html.escape(item["rationale"])}</p></article>'
        for item in model["actions"]
    )
    return f'<section><h2 class="section-title">下一步行动</h2><div class="actions">{actions}</div></section>'


def _report_title(model: dict[str, Any]) -> str:
    return {"daily": "BodyNote 日报", "weekly": "BodyNote 周报", "monthly": "BodyNote 月报"}[model["period_type"]]


def _period_label(model: dict[str, Any]) -> str:
    period = model["period"]
    if model["period_type"] == "monthly":
        return f"{model['period_key']} 月报"
    if period["start"] == period["end"]:
        return period["start"]
    return f"{period['start']} 至 {period['end']}"


def _kicker(model: dict[str, Any]) -> str:
    return {"daily": "TODAY SIGNAL · 每日状态", "weekly": "WEEKLY RHYTHM · 每周节奏", "monthly": "MONTHLY CHANGE · 每月变化"}[model["period_type"]]


def _hero_detail(model: dict[str, Any]) -> str:
    first = model.get("insights", [{}])[0].get("explanation")
    if first:
        return str(first)
    if model["period_type"] == "daily":
        return f"今天共有 {model['data_completeness']['event_count']} 条记录。"
    return "数据正在形成你的个人健康脉络。"
