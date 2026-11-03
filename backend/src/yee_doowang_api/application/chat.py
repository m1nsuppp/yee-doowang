from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yee_doowang_api.application.exercise_catalog import (
    Equipment,
    Exercise,
    ExerciseCatalog,
    Muscle,
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


class IntentDecision(_ChatModel):
    workout_intent: Literal[
        "push_day", "abs_day", "obliques_day", "clarify", "unsupported"
    ]
    equipment: EquipmentIntent
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
        if intent.workout_intent in {"clarify", "unsupported"}:
            reply = intent.message or (
                "현재는 푸시 데이, 복근, 복사근 운동을 추천해요. 어떤 부위를 원하시나요?"
            )
            return ChatReply(reply=reply, exercises=[])

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
                reply = (
                    f"장비 조건을 확인하지 못했어요. 현재 지원하는 장비: {options}."
                )
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
        answer = await self._model.answer(messages, candidates, constraint)
        return ChatReply(
            reply=answer.reply,
            exercises=[self._present_exercise(exercise) for exercise in candidates],
        )

    def _present_exercise(self, exercise: Exercise) -> RecommendedExercise:
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
        )
