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


class RecommendationPreferences(_ChatModel):
    goal: Literal["hypertrophy", "strength", "skip", "unknown", "unsupported"]
    experience: Literal["novice", "experienced", "skip", "unknown"]


class IntentDecision(_ChatModel):
    workout_intent: Literal[
        "push_day", "abs_day", "obliques_day", "clarify", "unsupported"
    ]
    equipment: EquipmentIntent
    personalization: RecommendationPreferences
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


class CoachAnswer(_ChatModel):
    reply: str = Field(min_length=1, max_length=2000)

    @field_validator("reply")
    @classmethod
    def reject_blank_reply(cls, reply: str) -> str:
        reply = reply.strip()
        if not reply:
            raise ValueError("reply must not be blank")
        return reply


class RecommendedExercise(_ChatModel):
    source_id: str
    name: str
    name_ko: str | None
    primary_muscle_ko: str
    secondary_muscles_ko: list[str]
    equipment_ko: str
    movement_pattern_ko: str | None
    technical_complexity: TechnicalComplexity | None


class ChatReply(_ChatModel):
    reply: str
    exercises: list[RecommendedExercise]


class ChatCompletionError(Exception):
    """A safe, provider-independent chat model failure."""


class CoachModel(Protocol):
    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        equipment_options: Sequence[Equipment],
        workout_days: Sequence[WorkoutDay],
        muscles: Sequence[Muscle],
    ) -> IntentDecision: ...

    async def answer(
        self,
        messages: Sequence[ConversationMessage],
        candidates: Sequence[Exercise],
        equipment_constraint: EquipmentConstraint,
        personalization: RecommendationPreferences,
        recommendation_profiles: Sequence[ExerciseRecommendationProfile],
    ) -> CoachAnswer: ...


class ExerciseReasoner(Protocol):
    async def recommend(
        self,
        *,
        workout_day_id: str,
        equipment_constraint: EquipmentConstraint,
    ) -> list[Exercise]: ...


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

    async def reply(self, messages: Sequence[ConversationMessage]) -> ChatReply:
        intent = await self._model.interpret(
            messages,
            self._catalog.equipment,
            self._catalog.workout_days,
            self._catalog.muscles,
        )
        if intent.safety_status == "urgent":
            return ChatReply(
                reply=(
                    "말씀하신 증상은 즉시 평가가 필요할 수 있어요. "
                    "운동을 멈추고 지금 응급 진료를 받으세요."
                ),
                exercises=[],
            )
        if intent.safety_status == "clarify":
            fallback = (
                "운동 추천 전에 통증 위치와 어떤 동작에서 심해지는지 확인할게요. "
                "통증을 악화시키는 운동은 중단해 주세요."
            )
            return ChatReply(reply=intent.message or fallback, exercises=[])

        if intent.workout_intent in {"clarify", "unsupported"}:
            reply = intent.message or (
                "현재는 푸시 데이, 복근, 복사근 운동을 추천해요. 어떤 부위를 원하시나요?"
            )
            return ChatReply(reply=reply, exercises=[])
        personalization_reply = self._personalization_reply(intent)
        if personalization_reply is not None:
            return ChatReply(reply=personalization_reply, exercises=[])

        equipment_intent = intent.equipment
        if equipment_intent.mode == "unknown":
            reply = intent.message or (
                "사용할 장비를 모르셔도 괜찮아요. 장비를 알려주시거나 "
                "‘알아서 골라줘’라고 말씀해 주세요."
            )
            return ChatReply(reply=reply, exercises=[])

        if equipment_intent.mode == "specified":
            equipment_ids = list(dict.fromkeys(equipment_intent.equipment_ids))
            if set(equipment_ids) - self._known_equipment_ids:
                options = ", ".join(self._equipment_names.values())
                reply = f"장비 조건을 확인하지 못했어요. 현재 지원하는 장비: {options}."
                return ChatReply(reply=reply, exercises=[])
            constraint = EquipmentConstraint(
                mode="specified",
                equipment_ids=equipment_ids,
            )
        else:
            constraint = EquipmentConstraint(mode="unrestricted", equipment_ids=[])

        candidates = await self._reasoner.recommend(
            workout_day_id=intent.workout_intent,
            equipment_constraint=constraint,
        )
        evidence_reply = self._evidence_coverage_reply(
            candidates,
            intent.personalization,
        )
        if evidence_reply is not None:
            return ChatReply(reply=evidence_reply, exercises=[])
        candidates = self._rank_candidates(candidates, intent.personalization)
        candidate_ids = {exercise.source_id for exercise in candidates}
        recommendation_profiles = [
            profile
            for profile in self._catalog.recommendations.profiles
            if profile.source_id in candidate_ids
        ]
        answer = await self._model.answer(
            messages,
            candidates,
            constraint,
            intent.personalization,
            recommendation_profiles,
        )
        return ChatReply(
            reply=answer.reply,
            exercises=[self._present_exercise(exercise) for exercise in candidates],
        )

    @staticmethod
    def _personalization_reply(intent: IntentDecision) -> str | None:
        preferences = intent.personalization
        if preferences.goal == "unsupported":
            return intent.message or (
                "현재 외부 근거가 연결된 목표는 근비대와 근력 진행이에요. "
                "둘 중 하나를 고르거나 목표 분류를 건너뛰어 주세요."
            )
        if preferences.goal == "unknown":
            return intent.message or "근비대와 근력 중 우선할 목표를 알려주세요."
        if preferences.experience == "unknown":
            return intent.message or (
                "운동을 처음 시작했거나 몇 년 쉬었다가 복귀했는지 알려주세요. "
                "모르거나 답하고 싶지 않으면 경력 분류를 건너뛸 수 있어요."
            )
        if preferences.experience == "experienced":
            return intent.message or (
                "확인된 운동 경력 근거는 초보·복귀 운동자에 한정돼요. "
                "경력 기준 정렬을 건너뛰고 목표 기준으로만 추천할까요?"
            )
        return None

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
