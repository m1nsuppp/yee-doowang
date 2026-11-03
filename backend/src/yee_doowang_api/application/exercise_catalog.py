from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataSource(_CatalogModel):
    repository: str
    revision: str
    license: str


class Muscle(_CatalogModel):
    id: str
    name_ko: str
    source_terms: list[str]


class Equipment(_CatalogModel):
    id: str
    name_ko: str
    source_term: str


class MovementPattern(_CatalogModel):
    id: str
    name_ko: str


class WorkoutDay(_CatalogModel):
    id: str
    name_ko: str
    focus_muscle_ids: list[str]


class Exercise(_CatalogModel):
    source_id: str = Field(pattern=r"^[0-9]{4}$")
    name: str
    name_ko: str
    primary_muscle_id: str
    secondary_muscle_ids: list[str]
    movement_pattern_id: str
    equipment_id: str


class ExerciseCatalog(_CatalogModel):
    source: DataSource
    muscles: list[Muscle]
    equipment: list[Equipment]
    movement_patterns: list[MovementPattern]
    workout_days: list[WorkoutDay]
    exercises: list[Exercise]

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        muscle_ids = _unique_ids([muscle.id for muscle in self.muscles], "muscle")
        equipment_ids = _unique_ids([item.id for item in self.equipment], "equipment")
        pattern_ids = _unique_ids(
            [pattern.id for pattern in self.movement_patterns], "movement pattern"
        )
        _unique_ids([day.id for day in self.workout_days], "workout day")
        _unique_ids([exercise.source_id for exercise in self.exercises], "source exercise")

        source_terms = [term for muscle in self.muscles for term in muscle.source_terms]
        if len(source_terms) != len(set(source_terms)):
            raise ValueError("Each source muscle term must map to one muscle ID")

        for day in self.workout_days:
            _require_known_ids(day.focus_muscle_ids, muscle_ids, "workout-day muscle")

        for exercise in self.exercises:
            _require_known_ids(
                [exercise.primary_muscle_id, *exercise.secondary_muscle_ids],
                muscle_ids,
                "exercise muscle",
            )
            _require_known_ids([exercise.equipment_id], equipment_ids, "exercise equipment")
            _require_known_ids(
                [exercise.movement_pattern_id], pattern_ids, "exercise movement pattern"
            )

        return self

    def find_exercises(
        self,
        *,
        workout_day_id: str,
        equipment_id: str | None = None,
        movement_pattern_id: str | None = None,
    ) -> list[Exercise]:
        workout_day = next(
            (day for day in self.workout_days if day.id == workout_day_id),
            None,
        )
        if workout_day is None:
            raise ValueError(f"Unknown workout day: {workout_day_id}")

        if equipment_id is not None and equipment_id not in {
            item.id for item in self.equipment
        }:
            raise ValueError(f"Unknown equipment: {equipment_id}")
        if movement_pattern_id is not None and movement_pattern_id not in {
            item.id for item in self.movement_patterns
        }:
            raise ValueError(f"Unknown movement pattern: {movement_pattern_id}")

        focus_muscles = set(workout_day.focus_muscle_ids)
        return [
            exercise
            for exercise in self.exercises
            if exercise.primary_muscle_id in focus_muscles
            and (equipment_id is None or exercise.equipment_id == equipment_id)
            and (
                movement_pattern_id is None
                or exercise.movement_pattern_id == movement_pattern_id
            )
        ]


def _unique_ids(ids: list[str], kind: str) -> set[str]:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{kind} IDs must be unique")
    return set(ids)


def _require_known_ids(ids: list[str], known_ids: set[str], relation: str) -> None:
    unknown_ids = set(ids) - known_ids
    if unknown_ids:
        unknown = ", ".join(sorted(unknown_ids))
        raise ValueError(f"Unknown {relation} ID(s): {unknown}")


def load_exercise_catalog(path: Path | None = None) -> ExerciseCatalog:
    catalog_path = path or (
        Path(__file__).resolve().parents[3] / "data" / "pushday-exercises.json"
    )
    return ExerciseCatalog.model_validate_json(catalog_path.read_text(encoding="utf-8"))
