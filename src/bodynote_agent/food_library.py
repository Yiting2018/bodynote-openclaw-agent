from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path
from typing import Any

from bodynote_agent.database import connect, new_id


NUTRIENT_FIELDS = ("calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")
FOOD_CATEGORIES = {"product", "food", "supplement"}
SOURCE_TYPES = {"user_label", "user_confirmed", "estimate"}
MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack", "unspecified"}


class FoodLibraryService:
    """Local, owner-confirmed food data and reusable meal templates."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def add_food(self, data: dict[str, Any]) -> dict[str, Any]:
        food = _normalize_food(data)
        food_id = new_id("food")
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO food_items (
                        id, profile_id, title, category, brand, default_serving_json,
                        nutrition_per_serving_json, source_type, notes, enabled
                    ) VALUES (?, 'owner', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        food_id, food["title"], food["category"], food["brand"],
                        _json(food["default_serving"]), _json(food["nutrition_per_serving"]),
                        food["source_type"], food["notes"], int(food["enabled"]),
                    ),
                )
                self._replace_aliases(connection, food_id, food["aliases"], food["title"])
        return {"ok": True, "food": self.get_food(food_id)}

    def update_food(self, food_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_food(food_id)
        if current is None:
            raise ValueError("没有找到这个食物条目。")
        merged = {**current, **patch}
        food = _normalize_food(merged)
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE food_items SET title = ?, category = ?, brand = ?,
                        default_serving_json = ?, nutrition_per_serving_json = ?,
                        source_type = ?, notes = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND id = ?
                    """,
                    (
                        food["title"], food["category"], food["brand"],
                        _json(food["default_serving"]), _json(food["nutrition_per_serving"]),
                        food["source_type"], food["notes"], int(food["enabled"]), food_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ValueError("没有找到这个食物条目。")
                self._replace_aliases(connection, food_id, food["aliases"], food["title"])
        return {"ok": True, "food": self.get_food(food_id)}

    def list_foods(self, *, enabled_only: bool = False) -> dict[str, Any]:
        clause = " AND enabled = 1" if enabled_only else ""
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                f"SELECT * FROM food_items WHERE profile_id = 'owner'{clause} ORDER BY enabled DESC, updated_at DESC"
            ).fetchall()
        foods = [self._serialize_food(row) for row in rows]
        return {"ok": True, "count": len(foods), "foods": foods}

    def get_food(self, food_id: str) -> dict[str, Any] | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT * FROM food_items WHERE profile_id = 'owner' AND id = ?", (food_id,)
            ).fetchone()
        return self._serialize_food(row) if row else None

    def set_food_enabled(self, food_id: str, enabled: bool) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE food_items SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE profile_id = 'owner' AND id = ?",
                    (int(enabled), food_id),
                )
        if cursor.rowcount == 0:
            raise ValueError("没有找到这个食物条目。")
        return {"ok": True, "food": self.get_food(food_id)}

    def add_template(self, data: dict[str, Any]) -> dict[str, Any]:
        template = self._normalize_template(data)
        template_id = new_id("meal_template")
        with closing(connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO meal_templates (id, profile_id, title, meal_type, aliases_json, notes, enabled)
                    VALUES (?, 'owner', ?, ?, ?, ?, ?)
                    """,
                    (template_id, template["title"], template["meal_type"], _json(template["aliases"]), template["notes"], int(template["enabled"])),
                )
                self._replace_template_items(connection, template_id, template["items"])
        return {"ok": True, "template": self.get_template(template_id)}

    def update_template(self, template_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_template(template_id)
        if current is None:
            raise ValueError("没有找到这个常用餐食。")
        template = self._normalize_template({**current, **patch})
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE meal_templates SET title = ?, meal_type = ?, aliases_json = ?, notes = ?,
                        enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE profile_id = 'owner' AND id = ?
                    """,
                    (template["title"], template["meal_type"], _json(template["aliases"]), template["notes"], int(template["enabled"]), template_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("没有找到这个常用餐食。")
                self._replace_template_items(connection, template_id, template["items"])
        return {"ok": True, "template": self.get_template(template_id)}

    def list_templates(self, *, enabled_only: bool = False) -> dict[str, Any]:
        clause = " AND enabled = 1" if enabled_only else ""
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                f"SELECT * FROM meal_templates WHERE profile_id = 'owner'{clause} ORDER BY enabled DESC, updated_at DESC"
            ).fetchall()
        templates = [self._serialize_template(row) for row in rows]
        return {"ok": True, "count": len(templates), "templates": templates}

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT * FROM meal_templates WHERE profile_id = 'owner' AND id = ?", (template_id,)
            ).fetchone()
        return self._serialize_template(row) if row else None

    def set_template_enabled(self, template_id: str, enabled: bool) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    "UPDATE meal_templates SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE profile_id = 'owner' AND id = ?",
                    (int(enabled), template_id),
                )
        if cursor.rowcount == 0:
            raise ValueError("没有找到这个常用餐食。")
        return {"ok": True, "template": self.get_template(template_id)}

    def resolve_text(self, text: str) -> dict[str, Any]:
        normalized = _normalize_alias(text)
        template = self._matching_template(normalized)
        if template:
            return {"ok": True, "match": "template", "template": template}
        matches = self._matching_foods(normalized)
        return {"ok": True, "match": "food" if matches else "none", "foods": matches}

    def enrich_meal(self, payload: dict[str, Any], raw_text: str) -> dict[str, Any]:
        """Attach immutable library snapshots; only complete matches populate meal totals."""
        resolution = self.resolve_text(raw_text)
        enriched = dict(payload)
        if resolution["match"] == "template":
            template = resolution["template"]
            snapshots = [_item_snapshot(item["food"], item["servings"], matched_alias=template["title"]) for item in template["items"]]
            self._apply_complete_snapshot(enriched, snapshots)
            enriched["foods"] = [item["title"] for item in snapshots]
            enriched["meal_type"] = payload.get("meal_type") if payload.get("meal_type") not in {None, "unspecified"} else template["meal_type"]
            enriched["food_library"] = {
                "resolution": "template", "template": {"id": template["id"], "title": template["title"]},
                "coverage": "complete", "items": snapshots,
            }
            return enriched

        original_foods = [str(item).strip() for item in payload.get("foods", []) if str(item).strip()]
        snapshots = []
        matched_count = 0
        for food_text in original_foods:
            candidates = self._matching_foods(_normalize_alias(food_text))
            if candidates:
                item = candidates[0]
                matched_count += 1
                snapshots.append(_item_snapshot(item["food"], _servings_from_text(food_text, item["food"]), matched_alias=item["matched_alias"]))
        if not snapshots:
            return enriched
        coverage = "complete" if matched_count == len(original_foods) else "partial"
        enriched["food_library"] = {"resolution": "food", "coverage": coverage, "items": snapshots}
        if coverage == "complete":
            self._apply_complete_snapshot(enriched, snapshots)
            enriched["foods"] = [item["title"] for item in snapshots]
        return enriched

    def _apply_complete_snapshot(self, payload: dict[str, Any], snapshots: list[dict[str, Any]]) -> None:
        totals = {field: round(sum(float(item["nutrition"].get(field, 0)) for item in snapshots), 2) for field in NUTRIENT_FIELDS}
        for field, value in totals.items():
            payload.setdefault(field, value)

    def _matching_foods(self, normalized_text: str) -> list[dict[str, Any]]:
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT a.alias, a.normalized_alias, f.* FROM food_aliases a
                JOIN food_items f ON f.id = a.food_item_id
                WHERE a.profile_id = 'owner' AND f.enabled = 1
                """
            ).fetchall()
        matches: list[dict[str, Any]] = []
        for row in rows:
            alias = str(row["normalized_alias"])
            if alias and alias in normalized_text:
                matches.append({"matched_alias": alias, "food": self._serialize_food(row)})
        matches.sort(key=lambda item: len(item["matched_alias"]), reverse=True)
        return _without_overlapping_matches(matches)

    def _matching_template(self, normalized_text: str) -> dict[str, Any] | None:
        for template in self.list_templates(enabled_only=True)["templates"]:
            aliases = [_normalize_alias(template["title"]), *[_normalize_alias(value) for value in template["aliases"]]]
            if any(alias and alias in normalized_text for alias in aliases):
                return template
        return None

    def _replace_aliases(self, connection: Any, food_id: str, aliases: list[str], title: str) -> None:
        values = _dedupe([title, *aliases])
        for alias in values:
            conflict = connection.execute(
                """
                SELECT food_item_id FROM food_aliases
                WHERE profile_id = 'owner' AND normalized_alias = ? AND food_item_id != ?
                """,
                (_normalize_alias(alias), food_id),
            ).fetchone()
            if conflict is not None:
                raise ValueError(f"别名“{alias}”已属于另一个食物条目，请先确认品牌或修改别名。")
        connection.execute("DELETE FROM food_aliases WHERE profile_id = 'owner' AND food_item_id = ?", (food_id,))
        for alias in values:
            connection.execute(
                "INSERT INTO food_aliases (id, profile_id, food_item_id, alias, normalized_alias) VALUES (?, 'owner', ?, ?, ?)",
                (new_id("food_alias"), food_id, alias, _normalize_alias(alias)),
            )

    def _replace_template_items(self, connection: Any, template_id: str, items: list[dict[str, Any]]) -> None:
        connection.execute("DELETE FROM meal_template_items WHERE template_id = ?", (template_id,))
        for position, item in enumerate(items):
            found = connection.execute(
                "SELECT id FROM food_items WHERE profile_id = 'owner' AND id = ?", (item["food_id"],)
            ).fetchone()
            if found is None:
                raise ValueError(f"常用餐食引用的食物不存在：{item['food_id']}。")
            connection.execute(
                "INSERT INTO meal_template_items (id, template_id, food_item_id, servings, position) VALUES (?, ?, ?, ?, ?)",
                (new_id("meal_template_item"), template_id, item["food_id"], item["servings"], position),
            )

    def _serialize_food(self, row: Any) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            alias_rows = connection.execute(
                "SELECT alias FROM food_aliases WHERE profile_id = 'owner' AND food_item_id = ? ORDER BY created_at", (row["id"],)
            ).fetchall()
        return {
            "id": row["id"], "title": row["title"], "category": row["category"], "brand": row["brand"],
            "aliases": [item["alias"] for item in alias_rows if item["alias"] != row["title"]],
            "default_serving": json.loads(row["default_serving_json"] or "{}"),
            "nutrition_per_serving": json.loads(row["nutrition_per_serving_json"] or "{}"),
            "source_type": row["source_type"], "notes": row["notes"], "enabled": bool(row["enabled"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _serialize_template(self, row: Any) -> dict[str, Any]:
        with closing(connect(self.database_path)) as connection:
            item_rows = connection.execute(
                """
                SELECT i.servings, f.* FROM meal_template_items i
                JOIN food_items f ON f.id = i.food_item_id
                WHERE i.template_id = ? ORDER BY i.position
                """, (row["id"],)
            ).fetchall()
        return {
            "id": row["id"], "title": row["title"], "meal_type": row["meal_type"],
            "aliases": json.loads(row["aliases_json"] or "[]"), "notes": row["notes"], "enabled": bool(row["enabled"]),
            "items": [{"food_id": item["id"], "servings": float(item["servings"]), "food": self._serialize_food(item)} for item in item_rows],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def _normalize_template(self, data: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "meal_type", "aliases", "notes", "enabled", "items", "id", "created_at", "updated_at"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"不支持的常用餐食字段：{', '.join(unknown)}。")
        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("常用餐食需要 title。")
        meal_type = str(data.get("meal_type") or "unspecified").strip()
        if meal_type not in MEAL_TYPES:
            raise ValueError("meal_type 必须是 breakfast、lunch、dinner、snack 或 unspecified。")
        aliases = _strings(data.get("aliases", []), "aliases")
        items = data.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("常用餐食至少需要一项 items。")
        normalized_items = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("items 必须是对象数组。")
            food_id = str(item.get("food_id") or "").strip()
            try:
                servings = float(item.get("servings", 1))
            except (TypeError, ValueError) as error:
                raise ValueError("items.servings 必须是数字。") from error
            if not food_id or not 0 < servings <= 100:
                raise ValueError("items 需要有效 food_id，且 servings 必须在 0 到 100 之间。")
            normalized_items.append({"food_id": food_id, "servings": servings})
        return {"title": title, "meal_type": meal_type, "aliases": aliases, "notes": str(data.get("notes") or "").strip() or None, "enabled": bool(data.get("enabled", True)), "items": normalized_items}


def _normalize_food(data: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "category", "brand", "aliases", "default_serving", "nutrition_per_serving", "source_type", "notes", "enabled", "id", "created_at", "updated_at"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"不支持的食物库字段：{', '.join(unknown)}。")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("食物条目需要 title。")
    category = str(data.get("category") or "product").strip()
    if category not in FOOD_CATEGORIES:
        raise ValueError("category 必须是 product、food 或 supplement。")
    source_type = str(data.get("source_type") or "user_confirmed").strip()
    if source_type not in SOURCE_TYPES:
        raise ValueError("source_type 必须是 user_label、user_confirmed 或 estimate。")
    serving = data.get("default_serving") or {"amount": 1, "unit": "份"}
    if not isinstance(serving, dict):
        raise ValueError("default_serving 必须是对象。")
    try:
        amount = float(serving.get("amount", 1))
    except (TypeError, ValueError) as error:
        raise ValueError("default_serving.amount 必须是数字。") from error
    if not 0 < amount <= 10000:
        raise ValueError("default_serving.amount 必须在 0 到 10000 之间。")
    unit = str(serving.get("unit") or "份").strip()
    if not unit:
        raise ValueError("default_serving.unit 不能为空。")
    nutrition = _nutrition(data.get("nutrition_per_serving"))
    if not nutrition:
        raise ValueError("nutrition_per_serving 至少需要一项营养数值。")
    return {
        "title": title, "category": category, "brand": str(data.get("brand") or "").strip() or None,
        "aliases": _strings(data.get("aliases", []), "aliases"),
        "default_serving": {"amount": amount, "unit": unit, "label": str(serving.get("label") or f"{amount:g}{unit}").strip()},
        "nutrition_per_serving": nutrition, "source_type": source_type,
        "notes": str(data.get("notes") or "").strip() or None, "enabled": bool(data.get("enabled", True)),
    }


def _nutrition(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("nutrition_per_serving 必须是对象。")
    unknown = sorted(set(value) - set(NUTRIENT_FIELDS))
    if unknown:
        raise ValueError(f"不支持的营养字段：{', '.join(unknown)}。")
    normalized = {}
    for field, item in value.items():
        try:
            number = float(item)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field} 必须是数字。") from error
        if not 0 <= number <= 100000:
            raise ValueError(f"{field} 超出合理范围。")
        normalized[field] = number
    return normalized


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} 必须是字符串数组。")
    return _dedupe([item.strip() for item in value if item.strip()])


def _item_snapshot(food: dict[str, Any], servings: float, *, matched_alias: str) -> dict[str, Any]:
    nutrition = {field: round(float(value) * servings, 2) for field, value in food["nutrition_per_serving"].items()}
    return {
        "food_item_id": food["id"], "title": food["title"], "brand": food["brand"], "matched_alias": matched_alias,
        "servings": servings, "serving": food["default_serving"], "nutrition": nutrition,
        "source_type": food["source_type"], "library_updated_at": food["updated_at"],
    }


def _servings_from_text(food_text: str, food: dict[str, Any]) -> float:
    unit = re.escape(str(food["default_serving"].get("unit") or "份"))
    match = re.search(rf"(\d+(?:\.\d+)?)\s*{unit}", food_text)
    if not match:
        return 1.0
    amount = float(match.group(1))
    base = float(food["default_serving"].get("amount") or 1)
    return round(amount / base, 3)


def _without_overlapping_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_food_ids: set[str] = set()
    result = []
    for item in matches:
        food_id = item["food"]["id"]
        if food_id not in seen_food_ids:
            seen_food_ids.add(food_id)
            result.append(item)
    return result


def _normalize_alias(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = _normalize_alias(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
