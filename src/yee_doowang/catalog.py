from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Locale = Literal["ko", "en"]
TermKind = Literal["muscle", "equipment", "workout_day", "movement_pattern", "exercise"]
TaxonomyKind = Literal["muscles", "equipment", "movement_patterns", "workout_days"]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedLabels(_Model):
    ko: str
    en: str


class ExerciseLabels(_Model):
    en: str
    ko: str | None = None


class TaxonomyEntry(_Model):
    id: str
    labels: LocalizedLabels
    input_aliases: dict[str, list[str]] = Field(default_factory=dict)


class WorkoutDay(TaxonomyEntry):
    focus_muscle_ids: list[str]
    include_secondary_muscles: bool


class ExerciseRecord(_Model):
    source_id: str = Field(pattern=r"^[0-9]{4}$")
    labels: ExerciseLabels
    primary_muscle_id: str
    secondary_muscle_ids: list[str]
    movement_pattern_id: str | None
    equipment_id: str


class ExerciseAPIProfile(_Model):
    id: str
    name: str
    modality: Literal["hypertrophy", "calisthenics"]
    sfr_class: Literal["high", "moderate", "low"] | None = None
    is_gold_standard: bool
    preferred_rank: int | None = None
    e1rm_substitution_group: str | None = None
    loadable: bool


class RecommendationProfile(_Model):
    source_id: str = Field(pattern=r"^[0-9]{4}$")
    exercise_api: ExerciseAPIProfile | None = None
    novice_consensus_exercise_name: str | None = None
    technical_complexity: Literal["low", "moderate", "high"] | None = None


class RecommendationData(_Model):
    sources: list[dict[str, Any]]
    profiles: list[RecommendationProfile]


class CatalogDocument(_Model):
    source: dict[str, str]
    muscles: list[TaxonomyEntry]
    equipment: list[TaxonomyEntry]
    movement_patterns: list[TaxonomyEntry]
    workout_days: list[WorkoutDay]
    exercise_shards: list[str]
    recommendations: RecommendationData


class Reference(_Model):
    id: str
    label: str


class ExerciseSummary(_Model):
    source_id: str
    labels: ExerciseLabels
    display_name: str
    primary_muscle: Reference
    secondary_muscles: list[Reference]
    equipment: Reference
    movement_pattern: Reference | None


class ExerciseList(_Model):
    locale: Locale
    total: int
    items: list[ExerciseSummary]


class ExerciseEvidence(_Model):
    modality: Literal["hypertrophy", "calisthenics"] | None
    sfr_class: Literal["high", "moderate", "low"] | None
    is_gold_standard: bool
    preferred_rank: int | None
    e1rm_substitution_group: str | None
    loadable: bool
    novice_consensus: bool
    technical_complexity: Literal["low", "moderate", "high"] | None


class ExerciseDetail(ExerciseSummary):
    evidence: ExerciseEvidence | None


class TaxonomyItem(_Model):
    id: str
    label: str
    aliases: list[str]


class WorkoutDayItem(TaxonomyItem):
    focus_muscles: list[Reference]
    include_secondary_muscles: bool


class TaxonomySnapshot(_Model):
    locale: Locale
    muscles: list[TaxonomyItem]
    equipment: list[TaxonomyItem]
    movement_patterns: list[TaxonomyItem]
    workout_days: list[WorkoutDayItem]


class TermMatch(_Model):
    kind: TermKind
    id: str
    label: str
    matched_text: str


class TermResolution(_Model):
    query: str
    locale: Locale
    matches: list[TermMatch]


class Catalog:
    def __init__(
        self,
        document: CatalogDocument,
        exercises: list[ExerciseRecord],
        korean_labels: dict[str, str],
        exercise_aliases: dict[str, list[str]] | None = None,
    ) -> None:
        self._document = document
        self._muscles = self._index(document.muscles, "muscle")
        self._equipment = self._index(document.equipment, "equipment")
        self._patterns = self._index(document.movement_patterns, "movement pattern")
        self._days = self._index(document.workout_days, "workout day")
        self._exercises_by_id = self._index(exercises, "exercise source")
        self._exercises = exercises
        self._profiles = self._index_profiles(document.recommendations.profiles)
        self._exercise_aliases = exercise_aliases or {}
        self._apply_korean_labels(korean_labels)
        self._validate_references()
        self._term_index = self._build_term_index()

    @classmethod
    def load(cls, data_dir: Path | None = None) -> Catalog:
        root = data_dir or DATA_DIR
        catalog_path = root / "exercise-catalog.json"
        document = CatalogDocument.model_validate(
            json.loads(catalog_path.read_text(encoding="utf-8"))
        )
        exercises = [
            ExerciseRecord.model_validate(item)
            for shard in document.exercise_shards
            for item in json.loads(
                (catalog_path.parent / shard).read_text(encoding="utf-8")
            )
        ]
        korean_labels = {
            source_id: label
            for source_id, label in json.loads(
                (root / "exercise-labels.ko.json").read_text(encoding="utf-8")
            ).items()
            if label
        }
        aliases_path = root / "exercise-aliases.ko.json"
        exercise_aliases = (
            json.loads(aliases_path.read_text(encoding="utf-8"))
            if aliases_path.exists()
            else {}
        )
        return cls(document, exercises, korean_labels, exercise_aliases)

    @staticmethod
    def _index(items: list[Any], kind: str) -> dict[str, Any]:
        index = {
            item.id if hasattr(item, "id") else item.source_id: item for item in items
        }
        if len(index) != len(items):
            raise ValueError(f"{kind} IDs must be unique")
        return index

    @staticmethod
    def _index_profiles(
        profiles: list[RecommendationProfile],
    ) -> dict[str, RecommendationProfile]:
        index = {profile.source_id: profile for profile in profiles}
        if len(index) != len(profiles):
            raise ValueError("recommendation profile exercise IDs must be unique")
        return index

    def _apply_korean_labels(self, korean_labels: dict[str, str]) -> None:
        unknown = set(korean_labels) - self._exercises_by_id.keys()
        if unknown:
            raise ValueError(f"Korean labels reference unknown exercises: {sorted(unknown)}")
        for source_id, label in korean_labels.items():
            self._exercises_by_id[source_id].labels.ko = label

    def _validate_references(self) -> None:
        for day in self._days.values():
            unknown = set(day.focus_muscle_ids) - self._muscles.keys()
            if unknown:
                raise ValueError(
                    f"Workout day {day.id} references unknown muscles: {sorted(unknown)}"
                )
        for exercise in self._exercises:
            unknown_muscles = (
                {exercise.primary_muscle_id, *exercise.secondary_muscle_ids}
                - self._muscles.keys()
            )
            if unknown_muscles:
                raise ValueError(
                    f"Exercise {exercise.source_id} references unknown muscles: "
                    f"{sorted(unknown_muscles)}"
                )
            if exercise.equipment_id not in self._equipment:
                raise ValueError(
                    f"Exercise {exercise.source_id} references unknown equipment: "
                    f"{exercise.equipment_id}"
                )
            if (
                exercise.movement_pattern_id is not None
                and exercise.movement_pattern_id not in self._patterns
            ):
                raise ValueError(
                    f"Exercise {exercise.source_id} references unknown movement pattern: "
                    f"{exercise.movement_pattern_id}"
                )
        for profile in self._profiles.values():
            if profile.source_id not in self._exercises_by_id:
                raise ValueError(
                    f"Recommendation profile references unknown exercise: {profile.source_id}"
                )
        unknown_aliases = set(self._exercise_aliases) - self._exercises_by_id.keys()
        if unknown_aliases:
            raise ValueError(
                f"Exercise aliases reference unknown exercises: {sorted(unknown_aliases)}"
            )

    def exercises(self) -> list[ExerciseRecord]:
        return list(self._exercises)

    def workout_days(self) -> list[WorkoutDay]:
        return list(self._document.workout_days)

    def workout_day(self, day_id: str) -> WorkoutDay:
        day = self._days.get(day_id)
        if day is None:
            raise ValueError(f"Unknown workout_day_id: {day_id}")
        return day

    def exercise(self, source_id: str) -> ExerciseRecord:
        exercise = self._exercises_by_id.get(source_id)
        if exercise is None:
            raise ValueError(f"Unknown exercise source_id: {source_id}")
        return exercise

    def profile(self, source_id: str) -> RecommendationProfile | None:
        return self._profiles.get(source_id)

    def muscle_ids(self) -> list[str]:
        return [muscle.id for muscle in self._document.muscles]

    def equipment_ids(self) -> list[str]:
        return [item.id for item in self._document.equipment]

    def list_exercises(
        self,
        *,
        muscle_id: str | None = None,
        workout_day_id: str | None = None,
        equipment_id: str | None = None,
        locale: Locale = "ko",
        limit: int = 20,
    ) -> ExerciseList:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if muscle_id is not None and muscle_id not in self._muscles:
            raise ValueError(
                f"Unknown muscle_id: {muscle_id}. Valid: {', '.join(sorted(self._muscles))}"
            )
        if equipment_id is not None and equipment_id not in self._equipment:
            raise ValueError(
                f"Unknown equipment_id: {equipment_id}. "
                f"Valid: {', '.join(sorted(self._equipment))}"
            )
        day = None
        if workout_day_id is not None:
            day = self._days.get(workout_day_id)
            if day is None:
                raise ValueError(
                    f"Unknown workout_day_id: {workout_day_id}. "
                    f"Valid: {', '.join(sorted(self._days))}"
                )

        matches = [
            exercise
            for exercise in self._exercises
            if self._matches(
                exercise, muscle_id=muscle_id, equipment_id=equipment_id, day=day
            )
        ]
        return ExerciseList(
            locale=locale,
            total=len(matches),
            items=[self.summary(exercise, locale) for exercise in matches[:limit]],
        )

    @staticmethod
    def _matches(
        exercise: ExerciseRecord,
        *,
        muscle_id: str | None,
        equipment_id: str | None,
        day: WorkoutDay | None,
    ) -> bool:
        if muscle_id is not None and exercise.primary_muscle_id != muscle_id:
            return False
        if equipment_id is not None and exercise.equipment_id != equipment_id:
            return False
        if day is None:
            return True
        focus = set(day.focus_muscle_ids)
        if exercise.primary_muscle_id in focus:
            return True
        return day.include_secondary_muscles and bool(
            focus & set(exercise.secondary_muscle_ids)
        )

    @staticmethod
    def is_mobility(exercise: ExerciseRecord) -> bool:
        name = exercise.labels.en.casefold()
        return (
            exercise.primary_muscle_id == "cardiovascular_system"
            or "stretch" in name
            or "mobility" in name
        )

    def summary(self, exercise: ExerciseRecord, locale: Locale) -> ExerciseSummary:
        return ExerciseSummary(
            source_id=exercise.source_id,
            labels=exercise.labels,
            display_name=self._exercise_label(exercise.labels, locale),
            primary_muscle=self.reference("muscle", exercise.primary_muscle_id, locale),
            secondary_muscles=[
                self.reference("muscle", muscle_id, locale)
                for muscle_id in exercise.secondary_muscle_ids
            ],
            equipment=self.reference("equipment", exercise.equipment_id, locale),
            movement_pattern=(
                self.reference("movement_pattern", exercise.movement_pattern_id, locale)
                if exercise.movement_pattern_id is not None
                else None
            ),
        )

    def get_exercise(self, source_id: str, locale: Locale = "ko") -> ExerciseDetail:
        exercise = self.exercise(source_id)
        profile = self._profiles.get(source_id)
        evidence = None
        if profile is not None:
            api = profile.exercise_api
            evidence = ExerciseEvidence(
                modality=api.modality if api is not None else None,
                sfr_class=api.sfr_class if api is not None else None,
                is_gold_standard=bool(api is not None and api.is_gold_standard),
                preferred_rank=api.preferred_rank if api is not None else None,
                e1rm_substitution_group=(
                    api.e1rm_substitution_group if api is not None else None
                ),
                loadable=bool(api is not None and api.loadable),
                novice_consensus=profile.novice_consensus_exercise_name is not None,
                technical_complexity=profile.technical_complexity,
            )
        return ExerciseDetail(
            **self.summary(exercise, locale).model_dump(),
            evidence=evidence,
        )

    def list_taxonomy(
        self,
        locale: Locale = "ko",
        kind: TaxonomyKind | None = None,
    ) -> TaxonomySnapshot:
        muscles = (
            [self._taxonomy_item(entry, locale) for entry in self._document.muscles]
            if kind in (None, "muscles")
            else []
        )
        equipment = (
            [self._taxonomy_item(entry, locale) for entry in self._document.equipment]
            if kind in (None, "equipment")
            else []
        )
        movement_patterns = (
            [
                self._taxonomy_item(entry, locale)
                for entry in self._document.movement_patterns
            ]
            if kind in (None, "movement_patterns")
            else []
        )
        workout_days = (
            [
                WorkoutDayItem(
                    id=day.id,
                    label=getattr(day.labels, locale),
                    aliases=self._aliases(day),
                    focus_muscles=[
                        self.reference("muscle", muscle_id, locale)
                        for muscle_id in day.focus_muscle_ids
                    ],
                    include_secondary_muscles=day.include_secondary_muscles,
                )
                for day in self._document.workout_days
            ]
            if kind in (None, "workout_days")
            else []
        )
        return TaxonomySnapshot(
            locale=locale,
            muscles=muscles,
            equipment=equipment,
            movement_patterns=movement_patterns,
            workout_days=workout_days,
        )

    def resolve_terms(
        self,
        query: str,
        locale: Locale = "ko",
        limit: int = 20,
    ) -> TermResolution:
        if not query.strip():
            raise ValueError("query must not be blank")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        normalized_query = self._normalize_text(query)
        best: dict[tuple[TermKind, str], tuple[int, TermMatch]] = {}
        for kind, entity_id, term, original in self._term_index:
            if not self._contains_term(normalized_query, term):
                continue
            match = TermMatch(
                kind=kind,
                id=entity_id,
                label=self.reference(kind, entity_id, locale).label,
                matched_text=original,
            )
            key = (kind, entity_id)
            if key not in best or len(term) > best[key][0]:
                best[key] = (len(term), match)
        matches = sorted(
            (match for _, match in best.values()),
            key=lambda item: len(self._normalize_text(item.matched_text)),
            reverse=True,
        )
        return TermResolution(query=query, locale=locale, matches=matches[:limit])

    def reference(self, kind: TermKind, entity_id: str, locale: Locale) -> Reference:
        return Reference(id=entity_id, label=self._label(kind, entity_id, locale))

    def _label(self, kind: TermKind, entity_id: str, locale: Locale) -> str:
        if kind == "exercise":
            return self._exercise_label(self._exercises_by_id[entity_id].labels, locale)
        if kind == "muscle":
            return getattr(self._muscles[entity_id].labels, locale)
        if kind == "equipment":
            return getattr(self._equipment[entity_id].labels, locale)
        if kind == "workout_day":
            return getattr(self._days[entity_id].labels, locale)
        return getattr(self._patterns[entity_id].labels, locale)

    @staticmethod
    def _exercise_label(labels: ExerciseLabels, locale: Locale) -> str:
        if locale == "ko" and labels.ko:
            return labels.ko
        return labels.en

    def _taxonomy_item(self, entry: TaxonomyEntry, locale: Locale) -> TaxonomyItem:
        return TaxonomyItem(
            id=entry.id,
            label=getattr(entry.labels, locale),
            aliases=self._aliases(entry),
        )

    @staticmethod
    def _aliases(entry: TaxonomyEntry) -> list[str]:
        labels = {entry.labels.ko, entry.labels.en}
        aliases: list[str] = []
        for values in entry.input_aliases.values():
            for value in values:
                if value not in labels and value not in aliases:
                    aliases.append(value)
        return aliases

    def _build_term_index(self) -> list[tuple[TermKind, str, str, str]]:
        terms: list[tuple[TermKind, str, str, str]] = []

        def add(kind: TermKind, entity_id: str, texts: list[str | None]) -> None:
            for text in texts:
                if not text:
                    continue
                normalized = self._normalize_text(text)
                if normalized:
                    terms.append((kind, entity_id, normalized, text))

        for entry in self._document.muscles:
            add("muscle", entry.id, self._term_texts(entry))
        for entry in self._document.equipment:
            add("equipment", entry.id, self._term_texts(entry))
        for entry in self._document.movement_patterns:
            add("movement_pattern", entry.id, self._term_texts(entry))
        for day in self._document.workout_days:
            add("workout_day", day.id, self._term_texts(day))
        for exercise in self._exercises:
            add("exercise", exercise.source_id, [exercise.labels.ko, exercise.labels.en])
        for source_id, aliases in self._exercise_aliases.items():
            add("exercise", source_id, aliases)

        unique: dict[tuple[TermKind, str, str], str] = {}
        for kind, entity_id, normalized, original in terms:
            unique.setdefault((kind, entity_id, normalized), original)
        index = [
            (kind, entity_id, normalized, original)
            for (kind, entity_id, normalized), original in unique.items()
        ]
        index.sort(key=lambda item: len(item[2]), reverse=True)
        return index

    @staticmethod
    def _term_texts(entry: TaxonomyEntry) -> list[str | None]:
        texts: list[str | None] = [entry.labels.ko, entry.labels.en]
        for values in entry.input_aliases.values():
            texts.extend(values)
        return texts

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(
            "".join(char.casefold() if char.isalnum() else " " for char in value).split()
        )

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if re.fullmatch(r"[0-9a-z ]+", term):
            return (
                re.search(
                    rf"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])",
                    text,
                )
                is not None
            )
        return term in text
