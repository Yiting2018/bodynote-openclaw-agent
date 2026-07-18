from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from bodynote_agent.analytics import HealthAnalysisService
from bodynote_agent.config import runtime_paths
from bodynote_agent.food_library import FoodLibraryService
from bodynote_agent.gap_check import GapCheckService
from bodynote_agent import __version__
from bodynote_agent.maintenance import BackupService, PrivacyAuditService, ReleaseService
from bodynote_agent.preferences import OnboardingService
from bodynote_agent.reference_library import ReferenceLibraryService
from bodynote_agent.runtime import initialize, status
from bodynote_agent.reports import ReportService
from bodynote_agent.schedule_plan import SchedulePlanService
from bodynote_agent.service import CheckinService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bodynote-agent",
        description="Local-first BodyNote workflow runtime for OpenClaw.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        help="Runtime directory. Defaults to BODYNOTE_HOME or ~/.bodynote.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create local config and SQLite storage.")

    status_parser = subparsers.add_parser("status", help="Inspect local runtime state.")
    status_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    checkin_parser = subparsers.add_parser("checkin", help="Record one health event.")
    checkin_input = checkin_parser.add_mutually_exclusive_group(required=True)
    checkin_input.add_argument("--text", help="Natural-language health record.")
    checkin_input.add_argument("--input", type=Path, help="Structured event JSON file.")
    checkin_parser.add_argument("--source", default="openclaw")
    checkin_parser.add_argument("--idempotency-key")
    checkin_parser.add_argument("--context", type=Path, help="Optional source-context JSON file.")
    checkin_parser.add_argument("--json", action="store_true")

    events_parser = subparsers.add_parser("events", help="List local health events.")
    events_parser.add_argument("--date", help="Filter by YYYY-MM-DD.")
    events_parser.add_argument("--type", dest="event_type")
    events_parser.add_argument("--limit", type=int, default=50)
    events_parser.add_argument("--include-deleted", action="store_true")
    events_parser.add_argument("--json", action="store_true")

    event_parser = subparsers.add_parser("event", help="Inspect or change one event.")
    event_subparsers = event_parser.add_subparsers(dest="event_command", required=True)

    show_parser = event_subparsers.add_parser("show", help="Show one event.")
    show_parser.add_argument("event_id")
    show_parser.add_argument("--include-deleted", action="store_true")
    show_parser.add_argument("--json", action="store_true")

    update_parser = event_subparsers.add_parser("update", help="Apply a structured JSON patch.")
    update_parser.add_argument("event_id")
    update_parser.add_argument("--input", type=Path, required=True)
    update_parser.add_argument("--json", action="store_true")

    delete_parser = event_subparsers.add_parser("delete", help="Soft-delete one event.")
    delete_parser.add_argument("event_id")
    delete_parser.add_argument("--confirm", action="store_true")
    delete_parser.add_argument("--json", action="store_true")

    onboarding_parser = subparsers.add_parser(
        "onboarding", help="Inspect or configure the single owner profile."
    )
    onboarding_subparsers = onboarding_parser.add_subparsers(
        dest="onboarding_command", required=True
    )
    onboarding_status = onboarding_subparsers.add_parser(
        "status", help="Show first-use setup state."
    )
    onboarding_status.add_argument("--json", action="store_true")
    onboarding_configure = onboarding_subparsers.add_parser(
        "configure", help="Apply first-use settings from JSON."
    )
    onboarding_configure.add_argument("--input", type=Path, required=True)
    onboarding_configure.add_argument("--json", action="store_true")

    gap_parser = subparsers.add_parser(
        "gap-check", help="Find missing records before the daily report."
    )
    gap_parser.add_argument("--date", help="Target local date, YYYY-MM-DD.")
    gap_parser.add_argument("--json", action="store_true")

    schedule_parser = subparsers.add_parser(
        "schedule", help="Build OpenClaw cron installation instructions."
    )
    schedule_subparsers = schedule_parser.add_subparsers(
        dest="schedule_command", required=True
    )
    schedule_plan = schedule_subparsers.add_parser(
        "plan", help="Show cron jobs without installing them."
    )
    schedule_plan.add_argument("--json", action="store_true")

    analyze_parser = subparsers.add_parser(
        "analyze", help="Build deterministic daily, weekly, or monthly health analysis."
    )
    analyze_parser.add_argument(
        "--type", dest="period_type", choices=("daily", "weekly", "monthly"), required=True
    )
    analyze_parser.add_argument(
        "--period", help="Daily/weekly: YYYY-MM-DD. Monthly: YYYY-MM."
    )
    analyze_parser.add_argument("--json", action="store_true")

    report_parser = subparsers.add_parser(
        "report", help="Generate or list local health report artifacts."
    )
    report_subparsers = report_parser.add_subparsers(
        dest="report_command", required=True
    )
    report_generate = report_subparsers.add_parser(
        "generate", help="Generate one report idempotently."
    )
    report_generate.add_argument(
        "--type", dest="report_type", choices=("daily", "weekly", "monthly"), required=True
    )
    report_generate.add_argument("--period")
    report_generate.add_argument(
        "--formats", help="Comma-separated: html,png,pdf,json."
    )
    report_generate.add_argument(
        "--scheduled", action="store_true", help="Apply scheduled-run guards."
    )
    report_generate.add_argument(
        "--delivery-dir",
        type=Path,
        help="Copy sendable artifacts into an OpenClaw workspace directory.",
    )
    report_generate.add_argument("--json", action="store_true")
    report_list = report_subparsers.add_parser("list", help="List generated reports.")
    report_list.add_argument("--limit", type=int, default=50)
    report_list.add_argument("--json", action="store_true")

    dashboard_parser = subparsers.add_parser(
        "dashboard", help="Build the static local health cockpit."
    )
    dashboard_subparsers = dashboard_parser.add_subparsers(
        dest="dashboard_command", required=True
    )
    dashboard_build = dashboard_subparsers.add_parser(
        "build", help="Refresh dashboard/index.html."
    )
    dashboard_build.add_argument("--date", help="Daily model date, YYYY-MM-DD.")
    dashboard_build.add_argument("--json", action="store_true")

    reference_parser = subparsers.add_parser(
        "reference", help="Manage structured notes extracted from owner-approved guides."
    )
    reference_subparsers = reference_parser.add_subparsers(
        dest="reference_command", required=True
    )
    reference_add = reference_subparsers.add_parser("add")
    reference_add.add_argument("--input", type=Path, required=True)
    reference_add.add_argument("--json", action="store_true")
    reference_list = reference_subparsers.add_parser("list")
    reference_list.add_argument("--enabled-only", action="store_true")
    reference_list.add_argument("--json", action="store_true")
    for command in ("enable", "disable"):
        item = reference_subparsers.add_parser(command)
        item.add_argument("guide_id")
        item.add_argument("--json", action="store_true")

    food_parser = subparsers.add_parser(
        "food", help="Manage owner-confirmed food and product nutrition entries."
    )
    food_subparsers = food_parser.add_subparsers(dest="food_command", required=True)
    food_add = food_subparsers.add_parser("add")
    food_add.add_argument("--input", type=Path, required=True)
    food_add.add_argument("--json", action="store_true")
    food_list = food_subparsers.add_parser("list")
    food_list.add_argument("--enabled-only", action="store_true")
    food_list.add_argument("--json", action="store_true")
    food_update = food_subparsers.add_parser("update")
    food_update.add_argument("food_id")
    food_update.add_argument("--input", type=Path, required=True)
    food_update.add_argument("--json", action="store_true")
    food_resolve = food_subparsers.add_parser("resolve")
    food_resolve.add_argument("--text", required=True)
    food_resolve.add_argument("--json", action="store_true")
    for command in ("enable", "disable"):
        item = food_subparsers.add_parser(command)
        item.add_argument("food_id")
        item.add_argument("--json", action="store_true")

    template_parser = subparsers.add_parser(
        "meal-template", help="Manage reusable owner meal combinations."
    )
    template_subparsers = template_parser.add_subparsers(
        dest="meal_template_command", required=True
    )
    template_add = template_subparsers.add_parser("add")
    template_add.add_argument("--input", type=Path, required=True)
    template_add.add_argument("--json", action="store_true")
    template_list = template_subparsers.add_parser("list")
    template_list.add_argument("--enabled-only", action="store_true")
    template_list.add_argument("--json", action="store_true")
    template_update = template_subparsers.add_parser("update")
    template_update.add_argument("template_id")
    template_update.add_argument("--input", type=Path, required=True)
    template_update.add_argument("--json", action="store_true")
    for command in ("enable", "disable"):
        item = template_subparsers.add_parser(command)
        item.add_argument("template_id")
        item.add_argument("--json", action="store_true")

    maintenance_parser = subparsers.add_parser(
        "maintenance", help="Run schema migrations and maintenance checks."
    )
    maintenance_subparsers = maintenance_parser.add_subparsers(
        dest="maintenance_command", required=True
    )
    maintenance_migrate = maintenance_subparsers.add_parser(
        "migrate", help="Apply all schema migrations idempotently."
    )
    maintenance_migrate.add_argument("--json", action="store_true")

    backup_parser = subparsers.add_parser(
        "backup", help="Create, verify, or restore an owner backup."
    )
    backup_subparsers = backup_parser.add_subparsers(
        dest="backup_command", required=True
    )
    backup_create = backup_subparsers.add_parser("create")
    backup_create.add_argument("--output", type=Path)
    backup_create.add_argument("--json", action="store_true")
    backup_verify = backup_subparsers.add_parser("verify")
    backup_verify.add_argument("backup", type=Path)
    backup_verify.add_argument("--json", action="store_true")
    backup_restore = backup_subparsers.add_parser("restore")
    backup_restore.add_argument("backup", type=Path)
    backup_restore.add_argument("--confirm", action="store_true")
    backup_restore.add_argument("--json", action="store_true")

    privacy_parser = subparsers.add_parser("privacy", help="Audit local privacy boundaries.")
    privacy_subparsers = privacy_parser.add_subparsers(
        dest="privacy_command", required=True
    )
    privacy_audit = privacy_subparsers.add_parser("audit")
    privacy_audit.add_argument("--project-root", type=Path)
    privacy_audit.add_argument("--json", action="store_true")

    release_parser = subparsers.add_parser("release", help="Build a privacy-checked release archive.")
    release_subparsers = release_parser.add_subparsers(
        dest="release_command", required=True
    )
    release_build = release_subparsers.add_parser("build")
    release_build.add_argument("--project-root", type=Path)
    release_build.add_argument("--output", type=Path)
    release_build.add_argument("--version", default=__version__)
    release_build.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        result = initialize(args.home)
        print(f"BodyNote initialized at {result['home']}")
        print(f"Config: {result['config']}")
        print(f"Database: {result['database']}")
        return 0

    if args.command == "status":
        result = status(args.home)
        if args.json:
            _print_json(result)
        else:
            database = result["database"]
            state = "ready" if database["exists"] and result["config_exists"] else "not initialized"
            print(f"BodyNote: {state}")
            print(f"Home: {result['home']}")
            print(f"Schema version: {database['schema_version']}")
            print(f"Events: {database['event_count']}")
        return 0

    paths = runtime_paths(args.home)
    if not paths.database.exists() or not paths.config.exists():
        return _fail(
            "BodyNote 尚未初始化，请先运行 bodynote-agent init。",
            json_output=getattr(args, "json", False),
        )
    try:
        if args.command == "onboarding":
            onboarding = OnboardingService(paths.database)
            if args.onboarding_command == "status":
                result = onboarding.status()
            else:
                result = onboarding.configure(_read_json_object(args.input))
            return _emit_result(result, json_output=args.json)

        if args.command == "gap-check":
            result = GapCheckService(paths.database).check(args.date)
            return _emit_result(result, json_output=args.json)

        if args.command == "schedule":
            result = SchedulePlanService(paths.database, paths.home).plan()
            return _emit_result(result, json_output=args.json)

        if args.command == "analyze":
            result = HealthAnalysisService(paths.database).analyze(
                args.period_type, args.period
            )
            return _emit_result(result, json_output=args.json)

        if args.command == "report":
            reports = ReportService(paths.database, paths.reports)
            if args.report_command == "list":
                result = reports.list_reports(limit=args.limit)
            else:
                formats = (
                    [item.strip() for item in args.formats.split(",") if item.strip()]
                    if args.formats
                    else None
                )
                result = reports.generate(
                    args.report_type,
                    args.period,
                    formats=formats,
                    scheduled=args.scheduled,
                    delivery_dir=args.delivery_dir,
                )
            return _emit_result(result, json_output=args.json)

        if args.command == "dashboard":
            reports = ReportService(paths.database, paths.reports)
            model = HealthAnalysisService(paths.database).analyze(
                "daily", args.date
            )
            if not model.get("ok"):
                return _emit_result(model, json_output=args.json)
            dashboard = reports.build_dashboard(model)
            result = {"ok": True, "dashboard": str(dashboard)}
            return _emit_result(result, json_output=args.json)

        if args.command == "reference":
            library = ReferenceLibraryService(paths.database)
            if args.reference_command == "add":
                result = library.add(_read_json_object(args.input))
            elif args.reference_command == "list":
                result = library.list(enabled_only=args.enabled_only)
            else:
                result = library.set_enabled(
                    args.guide_id, args.reference_command == "enable"
                )
            return _emit_result(result, json_output=args.json)

        if args.command == "food":
            library = FoodLibraryService(paths.database)
            if args.food_command == "add":
                result = library.add_food(_read_json_object(args.input))
            elif args.food_command == "list":
                result = library.list_foods(enabled_only=args.enabled_only)
            elif args.food_command == "update":
                result = library.update_food(args.food_id, _read_json_object(args.input))
            elif args.food_command == "resolve":
                result = library.resolve_text(args.text)
            else:
                result = library.set_food_enabled(
                    args.food_id, args.food_command == "enable"
                )
            return _emit_result(result, json_output=args.json)

        if args.command == "meal-template":
            library = FoodLibraryService(paths.database)
            if args.meal_template_command == "add":
                result = library.add_template(_read_json_object(args.input))
            elif args.meal_template_command == "list":
                result = library.list_templates(enabled_only=args.enabled_only)
            elif args.meal_template_command == "update":
                result = library.update_template(
                    args.template_id, _read_json_object(args.input)
                )
            else:
                result = library.set_template_enabled(
                    args.template_id, args.meal_template_command == "enable"
                )
            return _emit_result(result, json_output=args.json)

        if args.command == "maintenance":
            initialize(paths.home)
            result = status(paths.home)
            result["ok"] = True
            result["migrated"] = True
            return _emit_result(result, json_output=args.json)

        if args.command == "backup":
            backups = BackupService(paths)
            if args.backup_command == "create":
                result = backups.create(args.output)
            elif args.backup_command == "verify":
                result = backups.verify(args.backup)
            else:
                if not args.confirm:
                    return _fail("恢复备份需要明确传入 --confirm。", json_output=args.json)
                result = backups.restore(args.backup)
            return _emit_result(result, json_output=args.json)

        project_root = Path(__file__).resolve().parents[2]
        if args.command == "privacy":
            result = PrivacyAuditService(
                paths, args.project_root or project_root
            ).audit()
            return _emit_result(result, json_output=args.json)

        if args.command == "release":
            root = (args.project_root or project_root).resolve()
            output = args.output or (root / "dist")
            result = ReleaseService(root, paths).build(output, args.version)
            return _emit_result(result, json_output=args.json)

        service = CheckinService(paths.database)
        if args.command == "checkin":
            if args.input:
                payload = _read_json_object(args.input)
                payload.setdefault("source", args.source)
                if args.idempotency_key:
                    payload["idempotency_key"] = args.idempotency_key
                result = service.record_structured(payload)
            else:
                context = _read_json_object(args.context) if args.context else {}
                result = service.record_text(
                    args.text,
                    source=args.source,
                    source_context=context,
                    idempotency_key=args.idempotency_key,
                )
            return _emit_result(result, json_output=args.json)

        if args.command == "events":
            result = service.list_events(
                date=args.date,
                event_type=args.event_type,
                limit=args.limit,
                include_deleted=args.include_deleted,
            )
            return _emit_result(result, json_output=args.json)

        if args.event_command == "show":
            result = service.get_event(args.event_id, include_deleted=args.include_deleted)
        elif args.event_command == "update":
            result = service.update_event(args.event_id, _read_json_object(args.input))
        else:
            if not args.confirm:
                return _fail(
                    "删除需要明确传入 --confirm。",
                    json_output=args.json,
                )
            result = service.delete_event(args.event_id)
        return _emit_result(result, json_output=args.json)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        return _fail(str(error), json_output=getattr(args, "json", False))


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须包含一个 JSON object。")
    return payload


def _emit_result(result: dict[str, Any], *, json_output: bool) -> int:
    if json_output:
        _print_json(result)
    elif isinstance(result.get("summary"), str):
        print(result["summary"])
        if result.get("follow_up_question"):
            print(result["follow_up_question"])
    elif "events" in result:
        print(f"共 {result['count']} 条记录。")
        for event in result["events"]:
            print(f"{event['id']}  {event['occurred_at']}  {event['event_type']}")
    elif result.get("event"):
        event = result["event"]
        print(f"{event['id']}  {event['occurred_at']}  {event['event_type']}")
    elif result.get("deleted"):
        print(f"已删除记录 {result['event_id']}。")
    elif "onboarding_completed" in result and "profile" in result:
        state = "已完成" if result["onboarding_completed"] else "未完成"
        print(f"首次设置：{state}")
        print(f"时区：{result['profile']['timezone']}")
        if result["missing_setup_fields"]:
            print(f"待补设置：{', '.join(result['missing_setup_fields'])}")
    elif "prompt" in result:
        print(result["prompt"])
    elif "jobs" in result:
        for job in result["jobs"]:
            if job["ready"]:
                print(job["install_command"])
            else:
                print(f"{job['name']}：待实现（{job['blocker']}）")
    elif "health_score" in result and "summary" in result:
        print(result["summary"]["headline"])
        print(f"健康分：{result['health_score'] if result['health_score'] is not None else '暂无'}")
        print(f"数据置信度：{round(result['confidence'] * 100)}%")
    elif "dashboard" in result:
        print(result["dashboard"])
    elif "reports" in result:
        print(f"共 {result['count']} 份报告。")
        for report in result["reports"]:
            print(f"{report['report_type']}  {report['period_key']}  {report['status']}")
    elif "guides" in result:
        print(f"共 {result['count']} 份参考指南。")
        for guide in result["guides"]:
            state = "启用" if guide["enabled"] else "停用"
            print(f"{guide['id']}  {guide['title']}  {state}")
    elif "guide" in result:
        print(f"{result['guide']['title']}  {'启用' if result['guide']['enabled'] else '停用'}")
    elif "foods" in result:
        print(f"共 {result['count']} 个食物条目。")
        for food in result["foods"]:
            print(f"{food['id']}  {food['title']}")
    elif "food" in result:
        print(f"{result['food']['title']}  {'启用' if result['food']['enabled'] else '停用'}")
    elif "templates" in result:
        print(f"共 {result['count']} 个常用餐食。")
        for template in result["templates"]:
            print(f"{template['id']}  {template['title']}")
    elif "template" in result:
        print(f"{result['template']['title']}  {'启用' if result['template']['enabled'] else '停用'}")
    elif "match" in result:
        print(f"食物库匹配：{result['match']}")
    elif result.get("backup") and result.get("restored"):
        print(f"已恢复备份：{result['backup']}")
        print(f"恢复前安全备份：{result['safety_backup']}")
    elif result.get("backup"):
        print(result["backup"])
    elif result.get("package"):
        print(result["package"])
    elif "findings" in result:
        print("隐私审计通过。" if result.get("passed") else "隐私审计发现高风险项。")
    elif not result.get("ok"):
        print(result.get("error") or "操作失败。", file=sys.stderr)
    return 0 if result.get("ok") else 2


def _fail(message: str, *, json_output: bool) -> int:
    result = {"ok": False, "error": message}
    if json_output:
        _print_json(result)
    else:
        print(message, file=sys.stderr)
    return 2


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
