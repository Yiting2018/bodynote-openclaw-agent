from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bodynote_agent.config import runtime_paths
from bodynote_agent.food_library import FoodLibraryService
from bodynote_agent.runtime import initialize
from bodynote_agent.service import CheckinService


NOW = datetime(2026, 7, 16, 8, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


class FoodLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "runtime"
        initialize(self.home)
        self.database = runtime_paths(self.home).database
        self.library = FoodLibraryService(self.database)
        self.checkins = CheckinService(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_dumplings(self) -> dict[str, object]:
        return self.library.add_food(
            {
                "title": "野人日记高蛋白水饺",
                "category": "product",
                "brand": "野人日记",
                "aliases": ["野人日记水饺", "水饺"],
                "default_serving": {"amount": 1, "unit": "袋", "label": "1 袋"},
                "nutrition_per_serving": {
                    "calories_kcal": 310,
                    "protein_g": 28,
                    "carbs_g": 42,
                    "fat_g": 5,
                },
                "source_type": "user_label",
            }
        )

    def test_brand_alias_populates_complete_meal_snapshot(self) -> None:
        food = self.add_dumplings()["food"]
        result = self.checkins.record_text("晚饭吃了野人日记水饺", now=NOW)

        self.assertTrue(result["ok"])
        payload = result["event"]["payload"]
        self.assertEqual(payload["foods"], ["野人日记高蛋白水饺"])
        self.assertEqual(payload["calories_kcal"], 310)
        self.assertEqual(payload["protein_g"], 28)
        self.assertEqual(payload["food_library"]["coverage"], "complete")
        self.assertEqual(payload["food_library"]["items"][0]["food_item_id"], food["id"])

    def test_partial_match_keeps_library_evidence_without_inventing_meal_totals(self) -> None:
        self.add_dumplings()
        result = self.checkins.record_text("晚饭吃了水饺和青菜", now=NOW)

        payload = result["event"]["payload"]
        self.assertEqual(payload["food_library"]["coverage"], "partial")
        self.assertNotIn("calories_kcal", payload)
        self.assertEqual(len(payload["food_library"]["items"]), 1)

    def test_template_uses_fixed_breakfast_and_preserves_historical_snapshot(self) -> None:
        powder = self.library.add_food(
            {
                "title": "乳清蛋白粉",
                "category": "supplement",
                "aliases": ["蛋白粉"],
                "default_serving": {"amount": 1, "unit": "勺", "label": "1 勺"},
                "nutrition_per_serving": {"calories_kcal": 120, "protein_g": 24, "carbs_g": 3, "fat_g": 2},
                "source_type": "user_label",
            }
        )["food"]
        oats = self.library.add_food(
            {
                "title": "燕麦片",
                "category": "food",
                "default_serving": {"amount": 1, "unit": "份", "label": "1 份"},
                "nutrition_per_serving": {"calories_kcal": 150, "protein_g": 5, "carbs_g": 27, "fat_g": 3},
                "source_type": "user_confirmed",
            }
        )["food"]
        template = self.library.add_template(
            {
                "title": "固定早餐",
                "meal_type": "breakfast",
                "aliases": ["早餐照旧"],
                "items": [{"food_id": powder["id"], "servings": 1}, {"food_id": oats["id"], "servings": 1}],
            }
        )["template"]

        result = self.checkins.record_text("早餐照旧", now=NOW)
        payload = result["event"]["payload"]
        self.assertEqual(payload["meal_type"], "breakfast")
        self.assertEqual(payload["food_library"]["resolution"], "template")
        self.assertEqual(payload["food_library"]["template"]["id"], template["id"])
        self.assertEqual(payload["calories_kcal"], 270)
        self.assertEqual(payload["protein_g"], 29)

        self.library.update_food(powder["id"], {"nutrition_per_serving": {"calories_kcal": 130, "protein_g": 30}})
        saved = self.checkins.get_event(result["event"]["id"])["event"]["payload"]
        self.assertEqual(saved["food_library"]["items"][0]["nutrition"]["protein_g"], 24)
        self.assertEqual(saved["protein_g"], 29)

    def test_alias_collisions_are_rejected(self) -> None:
        self.add_dumplings()
        with self.assertRaises(ValueError):
            self.library.add_food(
                {
                    "title": "另一款水饺",
                    "aliases": ["水饺"],
                    "nutrition_per_serving": {"calories_kcal": 300},
                }
            )


if __name__ == "__main__":
    unittest.main()
