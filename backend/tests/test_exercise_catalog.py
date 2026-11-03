import hashlib
import unittest

from pydantic import ValidationError

from yee_doowang_api.application.exercise_catalog import ExerciseCatalog
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog

# SHA-256 of lexicographically sorted pinned-source IDs joined with newlines.
_PINNED_SOURCE_ID_COUNT = 1324
_PINNED_SOURCE_IDS_SHA256 = (
    "eab8eae6cfd9553f82d2ff3d6c2bcd66390e43772fd835d2e5d63f6b13640bdb"
)


class ExerciseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_exercise_catalog()

    def test_catalog_import_matches_all_pinned_source_ids(self) -> None:
        source_ids = [exercise.source_id for exercise in self.catalog.exercises]

        self.assertEqual(len(source_ids), _PINNED_SOURCE_ID_COUNT)
        self.assertEqual(len(set(source_ids)), _PINNED_SOURCE_ID_COUNT)
        self.assertEqual(
            hashlib.sha256("\n".join(sorted(source_ids)).encode()).hexdigest(),
            _PINNED_SOURCE_IDS_SHA256,
        )

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

    def test_catalog_rejects_korean_alias_colliding_with_another_muscle(self) -> None:
        data = self.catalog.model_dump()
        chest = next(muscle for muscle in data["muscles"] if muscle["id"] == "chest")
        chest["aliases_ko"] = ["삼두근"]

        with self.assertRaisesRegex(
            ValidationError,
            "Korean muscle names and aliases must be unique",
        ):
            ExerciseCatalog.model_validate(data)
