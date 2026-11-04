from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from yee_doowang_api.application.chat_models import (
    ChatAction,
    ChatCompletionError,
    ChatReply,
    CoachModel,
    ConversationMessage,
    ConversationState,
    ExerciseReasoner,
    QuickReply,
    RoutineContext,
    WorkoutDayRecommendation,
)
from yee_doowang_api.application.exercise_catalog import ExerciseCatalog
from yee_doowang_api.application.hypertrophy_prescription import HypertrophyGuidelines
from yee_doowang_api.application.routine_builder import RoutineBuilder
from yee_doowang_api.application.routine_context import RoutineContextManager


class ChatService:
    def __init__(
        self,
        model: CoachModel,
        reasoner: ExerciseReasoner,
        catalog: ExerciseCatalog,
        hypertrophy_guidelines: HypertrophyGuidelines,
    ) -> None:
        self._model = model
        self._catalog = catalog
        self._muscles_by_id = {muscle.id: muscle for muscle in catalog.muscles}
        self._known_equipment_ids = {item.id for item in catalog.equipment}
        self._workout_day_names = {day.id: day.name_ko for day in catalog.workout_days}
        self._context_manager = RoutineContextManager(catalog)
        self._routine_builder = RoutineBuilder(
            model,
            reasoner,
            catalog,
            hypertrophy_guidelines,
            self._context_manager,
        )
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
            context = self._context_manager.merge(previous_context, intent.context)
            mode: Literal["general", "routine"] = "routine"
        elif intent.conversation_action == "answer_only":
            previous_context = state.context
            context = (
                self._context_manager.merge(state.context, intent.context)
                if state.mode == "routine"
                else state.context
            )
            mode = state.mode
        else:
            previous_context = state.context
            context = self._context_manager.merge(state.context, intent.context)
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
        invalid_split_reply = self._context_manager.invalid_split_configuration_reply(context)
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
                reply=self._routine_builder.equipment_options_reply(),
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

        if self._context_manager.has_unresolved_constraints(context.known_constraints):
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
                    reply=self._context_manager.next_context_question(context) or "운동 부위를 직접 골라주세요.",
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
            return self._context_manager.propose_split(context)
        if state.phase == "confirming_split" and context.split_template is not None:
            if intent.split_confirmation == "confirm":
                context = self._context_manager.replace_split_template_status(context, "confirmed")
                response_prefix = "A/B 분할을 확인했어요."
            elif intent.split_confirmation == "reject":
                context = self._context_manager.reject_split_proposal(context)
                return ChatReply(
                    reply=self._context_manager.split_assignment_question(context),
                    state=ConversationState(mode="routine", context=context),
                    exploration_exercises=[],
                    quick_replies=self._context_manager.split_assignment_quick_replies(),
                )
            else:
                return ChatReply(
                    reply=self._context_manager.split_confirmation_prompt(context),
                    state=ConversationState(mode="routine", phase="confirming_split", context=context),
                    exploration_exercises=[],
                    quick_replies=self._context_manager.split_quick_replies(),
                )


        question = self._context_manager.next_context_question(context)
        if question is not None:
            return ChatReply(
                reply="\n\n".join(part for part in (response_prefix, question) if part),
                state=ConversationState(mode="routine", context=context),
                exploration_exercises=[],
                quick_replies=self._context_manager.context_question_quick_replies(context),
            )

        if (
            context.workout_split_type.status == "provided"
            and context.workout_split_assignment.status == "delegated"
            and context.split_template is None
            and not context.split_proposal_rejected
        ):
            return self._context_manager.propose_split(context)

        if action == "confirm_context":
            if context != state.context:
                return ChatReply(
                    reply=self._context_manager.context_summary(context),
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
            reply="\n\n".join(part for part in (response_prefix, self._context_manager.context_summary(context)) if part),
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
            return self._context_manager.split_quick_replies()
        return []






    def _supported_workout_days_reply(self) -> str:
        options = ", ".join(self._workout_day_names.values())
        return f"요청한 부위는 아직 지원하지 않아요. 현재 지원 범위: {options}."


    async def _draft_routine(
        self,
        messages: Sequence[ConversationMessage],
        state: ConversationState,
    ) -> ChatReply:
        context_question = self._context_manager.next_context_question(state.context)
        return await self._routine_builder.build(messages, state, context_question)
