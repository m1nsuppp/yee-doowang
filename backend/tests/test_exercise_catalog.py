import unittest

from pydantic import ValidationError

from yee_doowang_api.application.exercise_catalog import ExerciseCatalog
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog


class ExerciseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_exercise_catalog()

    def test_catalog_rejects_dangling_muscle_relationships(self) -> None:
        data = self.catalog.model_dump()
        data["exercises"][0]["primary_muscle_id"] = "missing-muscle"

        with self.assertRaises(ValidationError):
            ExerciseCatalog.model_validate(data)

    def test_catalog_rejects_duplicate_exercise_source_ids(self) -> None:
        data = self.catalog.model_dump()
        data["exercises"][1]["source_id"] = data["exercises"][0]["source_id"]

        with self.assertRaisesRegex(ValidationError, "source exercise IDs must be unique"):
            ExerciseCatalog.model_validate(data)
