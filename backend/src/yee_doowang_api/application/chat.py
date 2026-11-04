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


class _ChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextField[T](_ChatModel):
    status: Literal["not_asked", "provided", "unknown", "skipped"] = "not_asked"
    value: T | None = None

    @model_validator(mode="after")
    def validate_status_value(self) -> ContextField[T]:
        if (self.status == "provided") != (self.value is not None):
            raise ValueError("only provided context fields may contain a value")
        return self




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
    goal: ContextField[Literal["hypertrophy", "strength", "other"]] = Field(
        default_factory=ContextField
    )
    experience: ContextField[Literal["novice", "experienced"]] = Field(
        default_factory=ContextField
    )
    sessions_per_week: ContextField[int] = Field(default_factory=ContextField)
    minutes_per_session: ContextField[int] = Field(default_factory=ContextField)
    equipment: ContextField[EquipmentIntent] = Field(default_factory=ContextField)
    preferences: ContextField[list[str]] = Field(default_factory=ContextField)
    known_constraints: ContextField[list[str]] = Field(default_factory=ContextField)

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
        return self


class RecommendationPreferences(_ChatModel):
    goal: Literal["hypertrophy", "strength", "skip", "unknown", "unsupported"]
    experience: Literal["novice", "experienced", "skip", "unknown"]


class IntentDecision(_ChatModel):
    context: RoutineContext
    safety_status: Literal["none", "clarify", "urgent"]
    message: str = Field(max_length=1200)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, message: str) -> str:
        return message.strip()


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


class ConversationState(_ChatModel):
    phase: Literal["collecting_context", "confirming_context", "reviewing_routine"] = (
        "collecting_context"
    )
    context: RoutineContext = Field(default_factory=RoutineContext)
    routine: RoutineDraft | None = None

    @model_validator(mode="after")
    def validate_phase_routine(self) -> ConversationState:
        if (self.phase == "reviewing_routine") != (self.routine is not None):
            raise ValueError("only a reviewed routine may contain a routine draft")
        return self


ChatAction = Literal["message", "confirm_context"]


class ChatReply(_ChatModel):
    reply: str
    state: ConversationState
    exploration_exercises: list[RecommendedExercise]


class ChatCompletionError(Exception):
    """A safe, provider-independent chat model failure."""


class CoachModel(Protocol):
    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        current_context: RoutineContext,
        equipment_options: Sequence[Equipment],
        workout_days: Sequence[WorkoutDay],
        muscles: Sequence[Muscle],
    ) -> IntentDecision: ...

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
    ) -> None:
        self._model = model
        self._reasoner = reasoner
        self._catalog = catalog
        self._recommendation_profiles = {
            item.source_id: item for item in catalog.recommendations.profiles
        }
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

    async def reply(
        self,
        messages: Sequence[ConversationMessage],
        state: ConversationState,
        action: ChatAction,
    ) -> ChatReply:
        if action == "confirm_context" and state.phase != "confirming_context":
            raise ValueError("Only a reviewed context can be confirmed")

        intent = await self._model.interpret(
            messages,
            state.context,
            self._catalog.equipment,
            self._catalog.workout_days,
            self._catalog.muscles,
        )
        context = self._merge_context(state.context, intent.context)
        if intent.safety_status == "urgent":
            return ChatReply(
                reply=(
                    "말씀하신 증상은 즉시 평가가 필요할 수 있어요. "
                    "운동을 멈추고 지금 응급 진료를 받으세요."
                ),
                state=ConversationState(context=context),
                exploration_exercises=[],
            )
        if intent.safety_status == "clarify":
            fallback = (
                "운동 추천 전에 통증 위치와 어떤 동작에서 심해지는지 확인할게요. "
                "통증을 악화시키는 운동은 중단해 주세요."
            )
            return ChatReply(
                reply=intent.message or fallback,
                state=ConversationState(context=context),
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
                state=ConversationState(context=context),
                exploration_exercises=[],
            )

        unknown_days = (
            set(context.workout_day_ids.value or []) - self._workout_day_names.keys()
            if context.workout_day_ids.status == "provided"
            else set()
        )
        if unknown_days:
            return ChatReply(
                reply=self._supported_workout_days_reply(),
                state=ConversationState(context=state.context),
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
                state=ConversationState(context=state.context),
                exploration_exercises=[],
            )
        question = self._next_context_question(context)
        if question is not None:
            return ChatReply(
                reply=question,
                state=ConversationState(context=context),
                exploration_exercises=[],
            )

        if action == "confirm_context":
            if context != state.context:
                return ChatReply(
                    reply=self._context_summary(context),
                    state=ConversationState(
                        phase="confirming_context",
                        context=context,
                    ),
                    exploration_exercises=[],
                )
            return await self._draft_routine(messages, state)
        if state.phase == "reviewing_routine" and context == state.context:
            return await self._draft_routine(messages, state)

        return ChatReply(
            reply=self._context_summary(context),
            state=ConversationState(phase="confirming_context", context=context),
            exploration_exercises=[],
        )

    @staticmethod
    def _merge_context(previous: RoutineContext, updates: RoutineContext) -> RoutineContext:
        merged = previous.model_dump()
        for field_name in RoutineContext.model_fields:
            field = getattr(updates, field_name)
            if field.status != "not_asked":
                merged[field_name] = field.model_dump()
        return RoutineContext.model_validate(merged)

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
        routine = RoutineDraft(
            sessions_per_week=context.sessions_per_week.value,
            minutes_per_session=(
                context.minutes_per_session.value
                if context.minutes_per_session.status == "provided"
                else None
            ),
            sessions=planned_sessions,
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
        return ChatReply(
            reply=(
                "조건에 맞는 운동 후보를 찾았어요. 주간 루틴 초안을 만들었어요."
                f"{equipment_note} 세트·횟수·중량은 근거가 확인되지 않아 포함하지 않았어요."
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
        for index, planned_session in enumerate(proposal.sessions, start=1):
            if planned_session.workout_day_id not in selected_day_ids:
                raise ChatCompletionError("Routine used an unrequested workout day.")
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
        if context.workout_day_ids.status in {"not_asked", "unknown"}:
            supported = ", ".join(self._workout_day_names.values())
            return (
                "주간 일정에 넣을 운동 부위를 알려주세요. 현재 지원 범위: "
                f"{supported}. 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.sessions_per_week.status in {"not_asked", "unknown"}:
            return (
                "주간 일정을 만들려면 주당 운동 횟수가 필요해요. "
                "주 1~7회 중 알려주세요. 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.goal.status in {"not_asked", "unknown"}:
            return (
                "우선할 목표가 근비대와 근력 중 무엇인가요? 모르거나 답하고 싶지 않으면 "
                "목표 분류를 건너뛸 수 있어요."
            )
        if context.goal.status == "provided" and context.goal.value == "other":
            return (
                "현재 출처가 연결된 목표는 근비대와 근력 진행이에요. "
                "둘 중 하나를 선택하거나 목표 분류를 건너뛰어 주세요."
            )
        if context.experience.status in {"not_asked", "unknown"}:
            return (
                "저항 운동을 처음 시작했거나 몇 년 쉬었다가 복귀했나요? "
                "경력은 자기보고로만 반영하며, 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.experience.status == "provided" and context.experience.value == "experienced":
            return (
                "경험자 적합도 근거는 아직 없어요. 경력 기준을 건너뛰고 "
                "목표·다른 조건만 반영할까요?"
            )
        if context.minutes_per_session.status in {"not_asked", "unknown"}:
            return (
                "한 번 운동할 때 가능한 시간을 알려주세요. 모르거나 답하고 싶지 않으면 "
                "시간 조건을 건너뛸 수 있어요."
            )
        if context.equipment.status in {"not_asked", "unknown"} or (
            context.equipment.value is not None
            and context.equipment.value.mode == "unknown"
        ):
            return (
                "사용할 수 있는 장비를 알려주세요. 모르거나 답하고 싶지 않으면 건너뛰어도 돼요. "
                "건너뛰면 보유 장비를 가정하지 않고 장비 제한 없이 후보를 살펴봅니다."
            )
        if context.preferences.status in {"not_asked", "unknown"}:
            return "선호하거나 피하고 싶은 동작이 있나요? 없거나 답하고 싶지 않으면 건너뛰어도 돼요."
        if context.known_constraints.status in {"not_asked", "unknown"}:
            return (
                "운동에서 고려할 제약이나 불편함을 알고 있나요? 진단명은 추정하지 않으며, "
                "모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        return None

    def _context_summary(self, context: RoutineContext) -> str:
        goal_names = {"hypertrophy": "근비대", "strength": "근력", "other": "기타 목표"}
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
            else:
                equipment_text = "선택 위임(보유 장비는 가정하지 않음)"
        else:
            equipment_text = self._field_status_label(context.equipment.status)

        return "\n".join(
            [
                "제가 이해한 내용이에요. 확인하거나 채팅으로 수정해 주세요.",
                f"- 운동 부위: {workout_days}",
                f"- 주당 빈도: {self._value_with_unit(context.sessions_per_week, '회')}",
                f"- 목표: {self._context_value_label(context.goal, goal_names)}",
                f"- 운동 경력: {self._context_value_label(context.experience, experience_names)}",
                f"- 회당 가능 시간: {self._value_with_unit(context.minutes_per_session, '분')}",
                f"- 장비: {equipment_text}",
                f"- 선호: {self._list_value_or_status(context.preferences)}",
                f"- 알고 있는 제약: {self._list_value_or_status(context.known_constraints)}",
                "이 요약이 맞으면 ‘확인하고 루틴 만들기’를 눌러주세요.",
            ]
        )

    @staticmethod
    def _field_status_label(status: str) -> str:
        return {"unknown": "모름", "skipped": "건너뜀"}.get(status, "미입력")

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
            and context.goal.value == "hypertrophy"
            and evidence is not None
            and evidence.modality == "hypertrophy"
        ):
            return "카탈로그 출처 프로필에 근비대 목표 관련 메타데이터가 있습니다."
        if (
            context.goal.status == "provided"
            and context.goal.value == "strength"
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
            if preferences.goal == "hypertrophy" and evidence.modality != "hypertrophy":
                continue
            if preferences.goal == "strength" and not evidence.loadable:
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
