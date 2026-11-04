from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yee_doowang_api.application.exercise_catalog import (
    Equipment,
    Exercise,
    ExerciseCatalog,
    ExerciseRecommendationProfile,
    Muscle,
    TechnicalComplexity,
    WorkoutDay,
)
from yee_doowang_api.application.hypertrophy_prescription import (
    HypertrophyGuidelines,
    HypertrophyPrescription,
    HypertrophyProgressionRule,
    WeeklyDirectSetTarget,
)


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


_MAX_RECOMMENDED_CANDIDATES_PER_DAY = 5


class ChatService:
    def __init__(
        self,
        model: CoachModel,
        reasoner: ExerciseReasoner,
        catalog: ExerciseCatalog,
        hypertrophy_guidelines: HypertrophyGuidelines,
    ) -> None:
        self._model = model
        self._reasoner = reasoner
        self._catalog = catalog
        self._recommendation_profiles = {
            item.source_id: item for item in catalog.recommendations.profiles
        }
        self._hypertrophy_guidelines = hypertrophy_guidelines
        self._exercises_by_id = {
            exercise.source_id: exercise for exercise in catalog.exercises
        }
        self._muscles_by_id = {muscle.id: muscle for muscle in catalog.muscles}
        self._known_equipment_ids = {item.id for item in catalog.equipment}
        self._muscle_names = {
            item.id: item.name_ko or f"원문 근육명: {item.source_terms[0]}"
            for item in catalog.muscles
        }
        self._equipment_names = {
            item.id: item.name_ko or f"원문 장비명: {item.source_term}"
            for item in catalog.equipment
        }
        self._pattern_names = {
            item.id: item.name_ko for item in catalog.movement_patterns
        }

        self._workout_days_by_id = {
            day.id: day for day in catalog.workout_days
        }
        self._workout_day_names = {day.id: day.name_ko for day in catalog.workout_days}
        self._focus_muscle_ids_by_day = {
            day.id: set(day.focus_muscle_ids) for day in catalog.workout_days
        }

    async def reply(
        self,
        messages: Sequence[ConversationMessage],
        state: ConversationState,
        action: ChatAction,
    ) -> ChatReply:
        if action == "confirm_context" and (
            state.phase != "confirming_context" or state.mode != "routine"
        ):
            raise ValueError("Only a reviewed routine context can be confirmed")
        intent = await self._model.interpret(
            messages,
            state.context,
            state.mode,
            self._catalog.equipment,
            self._catalog.workout_days,
            state.workout_day_recommendation,
            self._catalog.muscles,
        )
        if state.mode == "general" and intent.conversation_action == "start_routine":
            previous_context = RoutineContext()
            context = self._merge_context(previous_context, intent.context)
            mode: Literal["general", "routine"] = "routine"
        elif intent.conversation_action == "answer_only":
            previous_context = state.context
            context = (
                self._merge_context(state.context, intent.context)
                if state.mode == "routine"
                else state.context
            )
            mode = state.mode
        else:
            previous_context = state.context
            context = self._merge_context(state.context, intent.context)
            mode = state.mode

        if (
            intent.conversation_action != "cancel_routine"
            and context != previous_context
            and not intent.explicit_minutes_target
        ):
            time_range_changed = (
                context.minutes_per_session_range
                != previous_context.minutes_per_session_range
            )
            target_changed = context.minutes_per_session != previous_context.minutes_per_session
            if (
                context.minutes_per_session_range.status == "provided"
                and (time_range_changed or target_changed)
                and context.minutes_per_session.status == "provided"
            ):
                data = context.model_dump()
                data["minutes_per_session"] = {"status": "unknown", "value": None}
                context = RoutineContext.model_validate(data)

        if intent.safety_status == "urgent":
            return ChatReply(
                reply=(
                    "말씀하신 증상은 즉시 평가가 필요할 수 있어요. "
                    "운동을 멈추고 지금 응급 진료를 받으세요."
                ),
                state=ConversationState(mode=mode, context=context),
                exploration_exercises=[],
            )
        if intent.safety_status == "clarify":
            fallback = (
                "운동 추천 전에 통증 위치와 어떤 동작에서 심해지는지 확인할게요. "
                "통증을 악화시키는 운동은 중단해 주세요."
            )
            return ChatReply(
                reply=intent.message or fallback,
                state=ConversationState(mode=mode, context=context),
                exploration_exercises=[],
            )

        if (
            action != "confirm_context"
            and intent.conversation_action == "cancel_routine"
            and state.mode == "routine"
        ):
            return ChatReply(
                reply="루틴 작성은 여기서 멈출게요. 다시 계획하고 싶을 때 말씀해 주세요.",
                state=ConversationState(mode="general"),
                exploration_exercises=[],
            )
        if action != "confirm_context" and (
            intent.conversation_action == "answer_only"
            or (state.mode == "general" and intent.conversation_action != "start_routine")
        ):
            response_state = state
            if state.mode == "routine" and context != state.context:
                phase = (
                    "confirming_split"
                    if state.phase == "confirming_split" and context.split_template is not None
                    else "collecting_context"
                )
                response_state = ConversationState(
                    mode="routine",
                    phase=phase,
                    context=context,
                )
            return ChatReply(
                reply=intent.assistant_response or "편하게 이어서 말씀해 주세요.",
                state=response_state,
                exploration_exercises=[],
                quick_replies=self._pending_quick_replies(response_state),
            )

        response_prefix = ""
        invalid_split_reply = self._invalid_split_configuration_reply(context)
        if invalid_split_reply is not None:
            return invalid_split_reply

        unknown_days = (
            set(context.workout_day_ids.value or []) - self._workout_day_names.keys()
            if context.workout_day_ids.status == "provided"
            else set()
        )
        if unknown_days:
            return ChatReply(
                reply=self._supported_workout_days_reply(),
                state=ConversationState(mode=mode, context=previous_context),
                exploration_exercises=[],
            )

        equipment = context.equipment.value
        if (
            context.equipment.status == "provided"
            and equipment is not None
            and equipment.mode == "specified"
            and set(equipment.equipment_ids) - self._known_equipment_ids
        ):
            return ChatReply(
                reply=self._equipment_options_reply(),
                state=ConversationState(mode=mode, context=previous_context),
                exploration_exercises=[],
            )
        if context.weekly_direct_sets_by_muscle.status == "provided":
            reported_muscle_ids = set(context.weekly_direct_sets_by_muscle.value or {})
            if reported_muscle_ids - self._muscles_by_id.keys():
                return ChatReply(
                    reply="최근 주간 세트 수에는 카탈로그의 표적 근육만 사용할 수 있어요. 부위별 세트 수를 다시 알려주세요.",
                    state=ConversationState(mode=mode, context=previous_context),
                    exploration_exercises=[],
                )

        if self._has_unresolved_constraints(context.known_constraints):
            return ChatReply(
                reply=(
                    "알려주신 제약을 운동별 금기로 임의 해석하지 않겠습니다. "
                    "현재 통증·부상·의료상 제한이면 안전 확인이 필요해요. "
                    "특정 운동이나 동작을 피하려는 선호라면 선호 항목에 구체적으로 적고, "
                    "제약은 건너뛰어 주세요."
                ),
                state=ConversationState(mode="routine", context=context),
                exploration_exercises=[],
            )
        proposal = state.workout_day_recommendation
        if proposal is not None:
            if intent.recommendation_confirmation == "accept":
                data = context.model_dump()
                data["workout_day_ids"] = {
                    "status": "provided",
                    "value": proposal.workout_day_ids,
                }
                context = RoutineContext.model_validate(data)
                response_prefix = "좋아요. 추천한 운동 부위를 반영했어요."
            elif context.workout_day_ids != state.context.workout_day_ids:
                proposal = None
            elif intent.recommendation_confirmation == "repropose":
                return await self._propose_workout_days(messages, context)
            elif intent.recommendation_confirmation == "reject":
                data = context.model_dump()
                data["workout_day_ids"] = {"status": "not_asked", "value": None}
                context = RoutineContext.model_validate(data)
                return ChatReply(
                    reply=self._next_context_question(context) or "운동 부위를 직접 골라주세요.",
                    state=ConversationState(mode="routine", context=context),
                    exploration_exercises=[],
                    quick_replies=self._workout_day_selection_quick_replies(),
                )
            elif context != state.context:
                if context.workout_day_ids.status == "delegated":
                    return await self._propose_workout_days(messages, context)
                proposal = None
            else:
                return ChatReply(
                    reply=self._workout_day_recommendation_prompt(proposal),
                    state=state,
                    exploration_exercises=[],
                    quick_replies=self._workout_day_recommendation_quick_replies(),
                )

        if context.workout_day_ids.status == "delegated" and proposal is None:
            return await self._propose_workout_days(messages, context)

        if intent.split_confirmation == "repropose" and context.split_proposal_rejected:
            data = context.model_dump()
            data["split_proposal_rejected"] = False
            context = RoutineContext.model_validate(data)
            return self._propose_split(context)
        if state.phase == "confirming_split" and context.split_template is not None:
            if intent.split_confirmation == "confirm":
                context = self._replace_split_template_status(context, "confirmed")
                response_prefix = "A/B 분할을 확인했어요."
            elif intent.split_confirmation == "reject":
                context = self._reject_split_proposal(context)
                return ChatReply(
                    reply=self._split_assignment_question(context),
                    state=ConversationState(mode="routine", context=context),
                    exploration_exercises=[],
                    quick_replies=self._split_assignment_quick_replies(),
                )
            else:
                return ChatReply(
                    reply=self._split_confirmation_prompt(context),
                    state=ConversationState(mode="routine", phase="confirming_split", context=context),
                    exploration_exercises=[],
                    quick_replies=self._split_quick_replies(),
                )


        question = self._next_context_question(context)
        if question is not None:
            return ChatReply(
                reply="\n\n".join(part for part in (response_prefix, question) if part),
                state=ConversationState(mode="routine", context=context),
                exploration_exercises=[],
                quick_replies=self._context_question_quick_replies(context),
            )

        if (
            context.workout_split_type.status == "provided"
            and context.workout_split_assignment.status == "delegated"
            and context.split_template is None
            and not context.split_proposal_rejected
        ):
            return self._propose_split(context)

        if action == "confirm_context":
            if context != state.context:
                return ChatReply(
                    reply=self._context_summary(context),
                    state=ConversationState(
                        mode="routine",
                        phase="confirming_context",
                        context=context,
                    ),
                    exploration_exercises=[],
                )
            return await self._draft_routine(messages, state)
        if state.phase == "reviewing_routine" and context == state.context:
            return await self._draft_routine(messages, state)

        return ChatReply(
            reply="\n\n".join(part for part in (response_prefix, self._context_summary(context)) if part),
            state=ConversationState(mode="routine", phase="confirming_context", context=context),
            exploration_exercises=[],
        )


    async def _propose_workout_days(
        self,
        messages: Sequence[ConversationMessage],
        context: RoutineContext,
    ) -> ChatReply:
        recommendation = await self._model.recommend_workout_days(
            messages,
            context,
            self._catalog.workout_days,
        )
        unknown_ids = set(recommendation.workout_day_ids) - self._workout_day_names.keys()
        if unknown_ids:
            raise ChatCompletionError("Workout-day recommendation contained unsupported IDs")
        return ChatReply(
            reply=self._workout_day_recommendation_prompt(recommendation),
            state=ConversationState(
                mode="routine",
                context=context,
                workout_day_recommendation=recommendation,
            ),
            exploration_exercises=[],
            quick_replies=self._workout_day_recommendation_quick_replies(),
        )

    def _workout_day_recommendation_prompt(
        self,
        recommendation: WorkoutDayRecommendation,
    ) -> str:
        names = ", ".join(
            self._workout_day_names[item]
            for item in recommendation.workout_day_ids
        )
        return (
            f"시작점으로 살펴볼 운동 부위는 다음과 같아요: {names}. "
            f"{recommendation.rationale} 이 부위들로 진행할까요?"
        )

    @staticmethod
    def _workout_day_recommendation_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="이 부위로 진행", message="추천한 운동 부위로 진행해줘"),
            QuickReply(label="다른 추천", message="다른 운동 부위를 다시 추천해줘"),
            QuickReply(label="직접 고르기", message="추천한 부위 대신 직접 고를게"),
        ]

    @staticmethod
    def _workout_day_selection_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="다른 추천", message="다른 운동 부위를 다시 추천해줘"),
            QuickReply(label="직접 고르기", message="운동 부위를 직접 고를게"),
        ]

    def _pending_quick_replies(self, state: ConversationState) -> list[QuickReply]:
        if state.workout_day_recommendation is not None:
            return self._workout_day_recommendation_quick_replies()
        if state.phase == "confirming_split":
            return self._split_quick_replies()
        return []

    @staticmethod
    def _merge_context(previous: RoutineContext, updates: RoutineContext) -> RoutineContext:
        merged = previous.model_dump()
        changed_fields: set[str] = set()
        system_fields = {"split_template", "split_proposal_rejected"}
        stopped_set_report: Literal["unknown", "skipped", "delegated"] | None = None
        for field_name in RoutineContext.model_fields:
            if field_name in system_fields:
                continue
            previous_field = getattr(previous, field_name)
            update_field = getattr(updates, field_name)
            if update_field.status == "not_asked":
                continue
            if update_field.model_dump() != previous_field.model_dump():
                changed_fields.add(field_name)
            if field_name == "weekly_direct_sets_by_muscle" and previous_field.status == "provided":
                if update_field.status == "provided":
                    values = dict(previous_field.value or {})
                    values.update(update_field.value or {})
                    merged[field_name] = {"status": "provided", "value": values}
                elif update_field.status in {"unknown", "skipped", "delegated"}:
                    merged[field_name] = previous_field.model_dump()
                    stopped_set_report = update_field.status
                else:
                    merged[field_name] = update_field.model_dump()
            else:
                merged[field_name] = update_field.model_dump()

        if stopped_set_report is not None:
            follow_up_status = updates.weekly_direct_sets_follow_up.status
            if follow_up_status not in {"unknown", "skipped", "delegated"}:
                follow_up_status = stopped_set_report
            merged["weekly_direct_sets_follow_up"] = {
                "status": follow_up_status,
                "value": None,
            }
        if merged["workout_split_type"]["status"] == "skipped":
            merged["workout_split_assignment"] = {
                "status": "skipped",
                "value": None,
            }
        context_changed_days = "workout_day_ids" in changed_fields
        split_request_changed = bool(
            changed_fields & {"workout_split_type", "workout_split_assignment"}
        )
        if context_changed_days or split_request_changed:
            merged["split_template"] = None
            merged["split_proposal_rejected"] = False
        else:
            merged["split_template"] = (
                previous.split_template.model_dump()
                if previous.split_template is not None
                else None
            )
            merged["split_proposal_rejected"] = previous.split_proposal_rejected

        return RoutineContext.model_validate(merged)

    @staticmethod
    def _replace_split_template_status(
        context: RoutineContext,
        status: Literal["proposed", "confirmed"],
    ) -> RoutineContext:
        data = context.model_dump()
        template = data["split_template"]
        template["confirmation_status"] = status
        return RoutineContext.model_validate(data)

    @staticmethod
    def _reject_split_proposal(context: RoutineContext) -> RoutineContext:
        data = context.model_dump()
        data["split_template"] = None
        data["split_proposal_rejected"] = True
        return RoutineContext.model_validate(data)

    def _split_template_matches_context(
        self,
        template: WorkoutSplitTemplate,
        context: RoutineContext,
    ) -> bool:
        if context.workout_day_ids.status != "provided":
            return False
        template_day_ids = set(template.day_a_ids + template.day_b_ids)
        selected_day_ids = set(context.workout_day_ids.value or [])
        return (
            template_day_ids == selected_day_ids
            and not (template_day_ids - self._workout_day_names.keys())
        )

    def _invalid_split_configuration_reply(
        self,
        context: RoutineContext,
    ) -> ChatReply | None:
        assignment = (
            context.workout_split_assignment.value
            if context.workout_split_assignment.status == "provided"
            else None
        )
        invalid_assignment = assignment is not None and not self._split_template_matches_context(
            assignment, context
        )
        invalid_proposal = (
            context.split_template is not None
            and not self._split_template_matches_context(context.split_template, context)
        )
        if not invalid_assignment and not invalid_proposal:
            return None

        data = context.model_dump()
        if invalid_assignment:
            data["workout_split_assignment"] = {"status": "unknown", "value": None}
        if invalid_proposal or (invalid_assignment and context.split_template is not None):
            data["split_template"] = None
            data["split_proposal_rejected"] = not (
                assignment is not None and not invalid_assignment
            )
        safe_context = RoutineContext.model_validate(data)
        supported = ", ".join(self._workout_day_names.values())
        return ChatReply(
            reply=(
                "A/B 구성에 지원되지 않거나 선택 부위와 맞지 않는 운동일 ID가 있어요. "
                f"현재 지원 부위: {supported}. A/B 그룹을 지원 부위 이름으로 다시 알려주세요."
            ),
            state=ConversationState(context=safe_context),
            exploration_exercises=[],
            quick_replies=self._split_assignment_quick_replies(),
        )

    def _split_names(self, template: WorkoutSplitTemplate) -> tuple[str, str]:
        day_a = ", ".join(self._workout_day_names[item] for item in template.day_a_ids)
        day_b = ", ".join(self._workout_day_names[item] for item in template.day_b_ids)
        return day_a, day_b

    def _split_confirmation_prompt(self, context: RoutineContext) -> str:
        template = context.split_template
        if template is None:
            raise ValueError("a split confirmation requires a proposed template")
        day_a, day_b = self._split_names(template)
        return (
            "주당 운동 횟수와 별도로 2분할 구성을 제안해요. "
            f"A: {day_a}; B: {day_b}. "
            "이 구성을 명시적으로 확인하기 전에는 루틴 초안을 만들지 않아요. "
            "맞으면 ‘이 A/B 분할을 확인합니다’라고 답하고, 바꾸려면 원하는 A/B 부위를 알려주세요."
        )

    @staticmethod
    def _session_frequency_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label=f"주 {frequency}회", message=f"주 {frequency}회")
            for frequency in range(1, 8)
        ]

    def _context_question_quick_replies(
        self,
        context: RoutineContext,
    ) -> list[QuickReply]:
        if context.workout_day_ids.status in {"not_asked", "unknown", "delegated"}:
            return []
        if context.workout_split_type.status in {"unknown", "delegated"}:
            return self._split_type_quick_replies()
        if (
            context.workout_split_type.status == "provided"
            and context.workout_split_assignment.status
            in {"not_asked", "unknown", "skipped"}
        ):
            return self._split_assignment_quick_replies()
        if context.sessions_per_week.status in {"not_asked", "unknown", "delegated"}:
            return self._session_frequency_quick_replies()
        return []

    @staticmethod
    def _split_type_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="2분할", message="2분할을 선택합니다."),
            QuickReply(label="분할 없이", message="분할 없이 진행합니다."),
        ]

    @staticmethod
    def _split_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="이 분할로 진행", message="이 A/B 분할을 확인합니다."),
            QuickReply(label="분할 바꾸기", message="A/B 분할을 바꾸고 싶어요."),
        ]

    @staticmethod
    def _split_assignment_question(context: RoutineContext) -> str:
        requested = context.workout_split_type.status == "provided"
        if not requested:
            return "A/B 분할 요청이 없어졌어요. 원하는 운동 부위를 알려주세요."
        return (
            "앞서 제안한 A/B 구성은 확인되지 않았어요. "
            "A와 B에 넣을 지원 운동 부위를 각각 알려주시거나, 새 제안을 맡기려면 ‘A/B 분할을 다시 제안해줘’라고 해주세요."
        )

    @staticmethod
    def _split_assignment_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="다시 제안받기", message="A/B 분할을 다시 제안해줘."),
            QuickReply(label="직접 정하기", message="A/B 분할을 직접 정하겠습니다."),
        ]

    def _split_missing_area_reply(self, context: RoutineContext) -> ChatReply:
        selected_ids = context.workout_day_ids.value or []
        selected_names = ", ".join(
            self._workout_day_names[day_id] for day_id in selected_ids
        )
        selected_text = f"현재 선택한 부위: {selected_names}. " if selected_names else ""
        quick_replies = [
            QuickReply(
                label=f"{day.name_ko} 추가",
                message=f"{selected_text}{day.name_ko}를 추가해 2분할 A/B를 제안해줘.",
            )
            for day in self._workout_days_by_id.values()
            if day.id not in selected_ids
        ]
        quick_replies.append(
            QuickReply(label="2분할 취소", message="2분할 없이 진행합니다.")
        )
        return ChatReply(
            reply=(
                "A/B 분할을 제안하려면 서로 다른 지원 운동 부위가 두 개 이상 필요해요. "
                f"{selected_text}추가할 부위를 골라 주세요. 선택하지 않은 부위를 임의로 넣지 않습니다."
            ),
            state=ConversationState(context=context),
            exploration_exercises=[],
            quick_replies=quick_replies,
        )
    def _propose_split(self, context: RoutineContext) -> ChatReply:
        day_ids = context.workout_day_ids.value or []
        if len(day_ids) < 2:
            return self._split_missing_area_reply(context)
        midpoint = (len(day_ids) + 1) // 2
        template = WorkoutSplitTemplate(
            day_a_ids=day_ids[:midpoint],
            day_b_ids=day_ids[midpoint:],
            confirmation_status="proposed",
        )
        data = context.model_dump()
        data["split_template"] = template.model_dump()
        proposed_context = RoutineContext.model_validate(data)
        return ChatReply(
            reply=self._split_confirmation_prompt(proposed_context),
            state=ConversationState(phase="confirming_split", context=proposed_context),
            exploration_exercises=[],
            quick_replies=self._split_quick_replies(),
        )

    async def _draft_routine(
        self,
        messages: Sequence[ConversationMessage],
        state: ConversationState,
    ) -> ChatReply:
        context = state.context
        question = self._next_context_question(context)
        if question is not None:
            return ChatReply(
                reply=question,
                state=ConversationState(context=context),
                exploration_exercises=[],
            )

        if context.workout_day_ids.status != "provided":
            return ChatReply(
                reply=(
                    "운동 부위를 건너뛰어서 주간 일정은 만들지 않았어요. "
                    "지원 부위를 알려주시면 언제든 이어서 구성할게요."
                ),
                state=ConversationState(context=context),
                exploration_exercises=[],
            )
        day_ids = context.workout_day_ids.value or []
        split_template = None
        if context.workout_split_type.status == "provided":
            if context.split_template is not None:
                split_template = context.split_template
            elif context.workout_split_assignment.status == "provided":
                split_template = context.workout_split_assignment.value
            if split_template is None or split_template.confirmation_status == "proposed":
                return ChatReply(
                    reply=(
                        "2분할 구성은 아직 확인되지 않아 초안을 만들지 않았어요. "
                        "A/B 구성을 직접 정하거나 제안을 명시적으로 확인해 주세요."
                    ),
                    state=ConversationState(context=context),
                    exploration_exercises=[],
                    quick_replies=self._split_assignment_quick_replies(),
                )
            if set(split_template.day_a_ids + split_template.day_b_ids) != set(day_ids):
                return ChatReply(
                    reply="A/B 구성과 선택한 운동 부위가 맞지 않아요. 선택 부위 전체를 A 또는 B에 한 번씩 넣어 주세요.",
                    state=ConversationState(context=context),
                    exploration_exercises=[],
                )
        if context.sessions_per_week.status != "provided":
            return ChatReply(
                reply=(
                    "주당 횟수를 건너뛰어서 주간 일정은 만들지 않았어요. "
                    "운동 횟수를 알려주시면 언제든 이어서 구성할게요."
                ),
                state=ConversationState(context=context),
                exploration_exercises=[],
            )

        equipment_field = context.equipment
        equipment_intent = equipment_field.value
        if equipment_field.status == "provided" and equipment_intent is not None:
            equipment_ids = list(dict.fromkeys(equipment_intent.equipment_ids))
            if equipment_intent.mode == "unknown":
                return ChatReply(
                    reply="장비를 모르거나 답하고 싶지 않으면 건너뛰어 주세요.",
                    state=ConversationState(context=context),
                    exploration_exercises=[],
                )
            if set(equipment_ids) - self._known_equipment_ids:
                return ChatReply(
                    reply=self._equipment_options_reply(),
                    state=ConversationState(context=context),
                    exploration_exercises=[],
                )
            constraint = EquipmentConstraint(
                mode="specified" if equipment_intent.mode == "specified" else "unrestricted",
                equipment_ids=(
                    equipment_ids if equipment_intent.mode == "specified" else []
                ),
            )
        else:
            constraint = EquipmentConstraint(mode="unrestricted", equipment_ids=[])

        preferences = self._recommendation_preferences(context)
        ranked_candidates_by_day: dict[str, list[Exercise]] = {}
        for day_id in day_ids:
            candidates = await self._reasoner.recommend(
                workout_day_id=day_id,
                equipment_constraint=constraint,
            )
            if not candidates:
                return ChatReply(
                    reply=(
                        f"{self._workout_day_names[day_id]}과 장비 조건에 맞는 "
                        "등록 운동이 없어요. 부위나 장비 조건을 수정해 주세요."
                    ),
                    state=ConversationState(context=context),
                    exploration_exercises=[],
                )
            ranked_candidates_by_day[day_id] = self._rank_candidates(
                candidates, preferences
            )

        (
            candidates_by_day,
            preferred_candidate_ids_by_day,
            preference_reply,
        ) = self._apply_user_preferences(context, ranked_candidates_by_day)
        if preference_reply is not None:
            return ChatReply(
                reply=preference_reply,
                state=ConversationState(context=context),
                exploration_exercises=[],
            )

        eligible_candidates_by_day: dict[str, list[Exercise]] = {}
        for day_id, candidates in candidates_by_day.items():
            evidence_reply = self._evidence_coverage_reply(candidates, preferences)
            if evidence_reply is not None:
                return ChatReply(
                    reply=evidence_reply,
                    state=ConversationState(context=context),
                    exploration_exercises=[],
                )
            eligible_candidates_by_day[day_id] = candidates
            candidates_by_day[day_id] = candidates[
                :_MAX_RECOMMENDED_CANDIDATES_PER_DAY
            ]

        candidate_ids = {
            exercise.source_id
            for candidates in candidates_by_day.values()
            for exercise in candidates
        }
        profiles = [
            profile
            for profile in self._catalog.recommendations.profiles
            if profile.source_id in candidate_ids
        ]
        proposal = await self._model.plan_routine(
            messages,
            context,
            candidates_by_day,
            self._catalog.workout_days,
            profiles,
            state.routine,
        )
        planned_sessions = self._validated_sessions(
            proposal,
            candidates_by_day,
            day_ids,
            context.sessions_per_week.value,
            context,
            preferred_candidate_ids_by_day,
        )
        prescription, prescription_note = self._build_hypertrophy_prescription(
            context,
            planned_sessions,
        )
        routine = RoutineDraft(
            sessions_per_week=context.sessions_per_week.value,
            minutes_per_session=(
                context.minutes_per_session.value
                if context.minutes_per_session.status == "provided"
                else None
            ),
            sessions=planned_sessions,
            hypertrophy_prescription=prescription,
            prescription_note=prescription_note,
        )
        default_recommendation_ids = {
            exercise.source_id
            for session in planned_sessions
            for item in session.exercises
            for exercise in (item.exercise, *item.alternatives)
        }
        all_candidates = {
            exercise.source_id: exercise
            for candidates in eligible_candidates_by_day.values()
            for exercise in candidates
        }
        available_minutes = (
            f" 회당 {routine.minutes_per_session}분을 목표 시간으로 반영했지만, "
            "운동별 소요 시간 자료가 없어 완료 시간은 보장하지 않아요."
            if routine.minutes_per_session is not None
            else ""
        )
        equipment_note = (
            " 장비를 제한하지 않고 후보를 살펴봤어요. 보유 장비를 가정하지 않습니다."
            if constraint.mode == "unrestricted"
            else ""
        )
        if prescription is not None:
            prescription_reply = (
                " 근비대 처방에는 적용 범위와 출처를 표시했고, 개인별 절대 중량은 제시하지 않았어요."
            )
        elif context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}:
            prescription_reply = f" 근비대 처방은 생략했어요. {prescription_note}"
        else:
            prescription_reply = " 근비대 목적의 근거가 연결되지 않아 세트·반복·휴식 처방은 포함하지 않았어요."
        return ChatReply(
            reply=(
                "조건에 맞는 운동 후보를 찾았어요. 주간 루틴 초안을 만들었어요."
                f"{equipment_note}{prescription_reply}"
                f"{available_minutes}"
            ),
            state=ConversationState(
                phase="reviewing_routine",
                context=context,
                routine=routine,
            ),
            exploration_exercises=[
                self._present_exercise(item)
                for source_id, item in all_candidates.items()
                if source_id not in default_recommendation_ids
            ],
        )

    def _validated_sessions(
        self,
        proposal: RoutineProposal,
        candidates_by_day: dict[str, Sequence[Exercise]],
        selected_day_ids: Sequence[str],
        expected_sessions: int,
        context: RoutineContext,
        preferred_candidate_ids_by_day: dict[str, set[str]],
    ) -> list[RoutineSession]:
        if len(proposal.sessions) != expected_sessions:
            raise ChatCompletionError("Routine session count did not match the request.")

        day_names = self._workout_day_names
        sessions: list[RoutineSession] = []
        split_template = (
            context.split_template
            if context.split_template is not None
            and context.split_template.confirmation_status == "confirmed"
            else context.workout_split_assignment.value
            if context.workout_split_assignment.status == "provided"
            else None
        )
        for index, planned_session in enumerate(proposal.sessions, start=1):
            if planned_session.workout_day_id not in selected_day_ids:
                raise ChatCompletionError("Routine used an unrequested workout day.")
            if split_template is not None:
                expected_group = split_template.day_a_ids if (index - 1) % 2 == 0 else split_template.day_b_ids
                if planned_session.workout_day_id not in expected_group:
                    raise ChatCompletionError("Routine did not follow the confirmed A/B split.")
            day_candidates = {
                exercise.source_id: exercise
                for exercise in candidates_by_day[planned_session.workout_day_id]
            }

            selected_ids: set[str] = set()
            planned_items: list[RoutineExercise] = []
            for item in planned_session.exercises:
                if item.source_id in selected_ids:
                    raise ChatCompletionError("Routine repeats an exercise within a session.")
                selected_ids.add(item.source_id)
                exercise = day_candidates.get(item.source_id)
                if exercise is None:
                    raise ChatCompletionError("Routine used an unverified exercise.")
                if len(item.alternative_source_ids) != len(set(item.alternative_source_ids)):
                    raise ChatCompletionError("Routine contains duplicate alternatives.")
                alternatives = []
                for alternative_id in item.alternative_source_ids:
                    alternative = day_candidates.get(alternative_id)
                    if alternative is None or alternative_id == item.source_id:
                        raise ChatCompletionError("Routine used an unverified alternative.")
                    alternatives.append(self._present_exercise(alternative))
                planned_items.append(
                    RoutineExercise(
                        exercise=self._present_exercise(exercise),
                        rationale=self._recommendation_rationale(
                            exercise,
                            planned_session.workout_day_id,
                            context,
                            preferred_candidate_ids_by_day[
                                planned_session.workout_day_id
                            ],
                        ),
                        alternatives=alternatives,
                    )
                )
            sessions.append(
                RoutineSession(
                    index=index,
                    workout_day_id=planned_session.workout_day_id,
                    workout_day_name_ko=day_names[planned_session.workout_day_id],
                    exercises=planned_items,
                )
            )
        return sessions

    def _next_context_question(self, context: RoutineContext) -> str | None:
        if context.workout_day_ids.status in {"not_asked", "unknown", "delegated"}:
            supported = ", ".join(self._workout_day_names.values())
            if context.workout_day_ids.status == "unknown":
                return f"운동 부위를 아직 모르시는 걸로 기록했어요. 지원 부위({supported}) 중 하나 이상을 직접 골라 주세요. 선택을 맡기거나 건너뛰어도 됩니다."
            if context.workout_day_ids.status == "delegated":
                return f"부위 선택은 맡기셨지만 임의로 고르지 않겠습니다. 지원 부위({supported}) 중 원하는 부위를 알려주시거나 건너뛰어 주세요."
            return (
                "주간 일정에 넣을 운동 부위를 알려주세요. 현재 지원 범위: "
                f"{supported}. 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.workout_split_type.status in {"unknown", "delegated"}:
            return (
                "주당 빈도와 분할 방식은 별개예요. 2분할 여부를 모르시거나 선택을 맡기신 것으로 기록했어요. "
                "2분할 A/B 구성을 정할지, 분할 없이 선택 부위별 일정을 만들지 알려주세요."
            )
        if context.workout_split_type.status == "provided":
            assignment_status = context.workout_split_assignment.status
            if context.split_proposal_rejected:
                return self._split_assignment_question(context)
            if assignment_status in {"not_asked", "unknown"}:
                return (
                    "주당 빈도는 별도로 보존했어요. 2분할 A/B에 넣을 운동 부위를 각각 알려주세요. "
                    "예: A는 가슴·어깨, B는 하체. 구성을 맡기려면 ‘A/B 분할을 알아서 제안해줘’라고 해주세요."
                )
            if assignment_status == "skipped":
                return (
                    "A/B 구성을 건너뛰어 2분할 초안은 만들지 않아요. A/B 부위를 직접 정하거나, "
                    "제안을 맡기거나, 2분할 요청을 취소해 주세요."
                )
        if context.sessions_per_week.status in {"not_asked", "unknown", "delegated"}:
            if context.sessions_per_week.status == "unknown":
                return "주당 운동 횟수를 모르시는 걸로 기록했어요. 주 1~7회 중 정확한 횟수를 고르거나, 주간 일정 항목을 건너뛰어 주세요."
            if context.sessions_per_week.status == "delegated":
                return "주당 횟수 선택을 맡기셨지만 빈도를 임의로 정하지 않겠습니다. 주 1~7회 중 하나를 알려주시거나 주간 일정 항목을 건너뛰어 주세요."
            return (
                "주간 일정을 만들려면 주당 운동 횟수가 필요해요. "
                "주 1~7회 중 알려주세요. 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.goal.status in {"not_asked", "unknown"}:
            if context.goal.status == "unknown":
                return "우선 목표를 아직 정하지 않으신 걸로 기록했어요. 근비대, 근력 중 하나를 고르거나 두 목표를 함께 추구할 수 있어요. 목표 분류를 건너뛰어도 됩니다."
            return (
                "우선할 목표를 근비대, 근력 중에서 고르거나 두 목표를 함께 추구할 수 있어요. 모르거나 답하고 싶지 않으면 "
                "목표 분류를 건너뛸 수 있어요."
            )
        if context.goal.status == "provided" and context.goal.value == "other":
            return (
                "현재 출처가 연결된 목표는 근비대와 근력 진행이에요. "
                "하나를 고르거나 두 목표를 함께 선택하거나 목표 분류를 건너뛰어 주세요."
            )
        if context.adult_eligibility.status in {"not_asked", "unknown", "delegated"} and (
            context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}
        ):
            if context.adult_eligibility.status in {"unknown", "delegated"}:
                return "성인 여부는 추정하지 않아요. 근비대 처방의 적용 범위를 확인하려면 만 18세 이상인지 직접 알려주시거나 해당 확인을 건너뛰어 주세요."
            return (
                "근비대 처방 근거는 건강한 성인 대상이에요. 만 18세 이상인가요? "
                "답하고 싶지 않으면 성인 여부를 건너뛸 수 있어요."
            )
        if context.experience.status in {"not_asked", "unknown"}:
            if context.experience.status == "unknown":
                return "운동 경력을 모르시는 걸로 기록했어요. 처음 시작·여러 해 쉬었다가 복귀·경험자 중 자기보고로 알려주시거나 경력 분류를 건너뛰어 주세요."
            return (
                "저항 운동을 처음 시작했거나 몇 년 쉬었다가 복귀했나요? "
                "경력은 자기보고로만 반영하며, 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.experience.status == "provided" and context.experience.value == "experienced" and not (
            context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}
        ):
            return (
                "경험자 적합도 근거는 아직 없어요. 경력 기준을 건너뛰고 "
                "목표·다른 조건만 반영할까요?"
            )
        if context.minutes_per_session.status in {"not_asked", "unknown"}:
            if context.minutes_per_session_range.status == "provided":
                time_range = context.minutes_per_session_range.value
                return (
                    f"회당 {time_range.minimum_minutes}~{time_range.maximum_minutes}분 범위로 기록했어요. "
                    "초안에 사용할 목표 시간 하나를 직접 골라 주세요. 중간값을 대신 선택하지 않습니다."
                )
            if context.minutes_per_session.status == "unknown":
                return "회당 시간을 모르시는 걸로 기록했어요. 사용 가능한 분 수 하나를 알려주시거나 시간 조건을 건너뛰어 주세요."
            return (
                "한 번 운동할 때 가능한 시간을 알려주세요. 모르거나 답하고 싶지 않으면 "
                "시간 조건을 건너뛸 수 있어요."
            )
        if context.equipment.status in {"not_asked", "unknown"} or (
            context.equipment.value is not None
            and context.equipment.value.mode == "unknown"
        ):
            if context.equipment.status == "unknown" or (
                context.equipment.value is not None
                and context.equipment.value.mode == "unknown"
            ):
                return (
                    "장비를 모르신다고 기록했어요. 장소 이름으로 장비를 추측하지 않겠습니다. "
                    "사용 가능한 장비를 직접 적거나 ‘알아서 선택’으로 맡기거나, 장비 조건을 건너뛰어 주세요."
                )
            return (
                "사용할 수 있는 장비를 알려주세요. 모르거나 답하고 싶지 않으면 건너뛰어도 돼요. "
                "건너뛰면 보유 장비를 가정하지 않고 장비 제한 없이 후보를 살펴봅니다."
            )
        if context.preferences.status in {"not_asked", "unknown"}:
            if context.preferences.status == "unknown":
                return "선호를 모르시는 걸로 기록했어요. 선호 운동이나 피하고 싶은 동작을 알려주시거나 선호 항목을 건너뛸 수 있어요."
            return "선호하거나 피하고 싶은 동작이 있나요? 없거나 답하고 싶지 않으면 건너뛰어도 돼요."
        if context.known_constraints.status in {"not_asked", "unknown", "delegated"}:
            if context.known_constraints.status == "unknown":
                return "알고 있는 제약을 모르시는 걸로 기록했어요. 진단을 추정하지 않으며, 알고 있는 제한을 말하거나 제약 확인을 건너뛸 수 있어요."
            if context.known_constraints.status == "delegated":
                return "제약 확인을 맡기셨지만 제약이 없다고 추정하지 않겠습니다. 알고 있는 제한을 직접 알려주시거나 확인을 건너뛰어 주세요."
            return (
                "운동에서 고려할 제약이나 불편함을 알고 있나요? 진단명은 추정하지 않으며, "
                "모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if (
            context.goal.status == "provided"
            and context.goal.value in {"hypertrophy", "both"}
            and context.adult_eligibility.status == "provided"
            and context.adult_eligibility.value == "adult"
            and context.known_constraints.status == "provided"
            and not context.known_constraints.value
            and context.experience.status == "provided"
            and context.experience.value == "experienced"
            and context.weekly_direct_sets_by_muscle.status not in {"unknown", "skipped", "delegated"}
            and context.weekly_direct_sets_follow_up.status not in {"unknown", "skipped", "delegated"}
        ):
            focus_muscle_ids = {
                muscle_id
                for day_id in (context.workout_day_ids.value or [])
                for muscle_id in self._focus_muscle_ids_by_day.get(day_id, set())
            }
            reported = context.weekly_direct_sets_by_muscle.value or {}
            missing_muscle_ids = [
                muscle.id
                for muscle in self._catalog.muscles
                if muscle.id in focus_muscle_ids and muscle.id not in reported
            ]
            if missing_muscle_ids:
                stage_ids = missing_muscle_ids[:3]
                missing_names = ", ".join(self._muscle_names[muscle_id] for muscle_id in stage_ids)
                return (
                    "최근 한 주의 근육별 직접 세트 수는 경험자 처방을 현재 보고에 맞추기 위해 필요해요. "
                    "한 번에 세 근육씩 받을게요. "
                    f"이번 단계: {missing_names}. 형식: 근육명마다 지난 한 주의 직접 세트 수를 적어주세요. "
                    "값을 추정하지 않으며, 모르는 값은 비워 두거나 보고를 건너뛸 수 있어요."
                )
        return None

    def _context_summary(self, context: RoutineContext) -> str:
        goal_names = {"hypertrophy": "근비대", "strength": "근력", "both": "근비대와 근력 진행", "other": "기타 목표"}
        experience_names = {"novice": "초보·복귀(자기보고)", "experienced": "경험자(자기보고)"}
        if context.workout_day_ids.status == "provided":
            workout_days = ", ".join(
                self._workout_day_names[item]
                for item in context.workout_day_ids.value or []
            )
        else:
            workout_days = self._field_status_label(context.workout_day_ids.status)
        if context.equipment.status == "provided" and context.equipment.value is not None:
            equipment = context.equipment.value
            if equipment.mode == "specified":
                equipment_text = ", ".join(
                    self._equipment_names[item] for item in equipment.equipment_ids
                )
            elif equipment.mode == "unknown":
                equipment_text = "모름"
            else:
                equipment_text = "선택 위임(보유 장비는 가정하지 않음)"
        else:
            equipment_text = self._field_status_label(context.equipment.status)

        if context.minutes_per_session.status == "provided":
            time_text = f"{context.minutes_per_session.value}분"
            if context.minutes_per_session_range.status == "provided":
                time_range = context.minutes_per_session_range.value
                time_text += f" (보고 범위 {time_range.minimum_minutes}~{time_range.maximum_minutes}분)"
        elif context.minutes_per_session_range.status == "provided":
            time_range = context.minutes_per_session_range.value
            time_text = f"{time_range.minimum_minutes}~{time_range.maximum_minutes}분 범위"
            if context.minutes_per_session.status in {"skipped", "delegated"}:
                time_text += f", 목표 {self._field_status_label(context.minutes_per_session.status)}"
            else:
                time_text += ", 목표 미선택"
        else:
            time_text = self._field_status_label(context.minutes_per_session.status)

        split_text = self._context_value_label(
            context.workout_split_type,
            {"ab": "2분할(A/B)"},
        )
        if context.workout_split_assignment.status == "provided":
            day_a, day_b = self._split_names(context.workout_split_assignment.value)
            split_text += f"; A: {day_a}, B: {day_b} (사용자 지정)"
        elif context.split_template is not None:
            day_a, day_b = self._split_names(context.split_template)
            confirmation = "확인됨" if context.split_template.confirmation_status == "confirmed" else "제안됨"
            split_text += f"; A: {day_a}, B: {day_b} ({confirmation})"
        elif context.workout_split_type.status == "provided":
            split_text += f"; A/B 구성: {self._field_status_label(context.workout_split_assignment.status)}"

        context_lines = [
            "제가 이해한 내용이에요. 확인하거나 채팅으로 수정해 주세요.",
            f"- 운동 부위: {workout_days}",
            f"- 주당 빈도: {self._value_with_unit(context.sessions_per_week, '회')}",
            f"- 운동 분할: {split_text}",
            f"- 목표: {self._context_value_label(context.goal, goal_names)}",
            f"- 운동 경력: {self._context_value_label(context.experience, experience_names)}",
            f"- 회당 가능 시간: {time_text}",
            f"- 장비: {equipment_text}",
            f"- 선호: {self._list_value_or_status(context.preferences)}",
            f"- 알고 있는 제약: {self._list_value_or_status(context.known_constraints)}",
        ]
        if context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}:
            context_lines.append(
                f"- 성인 여부: {self._context_value_label(context.adult_eligibility, {'adult': '성인', 'minor': '미성년'})}"
            )
            if context.experience.status == "provided" and context.experience.value == "experienced":
                sets_text = self._weekly_sets_label(context.weekly_direct_sets_by_muscle)
                follow_up = context.weekly_direct_sets_follow_up
                if follow_up.status in {"unknown", "skipped", "delegated"}:
                    sets_text += f"; 추가 보고 {self._field_status_label(follow_up.status)}"
                context_lines.append(f"- 최근 근육별 주간 직접 세트: {sets_text}")
        context_lines.append("이 요약이 맞으면 ‘확인하고 루틴 만들기’를 눌러주세요.")
        return "\n".join(context_lines)

    @staticmethod
    def _field_status_label(status: str) -> str:
        return {"unknown": "모름", "skipped": "건너뜀", "delegated": "선택 위임"}.get(status, "미입력")

    @classmethod
    def _value_with_unit(cls, field: ContextField[int], unit: str) -> str:
        if field.status == "provided":
            return f"{field.value}{unit}"
        return cls._field_status_label(field.status)

    @classmethod
    def _context_value_label(
        cls,
        field: ContextField[str],
        labels: dict[str, str],
    ) -> str:
        if field.status == "provided" and field.value is not None:
            return labels[field.value]
        return cls._field_status_label(field.status)

    @classmethod
    def _list_value_or_status(cls, field: ContextField[list[str]]) -> str:
        if field.status != "provided":
            return cls._field_status_label(field.status)
        return ", ".join(field.value or []) or "없음"
    def _weekly_sets_label(self, field: ContextField[dict[str, int]]) -> str:
        if field.status != "provided":
            return self._field_status_label(field.status)
        return ", ".join(
            f"{self._muscle_names.get(muscle_id, muscle_id)} {sets}세트"
            for muscle_id, sets in sorted((field.value or {}).items())
        ) or "없음"



    @staticmethod
    def _recommendation_preferences(context: RoutineContext) -> RecommendationPreferences:
        if context.goal.status == "skipped":
            goal = "skip"
        elif context.goal.status == "provided":
            goal = "unsupported" if context.goal.value == "other" else context.goal.value
        else:
            goal = "unknown"
        if context.experience.status == "skipped":
            experience = "skip"
        elif context.experience.status == "provided":
            experience = context.experience.value
        else:
            experience = "unknown"
        return RecommendationPreferences(goal=goal, experience=experience)

    def _build_hypertrophy_prescription(
        self,
        context: RoutineContext,
        sessions: Sequence[RoutineSession],
    ) -> tuple[HypertrophyPrescription | None, str | None]:
        if context.goal.status != "provided" or context.goal.value not in {"hypertrophy", "both"}:
            return None, None
        if context.adult_eligibility.status != "provided" or context.adult_eligibility.value != "adult":
            return None, "성인 여부가 확인되지 않거나 근거 적용 범위 밖이에요."
        if context.known_constraints.status != "provided" or context.known_constraints.value:
            return None, "건강상 제약이 없다고 확인되지 않아 일반 처방을 적용하지 않았어요."
        if context.experience.status != "provided":
            return None, "운동 경력을 확인하지 않아 사용자 맞춤 처방을 적용하지 않았어요."
        if (
            context.experience.value == "experienced"
            and context.weekly_direct_sets_by_muscle.status != "provided"
        ):
            return None, "최근 주간 직접 세트 수를 확인하지 않아 경험자 맞춤 처방을 적용하지 않았어요."

        focus_muscle_ids = {
            muscle_id
            for session in sessions
            for muscle_id in self._focus_muscle_ids_by_day[session.workout_day_id]
        }
        muscle_ids = sorted(
            {
                self._exercises_by_id[item.exercise.source_id].primary_muscle_id
                for session in sessions
                for item in session.exercises
                if self._exercises_by_id[item.exercise.source_id].primary_muscle_id
                in focus_muscle_ids
            }
        )
        if not muscle_ids:
            return None, "선택된 운동에 부위의 주 표적 근육이 없어 직접 세트 처방을 적용하지 않았어요."
        reported_sets = context.weekly_direct_sets_by_muscle.value or {}
        weekly_targets: list[WeeklyDirectSetTarget] = []
        for muscle_id in muscle_ids:
            if context.experience.value == "novice":
                set_count = self._hypertrophy_guidelines.initial_direct_sets_per_muscle_per_week
                basis = "source_starting_point"
            elif muscle_id in reported_sets:
                set_count = reported_sets[muscle_id]
                basis = "user_reported"
            else:
                return None, "선택된 표적 근육의 최근 주간 세트 수가 없어 처방을 적용하지 않았어요."
            weekly_targets.append(
                WeeklyDirectSetTarget(
                    muscle_id=muscle_id,
                    muscle_name_ko=self._muscle_names[muscle_id],
                    sets_per_week=set_count,
                    basis=basis,
                )
            )

        guidelines = self._hypertrophy_guidelines
        source_variables = {"higher_volume", "repetitions", "rest", "progression"}
        if any(target.basis == "source_starting_point" for target in weekly_targets):
            source_variables.add("initial_sets")
        source_ids = {
            source_id
            for variable in source_variables
            for source_id in guidelines.sources_by_variable[variable]
        }
        sources = [source for source in guidelines.sources if source.id in source_ids]
        progression = HypertrophyProgressionRule(
            extra_repetitions_min=guidelines.progression_extra_repetitions_range[0],
            extra_repetitions_max=guidelines.progression_extra_repetitions_range[1],
            load_increase_percent_min=guidelines.progression_load_increase_percent_range[0],
            load_increase_percent_max=guidelines.progression_load_increase_percent_range[1],
            instruction=(
                f"목표 반복보다 {guidelines.progression_extra_repetitions_range[0]}–"
                f"{guidelines.progression_extra_repetitions_range[1]}회 더 수행할 수 있을 때, "
                f"이미 선택한 부하를 {guidelines.progression_load_increase_percent_range[0]}–"
                f"{guidelines.progression_load_increase_percent_range[1]}% 높이는 진행 규칙이에요. "
                "개인별 절대 중량은 계산하거나 추천하지 않습니다."
            ),
        )
        return (
            HypertrophyPrescription(
                population_scope="건강상 제약이 없는 만 18세 이상 성인을 위한 일반 근비대 지침",
                weekly_direct_sets=weekly_targets,
                higher_volume_reference_sets_per_muscle_per_week=(
                    guidelines.higher_volume_direct_sets_per_muscle_per_week
                ),
                repetition_range_rm=guidelines.repetition_range_rm,
                rest_seconds_range=guidelines.rest_seconds_range,
                progression=progression,
                sources=sources,
                caveats=guidelines.caveats,
            ),
            None,
        )

    def _supported_workout_days_reply(self) -> str:
        options = ", ".join(self._workout_day_names.values())
        return f"요청한 부위는 아직 지원하지 않아요. 현재 지원 범위: {options}."

    def _equipment_options_reply(self) -> str:
        options = ", ".join(self._equipment_names.values())
        return f"장비 조건을 확인하지 못했어요. 현재 지원하는 장비: {options}."

    def _evidence_coverage_reply(
        self,
        candidates: Sequence[Exercise],
        preferences: RecommendationPreferences,
    ) -> str | None:
        if not candidates:
            return None
        profiles = [
            self._recommendation_profiles.get(exercise.source_id)
            for exercise in candidates
        ]
        if preferences.goal == "hypertrophy":
            goal_supported = any(
                profile is not None
                and profile.exercise_api is not None
                and profile.exercise_api.modality == "hypertrophy"
                for profile in profiles
            )
        elif preferences.goal == "both":
            goal_supported = any(
                profile is not None
                and profile.exercise_api is not None
                and profile.exercise_api.modality == "hypertrophy"
                and profile.exercise_api.loadable
                and profile.exercise_api.e1rm_substitution_group is not None
                for profile in profiles
            )
        elif preferences.goal == "strength":
            goal_supported = any(
                profile is not None
                and profile.exercise_api is not None
                and profile.exercise_api.loadable
                and profile.exercise_api.e1rm_substitution_group is not None
                for profile in profiles
            )
        else:
            goal_supported = True

        experience_supported = preferences.experience != "novice" or any(
            profile is not None and profile.novice_consensus_exercise_name is not None
            for profile in profiles
        )
        if goal_supported and experience_supported:
            return None
        if not goal_supported and not experience_supported:
            return (
                "현재 부위의 후보에는 목표·초보 경력과 연결된 외부 근거가 없습니다. "
                "목표와 경력 분류를 건너뛰고 미평가 후보를 볼까요?"
            )
        if not goal_supported:
            return (
                "현재 후보에는 출처가 연결된 근비대·근력 진행 메타데이터가 없습니다. "
                "목표 기준 정렬을 건너뛰고 미평가 후보를 볼까요?"
            )
        return (
            "현재 후보에는 연구에서 초보·복귀 운동자에게 적절하다고 확인된 운동이 없습니다. "
            "경력 기준 정렬을 건너뛰고 미평가 후보를 볼까요?"
        )

    @staticmethod
    def _normalize_catalog_text(value: str) -> str:
        return " ".join(
            "".join(char.casefold() if char.isalnum() else " " for char in value).split()
        )

    @classmethod
    def _contains_catalog_term(cls, phrase: str, term: str) -> bool:
        normalized_phrase = cls._normalize_catalog_text(phrase)
        normalized_term = cls._normalize_catalog_text(term)
        return bool(normalized_term) and f" {normalized_term} " in f" {normalized_phrase} "

    def _candidate_matches_preference(
        self,
        phrase: str,
        exercise: Exercise,
    ) -> bool:
        terms = [exercise.name, exercise.name_ko or ""]
        if exercise.movement_pattern_id is not None:
            terms.extend(
                [
                    exercise.movement_pattern_id,
                    self._pattern_names[exercise.movement_pattern_id],
                ]
            )
        return any(self._contains_catalog_term(phrase, term) for term in terms)

    def _matching_catalog_candidate_ids(self, phrase: str) -> set[str]:
        return {
            exercise.source_id
            for exercise in self._catalog.exercises
            if self._candidate_matches_preference(phrase, exercise)
        }

    @classmethod
    def _preference_direction(cls, phrase: str) -> Literal["prefer", "avoid"] | None:
        normalized = cls._normalize_catalog_text(phrase)
        negative_markers = (
            "피하고",
            "싫",
            "선호하지",
            "avoid",
            "dislike",
            "hate",
            "do not like",
            "don t like",
            "not like",
            "not prefer",
        )
        positive_markers = ("좋아", "선호", "prefer", "like", "love", "favorite")

        def contains_marker(value: str, marker: str) -> bool:
            normalized_marker = cls._normalize_catalog_text(marker)
            if marker.isascii():
                return f" {normalized_marker} " in f" {value} "
            return normalized_marker in value

        matched_negative = [
            marker for marker in negative_markers if contains_marker(normalized, marker)
        ]
        positive_text = normalized
        for marker in matched_negative:
            normalized_marker = cls._normalize_catalog_text(marker)
            positive_text = positive_text.replace(normalized_marker, " ")
        is_positive = any(
            contains_marker(positive_text, marker) for marker in positive_markers
        )
        is_negative = bool(matched_negative)
        if is_negative == is_positive:
            return None
        return "avoid" if is_negative else "prefer"

    def _apply_user_preferences(
        self,
        context: RoutineContext,
        ranked_candidates_by_day: dict[str, list[Exercise]],
    ) -> tuple[dict[str, list[Exercise]], dict[str, set[str]], str | None]:
        all_candidates_by_id = {
            exercise.source_id: exercise
            for candidates in ranked_candidates_by_day.values()
            for exercise in candidates
        }
        eligible_ids = set(all_candidates_by_id)
        preferred_ids: set[str] = set()
        avoided_ids: set[str] = set()
        no_preference_values = {
            "none",
            "no preference",
            "no preferences",
            "없음",
            "선호 없음",
            "선호하는 것 없어",
        }

        if context.preferences.status == "provided":
            for phrase in context.preferences.value or []:
                normalized = self._normalize_catalog_text(phrase)
                if not normalized or normalized in no_preference_values:
                    continue
                direction = self._preference_direction(phrase)
                if direction is None:
                    return {}, {}, (
                        "말씀하신 선호를 우선할지 피할지 분명하지 않아요. "
                        "운동명이나 동작 분류와 함께 의도를 알려주시거나 선호를 건너뛰어 주세요."
                    )
                matched_ids = self._matching_catalog_candidate_ids(phrase)
                if not matched_ids:
                    return {}, {}, (
                        "선호 표현을 카탈로그의 운동명이나 동작 분류와 연결하지 못했어요. "
                        "해당 항목을 구체적으로 알려주시거나 선호를 건너뛰어 주세요."
                    )
                matching_eligible_ids = matched_ids & eligible_ids
                if direction == "prefer":
                    if not matching_eligible_ids:
                        return {}, {}, (
                            "선호한 운동은 현재 부위·장비 조건의 후보에 없어요. "
                            "조건을 바꾸거나 다른 카탈로그 운동명을 알려주세요."
                        )
                    preferred_ids.update(matching_eligible_ids)
                else:
                    avoided_ids.update(matching_eligible_ids)

        if preferred_ids & avoided_ids:
            return {}, {}, "같은 운동을 선호와 제외 조건에 모두 적어주셨어요. 어느 쪽인지 확인해 주세요."

        ordered_by_day: dict[str, list[Exercise]] = {}
        preferred_ids_by_day: dict[str, set[str]] = {}
        for day_id, ranked_candidates in ranked_candidates_by_day.items():
            remaining = [
                exercise
                for exercise in ranked_candidates
                if exercise.source_id not in avoided_ids
            ]
            if not remaining:
                return {}, {}, (
                    f"{self._workout_day_names[day_id]}은 피하고 싶은 운동을 제외하면 후보가 없어요. "
                    "선호 조건이나 부위를 수정해 주세요."
                )
            preferred = [
                exercise for exercise in remaining if exercise.source_id in preferred_ids
            ]
            if len(preferred) > _MAX_RECOMMENDED_CANDIDATES_PER_DAY:
                return {}, {}, (
                    f"{self._workout_day_names[day_id]}에서 선호한 후보가 5개를 넘어요. "
                    "우선할 운동명이나 동작을 조금 더 구체적으로 알려주세요."
                )
            preferred_ids_by_day[day_id] = {
                exercise.source_id for exercise in preferred
            }
            ordered_by_day[day_id] = [
                *preferred,
                *(
                    exercise
                    for exercise in remaining
                    if exercise.source_id not in preferred_ids_by_day[day_id]
                ),
            ]

        return ordered_by_day, preferred_ids_by_day, None

    def _has_unresolved_constraints(self, field: ContextField[list[str]]) -> bool:
        if field.status != "provided":
            return False
        no_constraint_values = {
            "none",
            "no constraints",
            "no restrictions",
            "no limitation",
            "no limitations",
            "no known constraints",
            "no physical restrictions",
            "no injuries",
            "제약 사항 없음",
            "제약은 없어요",
            "제약 없음",
            "현재 제약 없음",
            "제한 없음",
            "운동 제한 없음",
            "불편함 없음",
            "없음",
        }
        return any(
            normalized and normalized not in no_constraint_values
            for value in field.value or []
            if (normalized := self._normalize_catalog_text(value))
        )

    def _recommendation_rationale(
        self,
        exercise: Exercise,
        workout_day_id: str,
        context: RoutineContext,
        preferred_candidate_ids: set[str],
    ) -> str:
        if exercise.source_id in preferred_candidate_ids:
            return "사용자가 명시한 운동명·동작 선호가 카탈로그 정보와 일치합니다."

        profile = self._recommendation_profiles.get(exercise.source_id)
        evidence = profile.exercise_api if profile is not None else None
        if (
            context.goal.status == "provided"
            and context.goal.value == "both"
            and evidence is not None
            and evidence.modality == "hypertrophy"
            and evidence.loadable
            and evidence.e1rm_substitution_group is not None
        ):
            return "카탈로그 출처 프로필에 근비대와 근력 진행 양쪽의 목표 관련 메타데이터가 있습니다."
        if (
            context.goal.status == "provided"
            and context.goal.value in {"hypertrophy", "both"}
            and evidence is not None
            and evidence.modality == "hypertrophy"
        ):
            return "카탈로그 출처 프로필에 근비대 목표 관련 메타데이터가 있습니다."
        if (
            context.goal.status == "provided"
            and context.goal.value in {"strength", "both"}
            and evidence is not None
            and evidence.loadable
            and evidence.e1rm_substitution_group is not None
        ):
            return "카탈로그 출처 프로필에 근력 진행 호환 메타데이터가 있습니다."
        if profile is not None and profile.novice_consensus_exercise_name is not None:
            return "이 운동에는 초보·복귀 운동 선택에 관한 전문가 합의 출처가 연결되어 있습니다."

        workout_day = self._workout_days_by_id[workout_day_id]
        if exercise.primary_muscle_id in workout_day.focus_muscle_ids:
            return "카탈로그의 주 표적 근육이 선택한 운동 부위와 일치합니다."
        return "카탈로그에서 허용된 보조 근육 운동으로 선택한 부위와 연결됩니다."

    def _rank_candidates(
        self,
        candidates: Sequence[Exercise],
        preferences: RecommendationPreferences,
    ) -> list[Exercise]:
        if preferences.goal == "skip" and preferences.experience == "skip":
            return list(candidates)

        original_order = {
            exercise.source_id: index for index, exercise in enumerate(candidates)
        }
        group_order: dict[str, int] = {}
        for exercise in candidates:
            profile = self._recommendation_profiles.get(exercise.source_id)
            evidence = profile.exercise_api if profile is not None else None
            if evidence is None or evidence.e1rm_substitution_group is None:
                continue
            supports_hypertrophy = evidence.modality == "hypertrophy"
            supports_strength = evidence.loadable
            if preferences.goal == "hypertrophy" and not supports_hypertrophy:
                continue
            if preferences.goal == "strength" and not supports_strength:
                continue
            if preferences.goal == "both" and not (supports_hypertrophy and supports_strength):
                continue
            group_order.setdefault(
                evidence.e1rm_substitution_group,
                original_order[exercise.source_id],
            )

        def rank_key(exercise: Exercise) -> tuple[int, ...]:
            profile = self._recommendation_profiles.get(exercise.source_id)
            evidence = profile.exercise_api if profile is not None else None
            if preferences.goal == "hypertrophy":
                goal_rank = (
                    0
                    if evidence is not None and evidence.modality == "hypertrophy"
                    else 1
                )
            elif preferences.goal == "strength":
                goal_rank = (
                    0
                    if evidence is not None
                    and evidence.loadable
                    and evidence.e1rm_substitution_group is not None
                    else 1
                )
            elif preferences.goal == "both":
                goal_rank = (
                    0
                    if evidence is not None
                    and evidence.modality == "hypertrophy"
                    and evidence.loadable
                    and evidence.e1rm_substitution_group is not None
                    else 1
                )
            else:
                goal_rank = 0

            novice_rank = (
                0
                if preferences.experience == "novice"
                and profile is not None
                and profile.novice_consensus_exercise_name is not None
                else 1
                if preferences.experience == "novice"
                else 0
            )
            combined_rank = goal_rank + novice_rank
            index = original_order[exercise.source_id]
            if (
                preferences.goal == "hypertrophy"
                and evidence is not None
                and evidence.modality == "hypertrophy"
            ):
                sfr_rank = {"high": 0, "moderate": 1, "low": 2}.get(
                    evidence.sfr_class, 3
                )
                group_rank = (
                    group_order.get(evidence.e1rm_substitution_group, index)
                    if evidence.e1rm_substitution_group is not None
                    else index
                )
                within_group_rank = evidence.preferred_rank or 1_000_000
                gold_standard_rank = 0 if evidence.is_gold_standard else 1
            elif preferences.goal == "both" and goal_rank == 0:
                sfr_rank = {"high": 0, "moderate": 1, "low": 2}.get(
                    evidence.sfr_class, 3
                )
                group_rank = group_order.get(
                    evidence.e1rm_substitution_group,
                    index,
                )
                within_group_rank = evidence.preferred_rank or 1_000_000
                gold_standard_rank = 0 if evidence.is_gold_standard else 1
            elif preferences.goal == "strength" and goal_rank == 0:
                sfr_rank = 0
                group_rank = group_order.get(
                    evidence.e1rm_substitution_group,
                    index,
                )
                within_group_rank = index
                gold_standard_rank = 0
            else:
                sfr_rank = 0
                group_rank = index
                within_group_rank = index
                gold_standard_rank = 0

            return (
                combined_rank,
                goal_rank,
                novice_rank,
                gold_standard_rank,
                sfr_rank,
                group_rank,
                within_group_rank,
                index,
            )

        return sorted(candidates, key=rank_key)

    def _present_exercise(self, exercise: Exercise) -> RecommendedExercise:
        profile = self._recommendation_profiles.get(exercise.source_id)

        return RecommendedExercise(
            source_id=exercise.source_id,
            name=exercise.name,
            name_ko=exercise.name_ko,
            primary_muscle_ko=self._muscle_names[exercise.primary_muscle_id],
            secondary_muscles_ko=[
                self._muscle_names[muscle_id]
                for muscle_id in exercise.secondary_muscle_ids
            ],
            equipment_ko=self._equipment_names[exercise.equipment_id],
            movement_pattern_ko=(
                self._pattern_names.get(exercise.movement_pattern_id)
                if exercise.movement_pattern_id is not None
                else None
            ),
            technical_complexity=(
                profile.technical_complexity if profile is not None else None
            ),
        )
