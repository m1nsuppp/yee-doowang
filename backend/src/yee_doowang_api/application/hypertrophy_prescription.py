from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _PrescriptionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrescriptionEvidenceSource(_PrescriptionModel):
    id: str
    title: str
    url: str
    doi: str
    year: int
    license: str | None
    scope: str
    limitations: str


class HypertrophyGuidelines(_PrescriptionModel):
    sources: list[PrescriptionEvidenceSource]
    initial_direct_sets_per_muscle_per_week: int = Field(ge=1)
    higher_volume_direct_sets_per_muscle_per_week: int = Field(ge=1)
    repetition_range_rm: tuple[int, int]
    rest_seconds_range: tuple[int, int]
    progression_extra_repetitions_range: tuple[int, int]
    progression_load_increase_percent_range: tuple[int, int]
    sources_by_variable: dict[str, list[str]]
    caveats: list[str]

    @model_validator(mode="after")
    def validate_ranges_and_sources(self) -> Self:
        if self.initial_direct_sets_per_muscle_per_week >= self.higher_volume_direct_sets_per_muscle_per_week:
            raise ValueError("higher-volume reference must exceed the starting set count")
        for value_range in (
            self.repetition_range_rm,
            self.rest_seconds_range,
            self.progression_extra_repetitions_range,
            self.progression_load_increase_percent_range,
        ):
            if value_range[0] < 1 or value_range[0] > value_range[1]:
                raise ValueError("prescription ranges must be positive and ordered")

        required_variables = {
            "initial_sets",
            "higher_volume",
            "repetitions",
            "rest",
            "progression",
        }
        if set(self.sources_by_variable) != required_variables:
            raise ValueError("prescription evidence must cover every required variable")
        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("prescription evidence source IDs must be unique")
        known_source_ids = set(source_ids)
        for variable, referenced_ids in self.sources_by_variable.items():
            if not referenced_ids:
                raise ValueError(f"{variable} requires at least one evidence source")
            unknown_ids = set(referenced_ids) - known_source_ids
            if unknown_ids:
                raise ValueError(
                    f"Unknown prescription evidence source(s): {', '.join(sorted(unknown_ids))}"
                )
        return self


class WeeklyDirectSetTarget(_PrescriptionModel):
    muscle_id: str
    muscle_name_ko: str
    sets_per_week: int = Field(ge=1)
    basis: Literal["source_starting_point", "user_reported"]


class HypertrophyProgressionRule(_PrescriptionModel):
    extra_repetitions_min: int
    extra_repetitions_max: int
    load_increase_percent_min: int
    load_increase_percent_max: int
    instruction: str


class HypertrophyPrescription(_PrescriptionModel):
    population_scope: str
    weekly_direct_sets: list[WeeklyDirectSetTarget] = Field(min_length=1)
    higher_volume_reference_sets_per_muscle_per_week: int
    repetition_range_rm: tuple[int, int]
    rest_seconds_range: tuple[int, int]
    progression: HypertrophyProgressionRule
    sources: list[PrescriptionEvidenceSource] = Field(min_length=1)
    caveats: list[str] = Field(min_length=1)
