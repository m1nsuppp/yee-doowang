import unittest

from yee_doowang_api.application.chat_models import EquipmentConstraint
from yee_doowang_api.application.exercise_catalog import ExerciseCatalog
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog
from yee_doowang_api.infrastructure.pyrewire_exercise_reasoner import (
    PyreWireExerciseReasoner,
)


class PyreWireExerciseReasonerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_exercise_catalog()

    async def test_bodyweight_push_day_uses_only_matching_catalog_exercises(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        exercises = await reasoner.recommend(
            workout_day_id="push_day",
            equipment_constraint=EquipmentConstraint(
                mode="specified",
                equipment_ids=["body_weight"],
            ),
        )

        focus_muscle_ids = next(
            set(day.focus_muscle_ids)
            for day in self.catalog.workout_days
            if day.id == "push_day"
        )
        expected_ids = {
            exercise.source_id
            for exercise in self.catalog.exercises
            if exercise.primary_muscle_id in focus_muscle_ids
            and exercise.equipment_id == "body_weight"
        }
        self.assertEqual({exercise.source_id for exercise in exercises}, expected_ids)

    async def test_unrestricted_push_day_includes_all_candidates_across_equipment(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        exercises = await reasoner.recommend(
            workout_day_id="push_day",
            equipment_constraint=EquipmentConstraint(
                mode="unrestricted",
                equipment_ids=[],
            ),
        )

        focus_muscle_ids = next(
            set(day.focus_muscle_ids)
            for day in self.catalog.workout_days
            if day.id == "push_day"
        )
        expected_ids = {
            exercise.source_id
            for exercise in self.catalog.exercises
            if exercise.primary_muscle_id in focus_muscle_ids
        }
        self.assertEqual({exercise.source_id for exercise in exercises}, expected_ids)
        self.assertLess(len(exercises), len(self.catalog.exercises))
        self.assertGreater(len({exercise.equipment_id for exercise in exercises}), 1)

    async def test_abs_day_matches_primary_abdominal_targets(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        exercises = await reasoner.recommend(
            workout_day_id="abs_day",
            equipment_constraint=EquipmentConstraint(
                mode="unrestricted",
                equipment_ids=[],
            ),
        )

        source_ids = {exercise.source_id for exercise in exercises}
        self.assertEqual(len(exercises), 169)
        self.assertIn("0002", source_ids)
        self.assertIn("0687", source_ids)
        self.assertNotIn("0025", source_ids)
        self.assertTrue(
            all(
                exercise.primary_muscle_id in {"abs", "lower_abs"}
                for exercise in exercises
            )
        )

    async def test_obliques_day_matches_secondary_muscles_when_configured(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        exercises = await reasoner.recommend(
            workout_day_id="obliques_day",
            equipment_constraint=EquipmentConstraint(
                mode="unrestricted",
                equipment_ids=[],
            ),
        )

        source_ids = {exercise.source_id for exercise in exercises}
        self.assertEqual(len(exercises), 72)
        self.assertIn("0002", source_ids)
        self.assertIn("0014", source_ids)
        self.assertNotIn("0025", source_ids)
        self.assertTrue(
            all(
                exercise.primary_muscle_id == "obliques"
                or "obliques" in exercise.secondary_muscle_ids
                for exercise in exercises
            )
        )

        bodyweight = await reasoner.recommend(
            workout_day_id="obliques_day",
            equipment_constraint=EquipmentConstraint(
                mode="specified",
                equipment_ids=["body_weight"],
            ),
        )
        self.assertIn("0002", {exercise.source_id for exercise in bodyweight})
        self.assertTrue(all(exercise.equipment_id == "body_weight" for exercise in bodyweight))

    async def test_secondary_muscle_does_not_qualify_an_exercise(self) -> None:
        data = self.catalog.model_dump()
        data["workout_days"][0]["focus_muscle_ids"] = ["chest"]
        chest_catalog = ExerciseCatalog.model_validate(data)
        reasoner = PyreWireExerciseReasoner(chest_catalog)

        exercises = await reasoner.recommend(
            workout_day_id="push_day",
            equipment_constraint=EquipmentConstraint(
                mode="specified",
                equipment_ids=["body_weight"],
            ),
        )

        expected_ids = {
            exercise.source_id
            for exercise in chest_catalog.exercises
            if exercise.primary_muscle_id == "chest"
            and exercise.equipment_id == "body_weight"
        }
        self.assertEqual({exercise.source_id for exercise in exercises}, expected_ids)
        secondary_only_ids = {
            exercise.source_id
            for exercise in chest_catalog.exercises
            if exercise.primary_muscle_id != "chest"
            and "chest" in exercise.secondary_muscle_ids
            and exercise.equipment_id == "body_weight"
        }
        self.assertTrue(secondary_only_ids)
        self.assertFalse(
            secondary_only_ids & {exercise.source_id for exercise in exercises}
        )

    async def test_unknown_workout_day_is_rejected(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        with self.assertRaisesRegex(ValueError, "Unknown workout day"):
            await reasoner.recommend(
                workout_day_id="pull_day",
                equipment_constraint=EquipmentConstraint(
                    mode="specified",
                    equipment_ids=["body_weight"],
                ),
            )

    async def test_unknown_equipment_is_rejected(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        with self.assertRaisesRegex(ValueError, "Unknown equipment"):
            await reasoner.recommend(
                workout_day_id="push_day",
                equipment_constraint=EquipmentConstraint(
                    mode="specified",
                    equipment_ids=["unregistered"],
                ),
            )
