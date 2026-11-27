from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yee_doowang.calculations import epley_1rm
from yee_doowang.catalog import Catalog, ExerciseRecord, Locale, Reference
from yee_doowang.ontology import ExerciseOntology, MuscleRoles
from yee_doowang.storage import WorkoutStore

_WEIGHT_UNIT_TO_KG = {"kg": 1.0, "lb": 0.45359237}
GroupBy = Literal["session", "exercise", "week", "muscle"]
Trend = Literal["up", "flat", "down", "insufficient_data"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetInput(_Model):
    weight_kg: float = Field(ge=0)
    reps: int = Field(ge=1, le=100)
    sets: int = Field(default=1, ge=1, le=20)
    rpe: float | None = Field(default=None, ge=1, le=10)
    is_warmup: bool = False


class ExerciseInput(_Model):
    name: str | None = Field(default=None, min_length=1)
    exercise_id: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    sets: list[SetInput] = Field(min_length=1)

    @model_validator(mode="after")
    def require_identity(self) -> ExerciseInput:
        if self.name is None and self.exercise_id is None:
            raise ValueError("exercise name or exercise_id is required")
        return self


class LogWorkoutRequest(_Model):
    performed_at: datetime | None = None
    exercises: list[ExerciseInput] = Field(min_length=1)
    notes: str | None = None
    client_request_id: str | None = None
    weight_unit: Literal["kg", "lb"] = "kg"


class WorkoutHistoryRequest(_Model):
    exercise: str | None = None
    exercise_id: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    start_date: date | None = None
    end_date: date | None = None
    group_by: GroupBy = "session"
    include_sets: bool = False


class BodyMetricInput(_Model):
    measured_at: datetime | None = None
    body_weight_kg: float | None = Field(default=None, gt=0)
    body_fat_percent: float | None = Field(default=None, ge=0, le=70)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    fatigue: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None

    @model_validator(mode="after")
    def require_metric(self) -> BodyMetricInput:
        if all(
            value is None
            for value in (
                self.body_weight_kg,
                self.body_fat_percent,
                self.sleep_hours,
                self.fatigue,
            )
        ):
            raise ValueError("at least one body metric is required")
        return self


class MuscleSetCount(_Model):
    muscle: Reference
    sets: int


class PersonalRecord(_Model):
    exercise_id: str
    exercise_name: str
    display_name: str
    e1rm_kg: float
    previous_e1rm_kg: float | None
    weight_kg: float
    reps: int
    performed_at: str


class LoggedExercise(_Model):
    exercise_id: str
    exercise_name: str
    display_name: str
    primary_muscle: Reference | None
    working_sets: int
    volume_kg: float
    best_e1rm_kg: float | None


class WorkoutLogResult(_Model):
    session_id: int
    performed_at: str
    exercises: list[LoggedExercise]
    total_volume_kg: float
    working_sets: int
    muscle_sets: list[MuscleSetCount]
    new_prs: list[PersonalRecord]
    notes: str | None
    duplicate: bool = False


class HistorySet(_Model):
    exercise_id: str
    exercise_name: str
    display_name: str
    set_index: int
    weight_kg: float
    reps: int
    rpe: float | None
    is_warmup: bool
    volume_kg: float


class HistorySession(_Model):
    session_id: int
    performed_at: str
    notes: str | None
    total_volume_kg: float
    working_sets: int
    exercises: list[LoggedExercise]
    sets: list[HistorySet] | None = None


class ExerciseHistory(_Model):
    exercise_id: str
    exercise_name: str
    display_name: str
    sessions: int
    working_sets: int
    total_volume_kg: float
    best_weight_kg: float
    best_e1rm_kg: float | None
    last_performed_at: str


class WeekHistory(_Model):
    week_start: date
    sessions: int
    working_sets: int
    total_volume_kg: float


class MuscleHistory(_Model):
    muscle: Reference
    direct_sets: int
    volume_kg: float


class ProgressionSignal(_Model):
    exercise_id: str
    exercise_name: str
    display_name: str
    sessions: int
    first_e1rm_kg: float | None
    last_e1rm_kg: float | None
    change_pct: float | None
    trend: Trend
    message: str


class WorkoutHistory(_Model):
    start_date: date
    end_date: date
    group_by: GroupBy
    sessions: list[HistorySession] = Field(default_factory=list)
    exercises: list[ExerciseHistory] = Field(default_factory=list)
    weeks: list[WeekHistory] = Field(default_factory=list)
    muscles: list[MuscleHistory] = Field(default_factory=list)
    signals: list[ProgressionSignal] = Field(default_factory=list)


class BodyMetricRecord(_Model):
    id: int
    measured_at: str
    body_weight_kg: float | None
    body_fat_percent: float | None
    sleep_hours: float | None
    fatigue: int | None
    notes: str | None


class BodyMetricsSummary(_Model):
    start_date: date
    end_date: date
    latest: BodyMetricRecord | None
    average_body_weight_kg: float | None
    average_body_fat_percent: float | None
    average_sleep_hours: float | None
    average_fatigue: float | None
    body_weight_change_kg: float | None
    records: list[BodyMetricRecord]


class BodyMetricLogResult(_Model):
    record: BodyMetricRecord
    previous: BodyMetricRecord | None
    body_weight_change_kg: float | None


class TrainingContext(_Model):
    generated_at: str
    days: int
    recent_sessions: list[HistorySession]
    body_metrics: BodyMetricsSummary
    progression_signals: list[ProgressionSignal]
    weekly_direct_sets: list[MuscleHistory]
    personal_records: list[PersonalRecord]
    notes: list[str]


class DeletedEntry(_Model):
    kind: Literal["workout", "body_metrics"]
    id: int
    summary: str


class ExportResult(_Model):
    path: str
    format: Literal["json", "markdown"]
    sessions: int
    sets: int
    body_metrics: int


class WorkoutService:
    def __init__(
        self,
        store: WorkoutStore,
        catalog: Catalog,
        ontology: ExerciseOntology,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._ontology = ontology

    def log_workout(
        self,
        request: LogWorkoutRequest,
        locale: Locale = "ko",
    ) -> WorkoutLogResult:
        if request.client_request_id is not None:
            existing = self._store.find_session_by_request_id(
                request.client_request_id
            )
            if existing is not None:
                return self._session_result(
                    existing,
                    self._store.get_sets(session_id=existing),
                    locale,
                    duplicate=True,
                )

        resolved: dict[str, tuple[ExerciseRecord, list[SetInput]]] = {}
        for item in request.exercises:
            exercise = self._resolve_exercise(item)
            _, pending = resolved.setdefault(exercise.source_id, (exercise, []))
            pending.extend(item.sets)

        unit_factor = _WEIGHT_UNIT_TO_KG[request.weight_unit]
        set_rows: list[dict[str, Any]] = []
        session_best: dict[str, tuple[float, float, int]] = {}
        for exercise_id, (exercise, sets) in resolved.items():
            set_index = 0
            for set_input in sets:
                weight_kg = round(set_input.weight_kg * unit_factor, 3)
                for _ in range(set_input.sets):
                    set_index += 1
                    set_rows.append(
                        {
                            "exercise_id": exercise.source_id,
                            "exercise_name": exercise.labels.en,
                            "set_index": set_index,
                            "weight_kg": weight_kg,
                            "reps": set_input.reps,
                            "rpe": set_input.rpe,
                            "is_warmup": int(set_input.is_warmup),
                        }
                    )
                    if set_input.is_warmup:
                        continue
                    estimate = _e1rm(weight_kg, set_input.reps)
                    if estimate is None:
                        continue
                    current = session_best.get(exercise_id)
                    if current is None or estimate > current[0]:
                        session_best[exercise_id] = (
                            estimate,
                            weight_kg,
                            set_input.reps,
                        )

        previous_best = {
            exercise_id: self._best_e1rm(exercise_id)
            for exercise_id in resolved
        }
        new_prs: list[PersonalRecord] = []
        for exercise_id, (estimate, weight_kg, reps) in session_best.items():
            previous = previous_best[exercise_id]
            if previous is not None and estimate <= previous + 0.05:
                continue
            exercise = resolved[exercise_id][0]
            new_prs.append(
                PersonalRecord(
                    exercise_id=exercise_id,
                    exercise_name=exercise.labels.en,
                    display_name=self._catalog.summary(exercise, locale).display_name,
                    e1rm_kg=estimate,
                    previous_e1rm_kg=previous,
                    weight_kg=weight_kg,
                    reps=reps,
                    performed_at=_iso(request.performed_at),
                )
            )

        performed_at = _iso(request.performed_at)
        session_id = self._store.insert_session(
            performed_at=performed_at,
            notes=request.notes,
            client_request_id=request.client_request_id,
            created_at=_iso(None),
        )
        self._store.insert_sets(session_id, set_rows)
        result = self._session_result(
            session_id,
            self._store.get_sets(session_id=session_id),
            locale,
        )
        result.new_prs = new_prs
        return result

    def workout_history(
        self,
        request: WorkoutHistoryRequest,
        locale: Locale = "ko",
    ) -> WorkoutHistory:
        end_date = request.end_date or _today()
        start_date = request.start_date or (end_date - timedelta(days=27))
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        exercise_id = self._history_exercise_id(request)
        rows = self._store.get_sets(
            exercise_id=exercise_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        signals = self._signals(rows, locale)
        sessions: list[HistorySession] = []
        exercises: list[ExerciseHistory] = []
        weeks: list[WeekHistory] = []
        muscles: list[MuscleHistory] = []
        if request.group_by == "session":
            sessions = self._sessions(rows, locale, request.include_sets)
        elif request.group_by == "exercise":
            exercises = self._exercise_history(rows, locale)
        elif request.group_by == "week":
            weeks = self._week_history(rows)
        else:
            muscles = self._muscle_history(rows, locale)
        return WorkoutHistory(
            start_date=start_date,
            end_date=end_date,
            group_by=request.group_by,
            sessions=sessions,
            exercises=exercises,
            weeks=weeks,
            muscles=muscles,
            signals=signals,
        )

    def log_body_metrics(self, request: BodyMetricInput) -> BodyMetricLogResult:
        measured_at = _iso(request.measured_at)
        previous = self._store.previous_body_metric(measured_at)
        metric_id = self._store.insert_body_metric(
            measured_at=measured_at,
            created_at=_iso(None),
            body_weight_kg=request.body_weight_kg,
            body_fat_percent=request.body_fat_percent,
            sleep_hours=request.sleep_hours,
            fatigue=request.fatigue,
            notes=request.notes,
        )
        row = self._store.get_body_metric(metric_id)
        if row is None:
            raise RuntimeError("body metric was not stored")
        record = _body_record(row)
        previous_record = _body_record(previous) if previous is not None else None
        change = None
        if (
            previous_record is not None
            and previous_record.body_weight_kg is not None
            and record.body_weight_kg is not None
        ):
            change = round(
                record.body_weight_kg - previous_record.body_weight_kg, 2
            )
        return BodyMetricLogResult(
            record=record,
            previous=previous_record,
            body_weight_change_kg=change,
        )

    def body_metrics(self, days: int = 28) -> BodyMetricsSummary:
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        end_date = _today()
        start_date = end_date - timedelta(days=days - 1)
        rows = self._store.body_metrics(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        records = [_body_record(row) for row in rows]
        latest = records[-1] if records else None
        weights = [
            record.body_weight_kg
            for record in records
            if record.body_weight_kg is not None
        ]
        body_fat = [
            record.body_fat_percent
            for record in records
            if record.body_fat_percent is not None
        ]
        sleep = [
            record.sleep_hours
            for record in records
            if record.sleep_hours is not None
        ]
        fatigue = [
            record.fatigue
            for record in records
            if record.fatigue is not None
        ]
        change = None
        if latest is not None and latest.body_weight_kg is not None and weights:
            change = round(latest.body_weight_kg - weights[0], 2)
        return BodyMetricsSummary(
            start_date=start_date,
            end_date=end_date,
            latest=latest,
            average_body_weight_kg=_average(weights),
            average_body_fat_percent=_average(body_fat),
            average_sleep_hours=_average(sleep),
            average_fatigue=_average(fatigue),
            body_weight_change_kg=change,
            records=records,
        )

    def training_context(
        self,
        days: int = 28,
        locale: Locale = "ko",
    ) -> TrainingContext:
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        end_date = _today()
        start_date = end_date - timedelta(days=days - 1)
        request = WorkoutHistoryRequest(
            start_date=start_date,
            end_date=end_date,
        )
        session_history = self.workout_history(
            request.model_copy(update={"group_by": "session"}), locale
        )
        muscle_history = self.workout_history(
            request.model_copy(update={"group_by": "muscle"}), locale
        )
        body_metrics = self.body_metrics(days)
        personal_records = self._all_time_records(locale)
        notes: list[str] = []
        if not session_history.sessions:
            notes.append(f"최근 {days}일 운동 기록이 없다.")
        if body_metrics.latest is None:
            notes.append(f"최근 {days}일 신체 측정 기록이 없다.")
        return TrainingContext(
            generated_at=_iso(None),
            days=days,
            recent_sessions=session_history.sessions[-5:],
            body_metrics=body_metrics,
            progression_signals=session_history.signals,
            weekly_direct_sets=muscle_history.muscles,
            personal_records=personal_records,
            notes=notes,
        )

    def undo_last_entry(
        self,
        kind: Literal["workout", "body_metrics"],
        entry_id: int | None = None,
    ) -> DeletedEntry:
        if kind == "workout":
            session = (
                self._store.get_session(entry_id)
                if entry_id is not None
                else self._store.latest_session()
            )
            if session is None:
                raise ValueError("No workout entry to delete")
            session_id = int(session["id"])
            rows = self._store.get_sets(session_id=session_id)
            working = [row for row in rows if not row["is_warmup"]]
            volume = round(
                sum(row["weight_kg"] * row["reps"] for row in working), 1
            )
            summary = (
                f"{session['performed_at']} 운동 세션, "
                f"{len(working)}세트, {volume}kg"
            )
            self._store.delete_session(session_id)
            return DeletedEntry(kind=kind, id=session_id, summary=summary)

        metric = (
            self._store.get_body_metric(entry_id)
            if entry_id is not None
            else self._store.latest_body_metric()
        )
        if metric is None:
            raise ValueError("No body metric entry to delete")
        metric_id = int(metric["id"])
        summary = f"{metric['measured_at']} 신체 측정"
        self._store.delete_body_metric(metric_id)
        return DeletedEntry(kind=kind, id=metric_id, summary=summary)

    def export_data(
        self,
        format: Literal["json", "markdown"] = "json",
    ) -> ExportResult:
        sessions = self._store.all_sessions()
        sets = self._store.get_sets()
        metrics = self._store.all_body_metrics()
        self._store.export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        extension = "json" if format == "json" else "md"
        path = self._store.export_dir / f"yee-doowang-{stamp}.{extension}"
        if format == "json":
            content = json.dumps(
                {
                    "exported_at": _iso(None),
                    "sessions": [
                        {
                            "session": session,
                            "sets": [
                                item
                                for item in sets
                                if item["session_id"] == session["id"]
                            ],
                        }
                        for session in sessions
                    ],
                    "body_metrics": metrics,
                },
                ensure_ascii=False,
                indent=2,
            )
        else:
            content = _markdown_export(sessions, sets, metrics)
        path.write_text(content, encoding="utf-8")
        return ExportResult(
            path=str(path),
            format=format,
            sessions=len(sessions),
            sets=len(sets),
            body_metrics=len(metrics),
        )

    def _resolve_exercise(self, item: ExerciseInput) -> ExerciseRecord:
        if item.exercise_id is not None:
            return self._catalog.exercise(item.exercise_id)
        if item.name is None:
            raise ValueError("exercise name or exercise_id is required")
        resolution = self._catalog.resolve_terms(item.name, locale="ko", limit=10)
        matches = [match for match in resolution.matches if match.kind == "exercise"]
        if len(matches) == 1:
            return self._catalog.exercise(matches[0].id)
        if not matches:
            raise ValueError(
                f"Unknown exercise name: {item.name}. "
                "Use a catalog name or pass exercise_id."
            )
        candidates = "; ".join(f"{match.id} {match.label}" for match in matches)
        raise ValueError(
            f"Ambiguous exercise name: {item.name}. Candidates: {candidates}"
        )

    def _history_exercise_id(
        self,
        request: WorkoutHistoryRequest,
    ) -> str | None:
        if request.exercise_id is not None:
            self._catalog.exercise(request.exercise_id)
            return request.exercise_id
        if request.exercise is None:
            return None
        resolution = self._catalog.resolve_terms(
            request.exercise, locale="ko", limit=10
        )
        matches = [match for match in resolution.matches if match.kind == "exercise"]
        if len(matches) == 1:
            return matches[0].id
        if not matches:
            raise ValueError(f"Unknown exercise name: {request.exercise}")
        candidates = "; ".join(f"{match.id} {match.label}" for match in matches)
        raise ValueError(
            f"Ambiguous exercise name: {request.exercise}. Candidates: {candidates}"
        )

    def _session_result(
        self,
        session_id: int,
        rows: list[dict[str, Any]],
        locale: Locale,
        duplicate: bool = False,
    ) -> WorkoutLogResult:
        session = self._store.get_session(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        working = [row for row in rows if not row["is_warmup"]]
        return WorkoutLogResult(
            session_id=session_id,
            performed_at=session["performed_at"],
            exercises=self._logged_exercises(rows, locale),
            total_volume_kg=round(
                sum(row["weight_kg"] * row["reps"] for row in working), 1
            ),
            working_sets=len(working),
            muscle_sets=self._muscle_sets(rows, locale),
            new_prs=[],
            notes=session["notes"],
            duplicate=duplicate,
        )

    def _logged_exercises(
        self,
        rows: list[dict[str, Any]],
        locale: Locale,
    ) -> list[LoggedExercise]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(row["exercise_id"], []).append(row)
        result: list[LoggedExercise] = []
        for exercise_id, group in groups.items():
            exercise, display_name = self._display(
                exercise_id, group[0]["exercise_name"], locale
            )
            working = [row for row in group if not row["is_warmup"]]
            estimates = [
                _e1rm(row["weight_kg"], row["reps"]) for row in working
            ]
            estimates = [value for value in estimates if value is not None]
            result.append(
                LoggedExercise(
                    exercise_id=exercise_id,
                    exercise_name=group[0]["exercise_name"],
                    display_name=display_name,
                    primary_muscle=(
                        self._catalog.reference(
                            "muscle", exercise.primary_muscle_id, locale
                        )
                        if exercise is not None
                        else None
                    ),
                    working_sets=len(working),
                    volume_kg=round(
                        sum(row["weight_kg"] * row["reps"] for row in working),
                        1,
                    ),
                    best_e1rm_kg=max(estimates) if estimates else None,
                )
            )
        return result

    def _muscle_sets(
        self,
        rows: list[dict[str, Any]],
        locale: Locale,
    ) -> list[MuscleSetCount]:
        working = [row for row in rows if not row["is_warmup"]]
        roles = self._roles_for(working)
        counts: dict[str, int] = {}
        for row in working:
            role = roles.get(row["exercise_id"])
            if role is None:
                continue
            for muscle_id in role.direct:
                counts[muscle_id] = counts.get(muscle_id, 0) + 1
        order = {
            muscle_id: index
            for index, muscle_id in enumerate(self._catalog.muscle_ids())
        }
        return [
            MuscleSetCount(
                muscle=self._catalog.reference("muscle", muscle_id, locale),
                sets=counts[muscle_id],
            )
            for muscle_id in sorted(counts, key=order.get)
        ]

    def _sessions(
        self,
        rows: list[dict[str, Any]],
        locale: Locale,
        include_sets: bool,
    ) -> list[HistorySession]:
        groups: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(int(row["session_id"]), []).append(row)
        sessions: list[HistorySession] = []
        for session_id, group in groups.items():
            session = self._store.get_session(session_id)
            if session is None:
                continue
            working = [row for row in group if not row["is_warmup"]]
            history_sets = None
            if include_sets:
                history_sets = [
                    HistorySet(
                        exercise_id=row["exercise_id"],
                        exercise_name=row["exercise_name"],
                        display_name=self._display(
                            row["exercise_id"], row["exercise_name"], locale
                        )[1],
                        set_index=row["set_index"],
                        weight_kg=row["weight_kg"],
                        reps=row["reps"],
                        rpe=row["rpe"],
                        is_warmup=bool(row["is_warmup"]),
                        volume_kg=round(
                            0
                            if row["is_warmup"]
                            else row["weight_kg"] * row["reps"],
                            1,
                        ),
                    )
                    for row in group
                ]
            sessions.append(
                HistorySession(
                    session_id=session_id,
                    performed_at=session["performed_at"],
                    notes=session["notes"],
                    total_volume_kg=round(
                        sum(row["weight_kg"] * row["reps"] for row in working),
                        1,
                    ),
                    working_sets=len(working),
                    exercises=self._logged_exercises(group, locale),
                    sets=history_sets,
                )
            )
        return sessions

    def _exercise_history(
        self,
        rows: list[dict[str, Any]],
        locale: Locale,
    ) -> list[ExerciseHistory]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(row["exercise_id"], []).append(row)
        result: list[ExerciseHistory] = []
        for exercise_id, group in groups.items():
            working = [row for row in group if not row["is_warmup"]]
            if not working:
                continue
            estimates = [
                _e1rm(row["weight_kg"], row["reps"]) for row in working
            ]
            estimates = [value for value in estimates if value is not None]
            display_name = self._display(
                exercise_id, group[0]["exercise_name"], locale
            )[1]
            result.append(
                ExerciseHistory(
                    exercise_id=exercise_id,
                    exercise_name=group[0]["exercise_name"],
                    display_name=display_name,
                    sessions=len({row["session_id"] for row in working}),
                    working_sets=len(working),
                    total_volume_kg=round(
                        sum(row["weight_kg"] * row["reps"] for row in working),
                        1,
                    ),
                    best_weight_kg=max(row["weight_kg"] for row in working),
                    best_e1rm_kg=max(estimates) if estimates else None,
                    last_performed_at=max(row["performed_at"] for row in working),
                )
            )
        result.sort(key=lambda item: item.total_volume_kg, reverse=True)
        return result

    def _week_history(self, rows: list[dict[str, Any]]) -> list[WeekHistory]:
        stats: dict[date, dict[str, Any]] = {}
        for row in rows:
            moment = _parse_datetime(row["performed_at"])
            if moment is None:
                continue
            week_start = moment.date() - timedelta(days=moment.weekday())
            entry = stats.setdefault(
                week_start,
                {"sessions": set(), "working_sets": 0, "volume": 0.0},
            )
            entry["sessions"].add(row["session_id"])
            if not row["is_warmup"]:
                entry["working_sets"] += 1
                entry["volume"] += row["weight_kg"] * row["reps"]
        return [
            WeekHistory(
                week_start=week_start,
                sessions=len(entry["sessions"]),
                working_sets=entry["working_sets"],
                total_volume_kg=round(entry["volume"], 1),
            )
            for week_start, entry in sorted(stats.items())
        ]

    def _muscle_history(
        self,
        rows: list[dict[str, Any]],
        locale: Locale,
    ) -> list[MuscleHistory]:
        working = [row for row in rows if not row["is_warmup"]]
        roles = self._roles_for(working)
        stats: dict[str, dict[str, float]] = {}
        for row in working:
            role = roles.get(row["exercise_id"])
            if role is None:
                continue
            for muscle_id in role.direct:
                entry = stats.setdefault(muscle_id, {"sets": 0, "volume": 0.0})
                entry["sets"] += 1
                entry["volume"] += row["weight_kg"] * row["reps"]
        order = {
            muscle_id: index
            for index, muscle_id in enumerate(self._catalog.muscle_ids())
        }
        return [
            MuscleHistory(
                muscle=self._catalog.reference("muscle", muscle_id, locale),
                direct_sets=int(stats[muscle_id]["sets"]),
                volume_kg=round(stats[muscle_id]["volume"], 1),
            )
            for muscle_id in sorted(
                stats, key=lambda item: (-stats[item]["sets"], order.get(item, 0))
            )
        ]

    def _signals(
        self,
        rows: list[dict[str, Any]],
        locale: Locale,
    ) -> list[ProgressionSignal]:
        best_by_exercise: dict[str, dict[int, tuple[str, float]]] = {}
        names: dict[str, str] = {}
        for row in rows:
            if row["is_warmup"]:
                continue
            estimate = _e1rm(row["weight_kg"], row["reps"])
            if estimate is None:
                continue
            exercise_id = row["exercise_id"]
            names[exercise_id] = row["exercise_name"]
            sessions = best_by_exercise.setdefault(exercise_id, {})
            current = sessions.get(row["session_id"])
            if current is None or estimate > current[1]:
                sessions[row["session_id"]] = (row["performed_at"], estimate)
        signals: list[ProgressionSignal] = []
        for exercise_id, sessions in best_by_exercise.items():
            ordered = sorted(sessions.values())
            display_name = self._display(
                exercise_id, names[exercise_id], locale
            )[1]
            if len(ordered) < 2:
                signals.append(
                    ProgressionSignal(
                        exercise_id=exercise_id,
                        exercise_name=names[exercise_id],
                        display_name=display_name,
                        sessions=len(ordered),
                        first_e1rm_kg=ordered[0][1] if ordered else None,
                        last_e1rm_kg=ordered[-1][1] if ordered else None,
                        change_pct=None,
                        trend="insufficient_data",
                        message="운동 세션 기록이 2개 미만이라 추세를 판단하지 않는다.",
                    )
                )
                continue
            first = ordered[0][1]
            last = ordered[-1][1]
            change = round((last - first) / first * 100, 1) if first else None
            if change is None:
                trend: Trend = "insufficient_data"
            elif change >= 2:
                trend = "up"
            elif change <= -2:
                trend = "down"
            else:
                trend = "flat"
            message = {
                "up": f"e1RM이 {change}% 증가했다.",
                "down": f"e1RM이 {abs(change)}% 감소했다.",
                "flat": "e1RM 변화가 2% 미만이다.",
                "insufficient_data": "추세를 판단할 수 없다.",
            }[trend]
            signals.append(
                ProgressionSignal(
                    exercise_id=exercise_id,
                    exercise_name=names[exercise_id],
                    display_name=display_name,
                    sessions=len(ordered),
                    first_e1rm_kg=first,
                    last_e1rm_kg=last,
                    change_pct=change,
                    trend=trend,
                    message=message,
                )
            )
        return signals

    def _all_time_records(self, locale: Locale) -> list[PersonalRecord]:
        rows = self._store.get_sets()
        best: dict[str, tuple[float, dict[str, Any]]] = {}
        for row in rows:
            if row["is_warmup"]:
                continue
            estimate = _e1rm(row["weight_kg"], row["reps"])
            if estimate is None:
                continue
            current = best.get(row["exercise_id"])
            if current is None or estimate > current[0]:
                best[row["exercise_id"]] = (estimate, row)
        records = []
        for exercise_id, (estimate, row) in best.items():
            _, display_name = self._display(
                exercise_id, row["exercise_name"], locale
            )
            records.append(
                PersonalRecord(
                    exercise_id=exercise_id,
                    exercise_name=row["exercise_name"],
                    display_name=display_name,
                    e1rm_kg=estimate,
                    previous_e1rm_kg=None,
                    weight_kg=row["weight_kg"],
                    reps=row["reps"],
                    performed_at=row["performed_at"],
                )
            )
        records.sort(key=lambda item: item.e1rm_kg, reverse=True)
        return records[:10]

    def _best_e1rm(self, exercise_id: str) -> float | None:
        rows = self._store.get_sets(exercise_id=exercise_id)
        estimates = [
            _e1rm(row["weight_kg"], row["reps"])
            for row in rows
            if not row["is_warmup"]
        ]
        estimates = [value for value in estimates if value is not None]
        return max(estimates) if estimates else None

    def _roles_for(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, MuscleRoles]:
        exercise_ids: list[str] = []
        for row in rows:
            exercise_id = row["exercise_id"]
            if exercise_id in exercise_ids:
                continue
            try:
                self._catalog.exercise(exercise_id)
            except ValueError:
                continue
            exercise_ids.append(exercise_id)
        return self._ontology.muscle_roles(exercise_ids) if exercise_ids else {}

    def _display(
        self,
        exercise_id: str,
        fallback: str,
        locale: Locale,
    ) -> tuple[ExerciseRecord | None, str]:
        try:
            exercise = self._catalog.exercise(exercise_id)
        except ValueError:
            return None, fallback
        return exercise, self._catalog.summary(exercise, locale).display_name


def _now() -> datetime:
    return datetime.now().astimezone()


def _today() -> date:
    return _now().date()


def _iso(moment: datetime | None) -> str:
    value = moment or _now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=_now().tzinfo)
    return value.isoformat(timespec="seconds")


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _e1rm(weight_kg: float, reps: int) -> float | None:
    if weight_kg <= 0 or not 1 <= reps <= 30:
        return None
    return round(epley_1rm(weight_kg, reps), 1)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _body_record(row: dict[str, Any]) -> BodyMetricRecord:
    return BodyMetricRecord(
        id=int(row["id"]),
        measured_at=row["measured_at"],
        body_weight_kg=row["body_weight_kg"],
        body_fat_percent=row["body_fat_percent"],
        sleep_hours=row["sleep_hours"],
        fatigue=row["fatigue"],
        notes=row["notes"],
    )


def _markdown_export(
    sessions: list[dict[str, Any]],
    sets: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> str:
    lines = ["# 이두왕 운동 기록", "", f"내보낸 시각: {_iso(None)}", "", "## 운동"]
    for session in sessions:
        lines.append("")
        lines.append(f"### {session['performed_at']}")
        if session["notes"]:
            lines.append(f"메모: {session['notes']}")
        for row in sets:
            if row["session_id"] != session["id"]:
                continue
            warmup = " (웜업)" if row["is_warmup"] else ""
            rpe = f" @RPE {row['rpe']}" if row["rpe"] is not None else ""
            weight = "-" if row["weight_kg"] == 0 else f"{row['weight_kg']}kg"
            lines.append(
                f"- {row['exercise_name']}: "
                f"{weight} × {row['reps']}회{warmup}{rpe}"
            )
    lines.extend(["", "## 신체 측정"])
    for metric in metrics:
        weight = metric["body_weight_kg"]
        body_fat = metric["body_fat_percent"]
        sleep = metric["sleep_hours"]
        fatigue = metric["fatigue"]
        lines.append(
            f"- {metric['measured_at']}: "
            f"체중 {weight if weight is not None else '-'}kg, "
            f"체지방 {body_fat if body_fat is not None else '-'}%, "
            f"수면 {sleep if sleep is not None else '-'}시간, "
            f"피로도 {fatigue if fatigue is not None else '-'}"
        )
    return "\n".join(lines) + "\n"
