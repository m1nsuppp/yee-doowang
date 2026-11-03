import unittest

from yee_doowang_api.application.chat import EquipmentConstraint
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

        self.assertEqual(
            {exercise.source_id for exercise in exercises},
            {"0259", "0662"},
        )

    async def test_unrestricted_push_day_includes_each_catalog_equipment(self) -> None:
        reasoner = PyreWireExerciseReasoner(self.catalog)

        exercises = await reasoner.recommend(
            workout_day_id="push_day",
            equipment_constraint=EquipmentConstraint(
                mode="unrestricted",
                equipment_ids=[],
            ),
        )

        self.assertEqual(
            {exercise.source_id for exercise in exercises},
            {exercise.source_id for exercise in self.catalog.exercises},
        )
        self.assertGreater(len({exercise.equipment_id for exercise in exercises}), 1)

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

        self.assertEqual({exercise.source_id for exercise in exercises}, {"0662"})

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
