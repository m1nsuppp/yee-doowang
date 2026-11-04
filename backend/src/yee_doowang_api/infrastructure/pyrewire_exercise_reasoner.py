import asyncio

from pyrewire import EasySession

from yee_doowang_api.application.chat_models import (
    EquipmentConstraint,
    ExerciseReasoner,
)
from yee_doowang_api.application.exercise_catalog import Exercise, ExerciseCatalog

_PROGRAM = """
.decl focus_muscle(day: symbol, muscle: symbol)
.decl focus_secondary_muscle(day: symbol, muscle: symbol)
.decl primary_muscle(exercise: symbol, muscle: symbol)
.decl exercise_equipment(exercise: symbol, equipment: symbol)
.decl secondary_muscle(exercise: symbol, muscle: symbol)
.decl requested_day(day: symbol)
.decl available_equipment(equipment: symbol)
.decl unrestricted_equipment(flag: symbol)
.decl eligible_exercise(exercise: symbol)

eligible_exercise(Exercise) :-
    requested_day(Day),
    focus_muscle(Day, Muscle),
    primary_muscle(Exercise, Muscle),
    exercise_equipment(Exercise, Equipment),
    available_equipment(Equipment).
eligible_exercise(Exercise) :-
    requested_day(Day),
    focus_muscle(Day, Muscle),
    primary_muscle(Exercise, Muscle),
    exercise_equipment(Exercise, Equipment),
    unrestricted_equipment("any").
eligible_exercise(Exercise) :-
    requested_day(Day),
    focus_secondary_muscle(Day, Muscle),
    secondary_muscle(Exercise, Muscle),
    exercise_equipment(Exercise, Equipment),
    available_equipment(Equipment).
eligible_exercise(Exercise) :-
    requested_day(Day),
    focus_secondary_muscle(Day, Muscle),
    secondary_muscle(Exercise, Muscle),
    exercise_equipment(Exercise, Equipment),
    unrestricted_equipment("any").
"""


class PyreWireExerciseReasoner(ExerciseReasoner):
    def __init__(self, catalog: ExerciseCatalog) -> None:
        self._catalog = catalog
        self._workout_day_ids = {day.id for day in catalog.workout_days}
        self._equipment_ids = {item.id for item in catalog.equipment}

    async def recommend(
        self,
        *,
        workout_day_id: str,
        equipment_constraint: EquipmentConstraint,
    ) -> list[Exercise]:
        if workout_day_id not in self._workout_day_ids:
            raise ValueError(f"Unknown workout day: {workout_day_id}")
        if equipment_constraint.mode == "specified":
            unknown_equipment = set(equipment_constraint.equipment_ids) - self._equipment_ids
            if unknown_equipment:
                unknown = ", ".join(sorted(unknown_equipment))
                raise ValueError(f"Unknown equipment ID(s): {unknown}")
        if equipment_constraint.mode == "unrestricted" and equipment_constraint.equipment_ids:
            raise ValueError("Unrestricted equipment cannot include IDs")

        return await asyncio.to_thread(
            self._recommend_sync,
            workout_day_id,
            equipment_constraint,
        )

    def _recommend_sync(
        self,
        workout_day_id: str,
        equipment_constraint: EquipmentConstraint,
    ) -> list[Exercise]:
        with EasySession(_PROGRAM) as session:
            for day in self._catalog.workout_days:
                for muscle_id in day.focus_muscle_ids:
                    session.insert("focus_muscle", [day.id, muscle_id])
                if day.include_secondary_muscles:
                    for muscle_id in day.focus_muscle_ids:
                        session.insert(
                            "focus_secondary_muscle", [day.id, muscle_id]
                        )

            for exercise in self._catalog.exercises:
                session.insert(
                    "primary_muscle",
                    [exercise.source_id, exercise.primary_muscle_id],
                )
                for muscle_id in exercise.secondary_muscle_ids:
                    session.insert(
                        "secondary_muscle", [exercise.source_id, muscle_id]
                    )
                session.insert(
                    "exercise_equipment",
                    [exercise.source_id, exercise.equipment_id],
                )

            session.insert("requested_day", [workout_day_id])
            if equipment_constraint.mode == "unrestricted":
                session.insert("unrestricted_equipment", ["any"])
            else:
                for equipment_id in equipment_constraint.equipment_ids:
                    session.insert("available_equipment", [equipment_id])

            eligible_ids = {
                row[0] for row in session.snapshot("eligible_exercise")
            }

        return [
            exercise
            for exercise in self._catalog.exercises
            if exercise.source_id in eligible_ids
        ]
