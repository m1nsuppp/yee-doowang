from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yee_doowang_api.application.exercise_catalog import (
    Equipment,
    Exercise,
    ExerciseRecommendationProfile,
    Muscle,
    TechnicalComplexity,
    WorkoutDay,
)
from yee_doowang_api.application.hypertrophy_prescription import HypertrophyPrescription


class _ChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextField[T](_ChatModel):
    status: Literal["not_asked", "provided", "unknown", "skipped", "delegated"] = "not_asked"
    value: T | None = None

    @model_validator(mode="after")
    def validate_status_value(self) -> ContextField[T]:
        if (self.status == "provided") != (self.value is not None):
            raise ValueError("only provided context fields may contain a value")
        return self
class SessionTimeRange(_ChatModel):
    minimum_minutes: int = Field(gt=0)
    maximum_minutes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> SessionTimeRange:
        if self.minimum_minutes >= self.maximum_minutes:
            raise ValueError("time range minimum must be less than maximum")
        return self


class WorkoutSplitTemplate(_ChatModel):
    day_a_ids: list[str] = Field(min_length=1)
    day_b_ids: list[str] = Field(min_length=1)
    confirmation_status: Literal["user_provided", "proposed", "confirmed"] = "user_provided"

    @model_validator(mode="after")
    def validate_day_groups(self) -> WorkoutSplitTemplate:
        if len(self.day_a_ids) != len(set(self.day_a_ids)) or len(self.day_b_ids) != len(set(self.day_b_ids)):
            raise ValueError("workout split groups must not repeat workout days")
        if set(self.day_a_ids) & set(self.day_b_ids):
            raise ValueError("workout split groups must be distinct")
        return self

class WorkoutDayRecommendation(_ChatModel):
    workout_day_ids: list[str] = Field(min_length=1, max_length=3)
    rationale: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_unique_workout_days(self) -> WorkoutDayRecommendation:
        if len(self.workout_day_ids) != len(set(self.workout_day_ids)):
            raise ValueError("recommended workout days must be unique")
        return self




class QuickReply(_ChatModel):
    label: str
    message: str




class ConversationMessage(_ChatModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, content: str) -> str:
        content = content.strip()
        if not content:
            raise ValueError("message content must not be blank")
        return content


class EquipmentIntent(_ChatModel):
    mode: Literal["specified", "unknown", "delegate_any"]
    equipment_ids: list[str]

    @model_validator(mode="after")
    def validate_equipment_ids(self) -> EquipmentIntent:
        if self.mode == "specified" and not self.equipment_ids:
            raise ValueError("specified equipment requires at least one ID")
        if self.mode != "specified" and self.equipment_ids:
            raise ValueError("only specified equipment may include IDs")
        return self


class RoutineContext(_ChatModel):
    workout_day_ids: ContextField[list[str]] = Field(default_factory=ContextField)
    goal: ContextField[Literal["hypertrophy", "strength", "both", "other"]] = Field(
        default_factory=ContextField
    )
    experience: ContextField[Literal["novice", "experienced"]] = Field(
        default_factory=ContextField
    )
    sessions_per_week: ContextField[int] = Field(default_factory=ContextField)
    minutes_per_session: ContextField[int] = Field(default_factory=ContextField)
    minutes_per_session_range: ContextField[SessionTimeRange] = Field(default_factory=ContextField)
    equipment: ContextField[EquipmentIntent] = Field(default_factory=ContextField)
    preferences: ContextField[list[str]] = Field(default_factory=ContextField)
    known_constraints: ContextField[list[str]] = Field(default_factory=ContextField)
    adult_eligibility: ContextField[Literal["adult", "minor"]] = Field(
        default_factory=ContextField
    )
    weekly_direct_sets_by_muscle: ContextField[dict[str, int]] = Field(
        default_factory=ContextField
    )
    workout_split_type: ContextField[Literal["ab"]] = Field(default_factory=ContextField)
    workout_split_assignment: ContextField[WorkoutSplitTemplate] = Field(default_factory=ContextField)
    weekly_direct_sets_follow_up: ContextField[Literal["remaining"]] = Field(default_factory=ContextField)
    split_proposal_rejected: bool = False
    split_template: WorkoutSplitTemplate | None = None

    @model_validator(mode="after")
    def validate_schedule_context(self) -> RoutineContext:
        if self.workout_day_ids.status == "provided":
            day_ids = self.workout_day_ids.value or []
            if not day_ids:
                raise ValueError("provided workout days must not be empty")
            if len(day_ids) != len(set(day_ids)):
                raise ValueError("workout day IDs must be unique")
        if self.sessions_per_week.status == "provided" and not 1 <= self.sessions_per_week.value <= 7:
            raise ValueError("sessions per week must be between 1 and 7")
        if self.minutes_per_session.status == "provided" and self.minutes_per_session.value <= 0:
            raise ValueError("session minutes must be positive")
        if self.workout_split_assignment.status == "provided":
            if self.workout_split_type.status != "provided":
                raise ValueError("an A/B assignment requires a requested A/B split")
            template = self.workout_split_assignment.value
            if template.confirmation_status != "user_provided":
                raise ValueError("user split assignments must be explicitly supplied")
        if self.split_template is not None:
            if self.workout_split_type.status != "provided":
                raise ValueError("an assistant split proposal requires an A/B split request")
            if self.split_template.confirmation_status not in {"proposed", "confirmed"}:
                raise ValueError("assistant split templates must be proposed or confirmed")
        if self.minutes_per_session_range.status == "provided":
            time_range = self.minutes_per_session_range.value
            if self.minutes_per_session.status == "provided" and not (
                time_range.minimum_minutes <= self.minutes_per_session.value <= time_range.maximum_minutes
            ):
                raise ValueError("session target must fall within the reported time range")
        if self.weekly_direct_sets_by_muscle.status == "provided":
            set_counts = self.weekly_direct_sets_by_muscle.value or {}
            if not set_counts or any(count < 0 for count in set_counts.values()):
                raise ValueError("reported weekly direct sets must be non-negative and non-empty")
        return self


class RecommendationPreferences(_ChatModel):
    goal: Literal["hypertrophy", "strength", "both", "skip", "unknown", "unsupported"]
    experience: Literal["novice", "experienced", "skip", "unknown"]


class CoachTurn(_ChatModel):
    context: RoutineContext
    safety_status: Literal["none", "clarify", "urgent"]
    message: str = Field(max_length=1200)
    assistant_response: str = Field(default="", max_length=1200)
    conversation_action: Literal[
        "start_routine", "continue_intake", "answer_only", "cancel_routine"
    ] = "continue_intake"
    explicit_minutes_target: bool = False
    split_confirmation: Literal["none", "confirm", "reject", "repropose"] = "none"
    recommendation_confirmation: Literal[
        "none", "accept", "reject", "repropose"
    ] = "none"


    @field_validator("message")
    @classmethod
    def normalize_message(cls, message: str) -> str:
        return message.strip()

    @field_validator("assistant_response")
    @classmethod
    def normalize_assistant_response(cls, response: str) -> str:
        return response.strip()



class EquipmentConstraint(_ChatModel):
    mode: Literal["specified", "unrestricted"]
    equipment_ids: list[str]

    @model_validator(mode="after")
    def validate_equipment_ids(self) -> EquipmentConstraint:
        if self.mode == "specified" and not self.equipment_ids:
            raise ValueError("specified equipment requires at least one ID")
        if self.mode == "unrestricted" and self.equipment_ids:
            raise ValueError("unrestricted equipment cannot include IDs")
        return self


class RecommendedExercise(_ChatModel):
    source_id: str
    name: str
    name_ko: str | None
    primary_muscle_ko: str
    secondary_muscles_ko: list[str]
    equipment_ko: str
    movement_pattern_ko: str | None
    technical_complexity: TechnicalComplexity | None


class PlannedExercise(_ChatModel):
    source_id: str = Field(pattern=r"^[0-9]{4}$")
    alternative_source_ids: list[str] = Field(default_factory=list)


class PlannedSession(_ChatModel):
    workout_day_id: str
    exercises: list[PlannedExercise] = Field(min_length=1)


class RoutineProposal(_ChatModel):
    sessions: list[PlannedSession] = Field(min_length=1)


class RoutineExercise(_ChatModel):
    exercise: RecommendedExercise
    rationale: str
    alternatives: list[RecommendedExercise]


class RoutineSession(_ChatModel):
    index: int = Field(ge=1)
    workout_day_id: str
    workout_day_name_ko: str
    exercises: list[RoutineExercise]


class RoutineDraft(_ChatModel):
    sessions_per_week: int | None
    minutes_per_session: int | None
    sessions: list[RoutineSession]
    hypertrophy_prescription: HypertrophyPrescription | None = None
    prescription_note: str | None = None

class ConversationState(_ChatModel):
    mode: Literal["general", "routine"] = "routine"
    phase: Literal["collecting_context", "confirming_context", "confirming_split", "reviewing_routine"] = (
        "collecting_context"
    )
    context: RoutineContext = Field(default_factory=RoutineContext)
    routine: RoutineDraft | None = None
    workout_day_recommendation: WorkoutDayRecommendation | None = None

    @model_validator(mode="after")
    def validate_conversation_state(self) -> ConversationState:
        if (self.phase == "reviewing_routine") != (self.routine is not None):
            raise ValueError("only a reviewed routine may contain a routine draft")
        if self.phase == "confirming_split" and (
            self.context.split_template is None
            or self.context.split_template.confirmation_status != "proposed"
        ):
            raise ValueError("only an unconfirmed split proposal may be confirmed")
        if (
            self.workout_day_recommendation is not None
            and self.context.workout_day_ids.status != "delegated"
        ):
            raise ValueError("a workout-day recommendation requires delegated selection")
        return self


ChatAction = Literal["message", "confirm_context"]


class ChatReply(_ChatModel):
    reply: str
    state: ConversationState
    exploration_exercises: list[RecommendedExercise]
    quick_replies: list[QuickReply] = Field(default_factory=list)


class ChatCompletionError(Exception):
    """A safe, provider-independent chat model failure."""


class CoachModel(Protocol):
    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        current_context: RoutineContext,
        current_mode: Literal["general", "routine"],
        equipment_options: Sequence[Equipment],
        workout_days: Sequence[WorkoutDay],
        current_recommendation: WorkoutDayRecommendation | None,
        muscles: Sequence[Muscle],
    ) -> CoachTurn: ...

    async def recommend_workout_days(
        self,
        messages: Sequence[ConversationMessage],
        context: RoutineContext,
        workout_days: Sequence[WorkoutDay],
    ) -> WorkoutDayRecommendation: ...

    async def plan_routine(
        self,
        messages: Sequence[ConversationMessage],
        context: RoutineContext,
        candidates_by_day: dict[str, Sequence[Exercise]],
        workout_days: Sequence[WorkoutDay],
        recommendation_profiles: Sequence[ExerciseRecommendationProfile],
        current_routine: RoutineDraft | None,
    ) -> RoutineProposal: ...

class ExerciseReasoner(Protocol):
    async def recommend(
        self,
        *,
        workout_day_id: str,
        equipment_constraint: EquipmentConstraint,
    ) -> list[Exercise]: ...
