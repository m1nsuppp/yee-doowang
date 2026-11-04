from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataSource(_CatalogModel):
    repository: str
    revision: str
    license: str


class RecommendationDataSource(_CatalogModel):
    id: Literal["exercise_api", "novice_consensus"]
    name: str
    url: str
    version: str | None = None
    license: str | None = None
    attribution: str | None = None


TechnicalComplexity = Literal["low", "moderate", "high"]


class ExerciseAPIProfile(_CatalogModel):
    id: str
    name: str
    primary_muscle: str
    modality: Literal["hypertrophy", "calisthenics"]
    sfr_class: Literal["high", "moderate", "low"] | None
    is_gold_standard: bool
    preferred_rank: int | None = Field(default=None, ge=1)
    e1rm_substitution_group: str | None
    loadable: bool


class ExerciseRecommendationProfile(_CatalogModel):
    source_id: str = Field(pattern=r"^[0-9]{4}$")
    exercise_api: ExerciseAPIProfile | None = None
    novice_consensus_exercise_name: str | None = None
    technical_complexity: TechnicalComplexity | None = None

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if (
            self.exercise_api is None
            and self.novice_consensus_exercise_name is None
            and self.technical_complexity is None
        ):
            raise ValueError("recommendation profile requires external evidence")
        return self


class RecommendationData(_CatalogModel):
    sources: list[RecommendationDataSource] = Field(default_factory=list)
    profiles: list[ExerciseRecommendationProfile] = Field(default_factory=list)


class Muscle(_CatalogModel):
    id: str
    name_ko: str | None
    aliases_ko: list[str] = Field(default_factory=list)
    source_terms: list[str]


class Equipment(_CatalogModel):
    id: str
    name_ko: str | None
    source_term: str


class MovementPattern(_CatalogModel):
    id: str
    name_ko: str


class WorkoutDay(_CatalogModel):
    id: str
    name_ko: str
    aliases: list[str] = Field(default_factory=list)
    focus_muscle_ids: list[str]
    include_secondary_muscles: bool = False


class Exercise(_CatalogModel):
    source_id: str = Field(pattern=r"^[0-9]{4}$")
    name: str
    name_ko: str | None
    primary_muscle_id: str
    secondary_muscle_ids: list[str]
    movement_pattern_id: str | None
    equipment_id: str


class ExerciseCatalog(_CatalogModel):
    source: DataSource
    muscles: list[Muscle]
    equipment: list[Equipment]
    movement_patterns: list[MovementPattern]
    workout_days: list[WorkoutDay]
    exercises: list[Exercise]
    recommendations: RecommendationData = Field(default_factory=RecommendationData)

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        muscle_ids = _unique_ids([muscle.id for muscle in self.muscles], "muscle")
        equipment_ids = _unique_ids([item.id for item in self.equipment], "equipment")
        pattern_ids = _unique_ids(
            [pattern.id for pattern in self.movement_patterns], "movement pattern"
        )
        _unique_ids([day.id for day in self.workout_days], "workout day")
        _unique_ids(
            [exercise.source_id for exercise in self.exercises], "source exercise"
        )
        recommendation_source_ids = _unique_ids(
            [source.id for source in self.recommendations.sources],
            "recommendation source",
        )
        recommendation_profile_ids = _unique_ids(
            [profile.source_id for profile in self.recommendations.profiles],
            "recommendation profile exercise",
        )
        _require_known_ids(
            list(recommendation_profile_ids),
            {exercise.source_id for exercise in self.exercises},
            "recommendation-profile exercise",
        )
        for profile in self.recommendations.profiles:
            if (
                profile.exercise_api is not None
                and "exercise_api" not in recommendation_source_ids
            ):
                raise ValueError("ExerciseAPI profile requires its source declaration")
            if (
                (
                    profile.novice_consensus_exercise_name is not None
                    or profile.technical_complexity is not None
                )
                and "novice_consensus" not in recommendation_source_ids
            ):
                raise ValueError("novice profile requires its source declaration")

        source_terms = [term for muscle in self.muscles for term in muscle.source_terms]
        if len(source_terms) != len(set(source_terms)):
            raise ValueError("Each source muscle term must map to one muscle ID")
        korean_names: set[str] = set()
        for muscle in self.muscles:
            names = [muscle.name_ko] if muscle.name_ko is not None else []
            names.extend(muscle.aliases_ko)
            for name in names:
                if not name.strip() or name != name.strip():
                    raise ValueError(
                        "Korean muscle names and aliases must be non-empty and trimmed"
                    )
                if name in korean_names:
                    raise ValueError("Korean muscle names and aliases must be unique")
                korean_names.add(name)

        for day in self.workout_days:
            _require_known_ids(day.focus_muscle_ids, muscle_ids, "workout-day muscle")

        for exercise in self.exercises:
            _require_known_ids(
                [exercise.primary_muscle_id, *exercise.secondary_muscle_ids],
                muscle_ids,
                "exercise muscle",
            )
            _require_known_ids(
                [exercise.equipment_id], equipment_ids, "exercise equipment"
            )
            if exercise.movement_pattern_id is not None:
                _require_known_ids(
                    [exercise.movement_pattern_id],
                    pattern_ids,
                    "exercise movement pattern",
                )

        return self


def _unique_ids(ids: list[str], kind: str) -> set[str]:
    if len(ids) != len(set(ids)):
        raise ValueError(f"{kind} IDs must be unique")
    return set(ids)


def _require_known_ids(ids: list[str], known_ids: set[str], relation: str) -> None:
    unknown_ids = set(ids) - known_ids
    if unknown_ids:
        unknown = ", ".join(sorted(unknown_ids))
        raise ValueError(f"Unknown {relation} ID(s): {unknown}")
