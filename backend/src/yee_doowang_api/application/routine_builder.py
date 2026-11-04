from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from yee_doowang_api.application.chat_models import (
    ChatCompletionError,
    ChatReply,
    CoachModel,
    ConversationMessage,
    ConversationState,
    EquipmentConstraint,
    ExerciseReasoner,
    RecommendationPreferences,
    RecommendedExercise,
    RoutineContext,
    RoutineDraft,
    RoutineExercise,
    RoutineProposal,
    RoutineSession,
)
from yee_doowang_api.application.exercise_catalog import Exercise, ExerciseCatalog
from yee_doowang_api.application.hypertrophy_prescription import (
    HypertrophyGuidelines,
    HypertrophyPrescription,
    HypertrophyProgressionRule,
    WeeklyDirectSetTarget,
)
from yee_doowang_api.application.routine_context import RoutineContextManager

_MAX_RECOMMENDED_CANDIDATES_PER_DAY = 5


class RoutineBuilder:
    def __init__(
        self,
        model: CoachModel,
        reasoner: ExerciseReasoner,
        catalog: ExerciseCatalog,
        hypertrophy_guidelines: HypertrophyGuidelines,
        context_manager: RoutineContextManager,
    ) -> None:
        self._model = model
        self._reasoner = reasoner
        self._catalog = catalog
        self._context_manager = context_manager
        self._known_equipment_ids = {item.id for item in catalog.equipment}
        self._recommendation_profiles = {
            item.source_id: item for item in catalog.recommendations.profiles
        }
        self._hypertrophy_guidelines = hypertrophy_guidelines
        self._exercises_by_id = {
            exercise.source_id: exercise for exercise in catalog.exercises
        }
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
        self._workout_days_by_id = {day.id: day for day in catalog.workout_days}
        self._workout_day_names = {
            day.id: day.name_ko for day in catalog.workout_days
        }
        self._focus_muscle_ids_by_day = {
            day.id: set(day.focus_muscle_ids) for day in catalog.workout_days
        }

    async def build(
        self,
        messages: Sequence[ConversationMessage],
        state: ConversationState,
        context_question: str | None,
    ) -> ChatReply:
        context = state.context
        question = context_question
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
                    quick_replies=self._context_manager.split_assignment_quick_replies(),
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
                    reply=self.equipment_options_reply(),
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
    def equipment_options_reply(self) -> str:
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
