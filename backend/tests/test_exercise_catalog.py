import unittest

from pydantic import ValidationError

from yee_doowang_api.application.exercise_catalog import (
    ExerciseCatalog,
    load_exercise_catalog,
)


class ExerciseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_exercise_catalog()

    def test_push_day_filters_by_primary_muscle_and_movement_pattern(self) -> None:
        exercises = self.catalog.find_exercises(
            workout_day_id="push_day",
            movement_pattern_id="horizontal_press",
        )
        source_ids = {exercise.source_id for exercise in exercises}

        self.assertIn("0025", source_ids)
        self.assertIn("0259", source_ids)
        self.assertNotIn("0060", source_ids)

    def test_bodyweight_filter_returns_only_bodyweight_options(self) -> None:
        exercises = self.catalog.find_exercises(
            workout_day_id="push_day",
            equipment_id="body_weight",
        )

        self.assertEqual(
            {exercise.source_id for exercise in exercises},
            {"0259", "0662"},
        )

    def test_secondary_muscle_does_not_qualify_exercise_for_a_day(self) -> None:
        data = self.catalog.model_dump()
        data["workout_days"][0]["focus_muscle_ids"] = ["chest"]
        chest_day_catalog = ExerciseCatalog.model_validate(data)

        exercises = chest_day_catalog.find_exercises(workout_day_id="push_day")
        source_ids = {exercise.source_id for exercise in exercises}

        self.assertIn("0025", source_ids)
        self.assertNotIn("0259", source_ids)

    def test_catalog_rejects_dangling_muscle_relationships(self) -> None:
        data = self.catalog.model_dump()
        data["exercises"][0]["primary_muscle_id"] = "missing-muscle"

        with self.assertRaises(ValidationError):
            ExerciseCatalog.model_validate(data)

    def test_unknown_workout_day_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown workout day"):
            self.catalog.find_exercises(workout_day_id="pull_day")
