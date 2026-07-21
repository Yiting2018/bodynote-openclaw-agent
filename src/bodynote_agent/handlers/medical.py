from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import HandlerResult, result


def parse_medical_report(text: str) -> HandlerResult | None:
    if not any(marker in text for marker in ("体检报告", "检查报告", "化验单", "检验报告", "医疗报告")):
        return None
    report_type = next((marker for marker in ("体检报告", "检查报告", "化验单", "检验报告", "医疗报告") if marker in text), "医疗报告")
    findings = []
    attention = re.search(r"(?:异常|需关注|超标)\s*[:：]?\s*(\d+)\s*项", text) or re.search(r"(\d+)\s*项\s*(?:异常|需关注|超标)", text)
    actions = re.search(r"(?:复查|后续建议)\s*[:：]?\s*(\d+)\s*项", text) or re.search(r"(\d+)\s*项\s*(?:复查|后续建议)", text)
    if attention:
        findings = [{"summary": "待查看报告中的关注项"} for _ in range(int(attention.group(1)))]
    action_candidates = []
    if actions:
        action_candidates = ["按报告建议确认后续事项" for _ in range(int(actions.group(1)))]
    payload = {"report_type": report_type, "findings": findings, "action_candidates": action_candidates}
    ambiguities = () if attention or actions else ("report_details",)
    return result("medical_report", payload, 0.86 if not ambiguities else 0.68,
                  required_fields=("report_type",), ambiguities=ambiguities,
                  follow_up="可以继续提供报告中的异常项和复查建议。" if ambiguities else None)
