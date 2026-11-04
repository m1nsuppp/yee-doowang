import re
import unittest
from collections.abc import Sequence

from fastapi.testclient import TestClient

from yee_doowang_api.application.chat import (
    ChatCompletionError,
    ChatService,
    CoachTurn,
    ContextField,
    ConversationMessage,
    ConversationState,
    EquipmentIntent,
    PlannedExercise,
    PlannedSession,
    RoutineContext,
    RoutineProposal,
    SessionTimeRange,
    WorkoutDayRecommendation,
    WorkoutSplitTemplate,
)
from yee_doowang_api.application.exercise_catalog import (
    Equipment,
    Exercise,
    ExerciseRecommendationProfile,
    Muscle,
    WorkoutDay,
)
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog
from yee_doowang_api.main import create_app
from yee_doowang_api.settings import Settings


class FixtureCoachModel:
    @staticmethod
    def _field(value: object = None, *, status: str = "provided") -> ContextField:
        return ContextField(status=status, value=value)

    @classmethod
    def _context(
        cls,
        transcript: str,
        current: RoutineContext,
        workout_days: Sequence[WorkoutDay],
        latest_user_message: str | None = None,
        muscles: Sequence[Muscle] = (),
    ) -> tuple[RoutineContext, str]:
        updates: dict[str, ContextField] = {}
        message = ""
        text = transcript.lower()
        latest = (latest_user_message or transcript).lower()

        def field_text(_terms: tuple[str, ...]) -> str:
            return latest

        area_terms = {
            "push_day": ("push", "푸시", "푸시 데이", "푸시데이", "가슴", "삼두", "어깨", "위팔세갈래근"),
            "back_day": (
                "등",
                "허리",
                "척추",
                "광배근",
                "상부 등",
                "승모근",
                "능형근",
            ),
            "biceps_day": ("이두", "위팔두갈래근", "상완근"),
            "legs_day": (
                "하체",
                "대퇴사두근",
                "햄스트링",
                "둔근",
                "종아리",
                "내전근",
                "외전근",
                "고관절 굴곡근",
                "가자미근",
                "정강이",
                "발목",
                "발",
                "사타구니",
                "허벅지 안쪽",
            ),
            "forearms_day": ("전완", "전완근", "손목", "손목 굽힘근", "손목 폄근"),
            "scapula_day": ("견갑", "전거근", "견갑거근"),
            "core_day": ("코어",),
            "abs_day": ("복근", "하복근"),
            "obliques_day": ("복사근", "옆구리"),
        }
        unsupported_terms = ("심혈관계", "회전근개")
        concept_question = any(
            marker in latest
            for marker in ("차이", "무슨 뜻", "뭐예요", "뭐에요", "무엇인가요", "뜻이 뭐", "설명해")
        ) and "추천" not in latest
        set_report_turn = re.search(r"[0-9]+\s*세트", latest) is not None
        workout_terms = tuple(
            term for terms in area_terms.values() for term in terms
        )
        workout_text = field_text((*workout_terms, *unsupported_terms))
        selected_days = [
            day.id
            for day in workout_days
            if not concept_question
            and not set_report_turn
            and any(term in workout_text for term in area_terms.get(day.id, ()))
        ]
        if selected_days:
            updates["workout_day_ids"] = cls._field(list(dict.fromkeys(selected_days)))
        elif not concept_question and not set_report_turn and any(term in workout_text for term in unsupported_terms):
            updates["workout_day_ids"] = cls._field(status="unknown")
            message = "요청한 운동 부위는 아직 지원하지 않습니다."
        elif not concept_question and not set_report_turn and (
            "잘 모르" in latest or ("추천" in latest and ("부위" in latest or "선택" in latest))
        ):
            updates["workout_day_ids"] = cls._field(status="delegated")
        if "분할 없이" in latest or ("취소" in latest and "분할" in latest):
            updates["workout_split_type"] = cls._field(status="skipped")
            updates["workout_split_assignment"] = cls._field(status="skipped")
        elif not concept_question and "2분할" in latest:
            updates["workout_split_type"] = cls._field("ab")

        split_type = updates.get("workout_split_type", current.workout_split_type)
        if (
            split_type.status == "provided"
            and current.workout_split_assignment.status != "provided"
            and any(term in latest for term in ("알아서", "맡길게", "제안해", "선택해줘"))
        ):
            updates["workout_split_assignment"] = cls._field(status="delegated")
        elif split_type.status == "provided" and "a는" in latest and "b는" in latest:
            a_text, b_text = re.split(
                r"\bb\s*(?:는|:)", latest, maxsplit=1, flags=re.IGNORECASE
            )
            a_text = re.sub(r"^.*?\ba\s*(?:는|:)", "", a_text, flags=re.IGNORECASE)
            day_a_ids = [
                day.id
                for day in workout_days
                if any(term in a_text for term in area_terms.get(day.id, ()))
            ]
            day_b_ids = [
                day.id
                for day in workout_days
                if any(term in b_text for term in area_terms.get(day.id, ()))
            ]
            if day_a_ids and day_b_ids:
                updates["workout_split_assignment"] = cls._field(
                    WorkoutSplitTemplate(day_a_ids=day_a_ids, day_b_ids=day_b_ids)
                )

        goal_text = "" if concept_question else field_text(
            ("근비대", "근육 증가", "근력", "목표 건너", "목표는 상관없", "감량", "지구력", "일반 체력", "목표 모르")
        )
        has_hypertrophy = any(term in goal_text for term in ("근비대", "근육 증가"))
        has_strength = "근력" in goal_text
        if any(term in goal_text for term in ("목표 건너", "목표는 상관없")):
            updates["goal"] = cls._field(status="skipped")
        elif "목표 모르" in goal_text:
            updates["goal"] = cls._field(status="unknown")
        elif has_hypertrophy and has_strength:
            updates["goal"] = cls._field("both")
        elif has_hypertrophy:
            updates["goal"] = cls._field("hypertrophy")
        elif has_strength:
            updates["goal"] = cls._field("strength")
        elif any(term in goal_text for term in ("감량", "지구력", "일반 체력")):
            updates["goal"] = cls._field("other")

        adult_text = field_text(("성인", "미성년", "18세"))
        if any(term in adult_text for term in ("미성년", "18세 미만")):
            updates["adult_eligibility"] = cls._field("minor")
        elif "성인" in adult_text or "18세 이상" in adult_text:
            updates["adult_eligibility"] = cls._field("adult")
        elif "성인 여부 모르" in adult_text:
            updates["adult_eligibility"] = cls._field(status="unknown")
        elif "성인 여부 건너" in adult_text:
            updates["adult_eligibility"] = cls._field(status="skipped")

        experience_text = field_text(
            ("경력 건너", "경험 건너", "초보", "처음 시작", "복귀", "숙련자", "경험자", "경력 모르", "경험 모르", "경력은 모르", "경험은 모르")
        )
        if any(term in experience_text for term in ("경력 건너", "경험 건너")):
            updates["experience"] = cls._field(status="skipped")
        elif any(term in experience_text for term in ("경력 모르", "경험 모르", "경력은 모르", "경험은 모르")):
            updates["experience"] = cls._field(status="unknown")
        elif any(term in experience_text for term in ("초보", "처음 시작", "복귀")):
            updates["experience"] = cls._field("novice")
        elif any(term in experience_text for term in ("숙련자", "경험자")):
            updates["experience"] = cls._field("experienced")

        schedule_text = field_text(("주", "회", "횟수", "빈도"))
        if any(term in latest for term in ("횟수를 모르", "빈도를 모르", "주당 횟수는 모르")):
            updates["sessions_per_week"] = cls._field(status="unknown")
        elif any(term in latest for term in ("횟수 건너", "빈도 건너")):
            updates["sessions_per_week"] = cls._field(status="skipped")
        else:
            session_matches = list(re.finditer(r"주\s*([1-7])\s*회", text))
            sessions = re.search(r"주\s*([1-7])\s*회", latest)
            if sessions is None and session_matches:
                sessions = session_matches[-1]
            if sessions:
                updates["sessions_per_week"] = cls._field(int(sessions.group(1)))
            elif any(term in schedule_text for term in ("횟수 건너", "빈도 건너")):
                updates["sessions_per_week"] = cls._field(status="skipped")

        time_range = None
        range_separator = r"(?:~|～|〜|-|부터|에서)"
        minute_hour_range = re.search(
            rf"([1-9][0-9]*)\s*분\s*{range_separator}\s*([1-9][0-9]*)\s*시간",
            latest,
        )
        minute_range = re.search(
            rf"([1-9][0-9]*)\s*분?\s*{range_separator}\s*([1-9][0-9]*)\s*분",
            latest,
        )
        hour_range = re.search(
            rf"([1-9][0-9]*)\s*시간\s*{range_separator}\s*([1-9][0-9]*)\s*시간",
            latest,
        )
        if minute_hour_range:
            time_range = (int(minute_hour_range.group(1)), int(minute_hour_range.group(2)) * 60)
        elif minute_range:
            time_range = (int(minute_range.group(1)), int(minute_range.group(2)))
        elif hour_range:
            time_range = (int(hour_range.group(1)) * 60, int(hour_range.group(2)) * 60)
        if time_range:
            updates["minutes_per_session_range"] = cls._field(
                SessionTimeRange(minimum_minutes=time_range[0], maximum_minutes=time_range[1])
            )
            updates["minutes_per_session"] = cls._field(status="unknown")
        elif any(term in latest for term in ("시간 건너", "시간 조건 건너", "회당 시간 건너", "시간은 상관없")):
            updates["minutes_per_session"] = cls._field(status="skipped")
        elif any(term in latest for term in ("시간을 모르", "시간은 모르")):
            updates["minutes_per_session"] = cls._field(status="unknown")
        else:
            minutes = re.search(r"([1-9][0-9]*)\s*분", latest)
            hours = re.search(r"([1-9][0-9]*)\s*시간", latest)
            if minutes:
                updates["minutes_per_session"] = cls._field(int(minutes.group(1)))
            elif hours:
                updates["minutes_per_session"] = cls._field(int(hours.group(1)) * 60)
        equipment_text = field_text(
            ("장비", "알아서", "아무거나", "맨몸", "덤벨", "no equipment")
        )
        if any(term in equipment_text for term in ("장비 건너", "장비는 상관없")):
            updates["equipment"] = cls._field(status="skipped")
        elif "알아서" in equipment_text or "아무거나" in equipment_text:
            updates["equipment"] = cls._field(
                EquipmentIntent(mode="delegate_any", equipment_ids=[])
            )
        elif "맨몸" in equipment_text or "no equipment" in equipment_text:
            updates["equipment"] = cls._field(
                EquipmentIntent(mode="specified", equipment_ids=["body_weight"])
            )
        elif "덤벨" in equipment_text:
            updates["equipment"] = cls._field(
                EquipmentIntent(mode="specified", equipment_ids=["dumbbell"])
            )
        elif "모르겠" in equipment_text:
            updates["equipment"] = cls._field(
                EquipmentIntent(mode="unknown", equipment_ids=[])
            )

        preferences_text = field_text(
            ("선호", "좋아하는 운동", "피하고 싶은 운동")
        )
        if any(term in preferences_text for term in ("선호 없음", "선호하는 것 없어")):
            updates["preferences"] = cls._field([])
        elif any(term in preferences_text for term in ("선호 건너", "선호는 상관없")):
            updates["preferences"] = cls._field(status="skipped")
        elif "좋아하는 운동" in preferences_text or "피하고 싶은 운동" in preferences_text:
            preference_match = re.search(
                r"(?:좋아하는 운동은?|피하고 싶은 운동은?)\s*[:：]?\s*([^,.!?。]+)",
                preferences_text,
            )
            if preference_match:
                preference_kind = (
                    "좋아하는 운동"
                    if "좋아하는 운동" in preference_match.group(0)
                    else "피하고 싶은 운동"
                )
                updates["preferences"] = cls._field(
                    [f"{preference_kind}: {preference_match.group(1).strip()}"]
                )
            else:
                updates["preferences"] = cls._field(["사용자 선호"])

        constraints_text = field_text(("제약", "제한", "불편함", "부상"))
        if any(term in constraints_text for term in ("제약 없음", "제한 없음", "불편함 없음")):
            updates["known_constraints"] = cls._field([])
        elif any(term in constraints_text for term in ("제약 건너", "제약은 상관없")):
            updates["known_constraints"] = cls._field(status="skipped")
        set_reports: dict[str, int] = {}
        for muscle in muscles:
            terms = [muscle.name_ko, *muscle.aliases_ko, *muscle.source_terms]
            for term in sorted((term for term in terms if term), key=len, reverse=True):
                report = re.search(
                    rf"{re.escape(term.lower())}\s*(?:주간\s*)?(?:주\s*)?([0-9]+)\s*세트",
                    latest,
                )
                if report:
                    set_reports[muscle.id] = int(report.group(1))
                    break
        if set_reports:
            updates["weekly_direct_sets_by_muscle"] = cls._field(set_reports)
        if any(term in latest for term in ("세트 건너", "세트 보고 건너")):
            updates["weekly_direct_sets_follow_up"] = cls._field(status="skipped")
            if not set_reports:
                updates["weekly_direct_sets_by_muscle"] = cls._field(status="skipped")
        elif any(term in latest for term in ("세트 모르", "세트는 몰")):
            updates["weekly_direct_sets_follow_up"] = cls._field(status="unknown")
            if not set_reports:
                updates["weekly_direct_sets_by_muscle"] = cls._field(status="unknown")
        elif any(term in latest for term in ("세트 알아서", "세트 맡겨")):
            updates["weekly_direct_sets_follow_up"] = cls._field(status="delegated")
            if not set_reports:
                updates["weekly_direct_sets_by_muscle"] = cls._field(status="delegated")

        context_data = current.model_dump()
        for key, value in updates.items():
            if key == "weekly_direct_sets_by_muscle" and value.status == "provided" and current.weekly_direct_sets_by_muscle.status == "provided":
                reports = dict(current.weekly_direct_sets_by_muscle.value or {})
                reports.update(value.value or {})
                context_data[key] = {"status": "provided", "value": reports}
            else:
                context_data[key] = value.model_dump()
        return RoutineContext.model_validate(context_data), message

    @staticmethod
    def _safety(transcript: str) -> tuple[str, str]:
        resolved_terms = ("통증은 이제 없어", "통증은 없어", "이제 안 아파", "완전히 나았")
        if any(term in transcript for term in resolved_terms):
            return "none", ""
        urgent_terms = ("양쪽 다리", "회음부", "소변을 보기 어렵", "대소변", "교통사고")
        if any(term in transcript for term in urgent_terms):
            return "urgent", "운동을 중단하고 지금 응급 진료를 받으세요."
        if any(term in transcript for term in ("통증", "아파", "아프", "엉치", "꼬리뼈", "저림", "부상")):
            return "clarify", "통증 위치와 어떤 동작에서 심해지는지 알려주세요. 통증을 악화시키는 운동은 중단해 주세요."
        return "none", ""

    @staticmethod
    def _assistant_response(latest: str, context: RoutineContext) -> str:
        if any(term in latest for term in ("푸시 데이", "푸시데이", "push day")) and any(
            term in latest for term in ("뭐", "무슨 뜻", "무엇", "설명")
        ):
            return "푸시 데이는 가슴·어깨·삼두근을 함께 묶는 운동 분할 이름이에요."
        if "차이" in latest and "근비대" in latest and "근력" in latest:
            return "근비대는 근육 크기 증가를, 근력은 힘을 내는 능력 향상을 우선하는 목표예요. 목표는 함께 추구할 수 있지만 상담에서 우선순위를 정하면 돼요."
        if context.experience.status == "provided" and context.experience.value == "experienced" and any(
            term in latest for term in ("왜", "부담", "필요해")
        ):
            return "최근 직접 세트는 목표값이 아니라 현재 보고하신 양을 기록해 처방이 현황과 맞는지 확인하려는 정보예요. 한 번에 일부 근육만 알려주셔도 되고, 추정하지 않도록 모르는 값은 비워 두거나 전체 보고를 건너뛸 수 있어요."
        if context.equipment.status in {"not_asked", "unknown"} and any(
            term in latest for term in ("헬스장", "휘트니스", "피트니스", "gym")
        ):
            return "장소 이름으로 이해했어요. 장소만으로 보유 장비를 추측하지 않겠습니다. 사용할 수 있는 장비를 직접 알려주시거나, 선택을 맡기거나 장비 조건을 건너뛰어 주세요."
        return ""

    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        current_context: RoutineContext,
        current_mode: str,
        _equipment_options: Sequence[Equipment],
        workout_days: Sequence[WorkoutDay],
        current_recommendation: WorkoutDayRecommendation | None,
        muscle_options: Sequence[Muscle],
    ) -> CoachTurn:
        user_messages = [message.content.lower() for message in messages if message.role == "user"]
        transcript = " ".join(user_messages)
        latest_user_message = user_messages[-1] if user_messages else ""
        safety_status, safety_message = self._safety(transcript)
        context, context_message = self._context(
            transcript,
            current_context,
            workout_days,
            latest_user_message,
            muscle_options,
        )
        assistant_response = self._assistant_response(
            latest_user_message, current_context
        )
        split_confirmation = "none"
        if current_context.split_template is not None and current_context.split_template.confirmation_status == "proposed":
            if any(term in latest_user_message for term in ("확인합니다", "확인할게요", "맞아요", "동의")) and "바꾸" not in latest_user_message:
                split_confirmation = "confirm"
            elif any(term in latest_user_message for term in ("바꾸", "안 맞", "거부")):
                split_confirmation = "reject"
        elif current_context.split_proposal_rejected and "다시 제안" in latest_user_message:
            split_confirmation = "repropose"
        recommendation_confirmation = "none"
        if current_recommendation is not None:
            if any(term in latest_user_message for term in ("추천한 운동 부위로 진행", "이 부위로 진행", "이대로 진행")):
                recommendation_confirmation = "accept"
            elif "다른 운동 부위" in latest_user_message and "추천" in latest_user_message:
                recommendation_confirmation = "repropose"
            elif "직접 고를" in latest_user_message:
                recommendation_confirmation = "reject"
        time_range_separator = r"(?:~|～|〜|-|부터|에서)"
        mentions_time_range = re.search(
            rf"[0-9]+\s*(?:분|시간)?\s*{time_range_separator}\s*[0-9]+\s*(?:분|시간)",
            latest_user_message,
        )
        explicit_minutes_target = (
            re.search(r"[1-9][0-9]*\s*(?:분|시간)", latest_user_message) is not None
            and mentions_time_range is None
        )
        if current_mode == "general":
            routine_request = any(
                term in latest_user_message
                for term in ("루틴 추천", "루틴 만들어", "루틴 짜", "운동 계획 만들어")
            )
            conversation_action = "start_routine" if routine_request else "answer_only"
        elif any(term in latest_user_message for term in ("루틴 취소", "루틴 그만", "루틴 만들기 그만")):
            conversation_action = "cancel_routine"
        elif assistant_response:
            conversation_action = "answer_only"
        else:
            conversation_action = "continue_intake"
        return CoachTurn(
            context=context,
            safety_status=safety_status,
            message=safety_message or context_message,
            assistant_response=assistant_response,
            conversation_action=conversation_action,
            split_confirmation=split_confirmation,
            recommendation_confirmation=recommendation_confirmation,
            explicit_minutes_target=explicit_minutes_target,
        )


    async def recommend_workout_days(
        self,
        _messages: Sequence[ConversationMessage],
        _context: RoutineContext,
        workout_days: Sequence[WorkoutDay],
    ) -> WorkoutDayRecommendation:
        return WorkoutDayRecommendation(
            workout_day_ids=[day.id for day in workout_days[:2]],
            rationale="현재 정보가 적어 시작점으로만 제안해요.",
        )
    async def plan_routine(
        self,
        _messages: Sequence[ConversationMessage],
        context: RoutineContext,
        candidates_by_day: dict[str, Sequence[Exercise]],
        _workout_days: Sequence[WorkoutDay],
        _recommendation_profiles: Sequence[ExerciseRecommendationProfile],
        _current_routine,
    ) -> RoutineProposal:
        session_count = context.sessions_per_week.value
        assert session_count is not None
        day_ids = context.workout_day_ids.value
        assert day_ids
        split_template = (
            context.split_template
            if context.split_template is not None
            and context.split_template.confirmation_status == "confirmed"
            else context.workout_split_assignment.value
            if context.workout_split_assignment.status == "provided"
            else None
        )
        sessions = []
        for index in range(session_count):
            if split_template is None:
                day_id = day_ids[index % len(day_ids)]
            else:
                group = split_template.day_a_ids if index % 2 == 0 else split_template.day_b_ids
                day_id = group[(index // 2) % len(group)]
            candidates = candidates_by_day[day_id]
            selected = candidates[0]
            sessions.append(
                PlannedSession(
                    workout_day_id=day_id,
                    exercises=[
                        PlannedExercise(
                            source_id=selected.source_id,
                            alternative_source_ids=[
                                item.source_id for item in candidates[1:3]
                            ],
                        )
                    ],
                )
            )
        return RoutineProposal(sessions=sessions)


class ContextPreservingCoachModel(FixtureCoachModel):
    async def interpret(
        self,
        _messages: Sequence[ConversationMessage],
        current_context: RoutineContext,
        _current_mode: str,
        _equipment_options: Sequence[Equipment],
        _workout_days: Sequence[WorkoutDay],
        _current_recommendation: WorkoutDayRecommendation | None,
        _muscles: Sequence[Muscle],
    ) -> CoachTurn:
        return CoachTurn(
            context=current_context,
            safety_status="none",
            message="",
        )


class FailingCoachModel:
    async def interpret(
        self,
        _messages: Sequence[ConversationMessage],
        _current_context: RoutineContext,
        _current_mode: str,
        _equipment_options: Sequence[Equipment],
        _workout_days: Sequence[WorkoutDay],
        _current_recommendation: WorkoutDayRecommendation | None,
        _muscles: Sequence[Muscle],
    ) -> CoachTurn:
        raise ChatCompletionError("provider detail must not reach the caller")

    async def plan_routine(self, *_args: object, **_kwargs: object) -> RoutineProposal:
        raise AssertionError("routine planning must not run after interpretation fails")

    async def recommend_workout_days(self, *_args: object, **_kwargs: object) -> WorkoutDayRecommendation:
        raise AssertionError("recommendation must not run after interpretation fails")


class ChatApiTests(unittest.TestCase):
    @staticmethod
    def _messages_with_routine_context(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        context_turns = [
            {"role": "assistant", "content": "주당 운동 횟수는 몇 회인가요?"},
            {"role": "user", "content": "주 3회"},
            {"role": "assistant", "content": "회당 가능한 시간은요?"},
            {"role": "user", "content": "시간 조건 건너뛰기"},
            {"role": "assistant", "content": "선호하는 운동이 있나요?"},
            {"role": "user", "content": "선호 없음"},
            {"role": "assistant", "content": "운동 관련 제약이 있나요?"},
            {"role": "user", "content": "제약 없음"},
        ]
        return [*context_turns, *messages]

    def _post_confirmed_routine(
        self,
        client: TestClient,
        messages: list[dict[str, str]],
    ):
        conversation = self._messages_with_routine_context(messages)
        user_messages = [
            message["content"] for message in conversation if message["role"] == "user"
        ]
        if not any("성인" in content or "18세" in content or "미성년" in content for content in user_messages):
            conversation.append({"role": "user", "content": "만 18세 이상 성인입니다."})
            user_messages.append("만 18세 이상 성인입니다.")
        catalog = load_exercise_catalog()
        context = RoutineContext()
        for user_message in user_messages:
            parsed, _ = FixtureCoachModel._context(
                user_message,
                context,
                catalog.workout_days,
                user_message,
                catalog.muscles,
            )
            context = ChatService._merge_context(context, parsed)
        state = ConversationState(phase="confirming_context", context=context)
        return client.post(
            "/api/chat",
            json={
                "messages": [*conversation, {"role": "user", "content": "확인하고 루틴 만들기"}],
                "state": state.model_dump(mode="json"),
                "action": "confirm_context",
            },
        )

    @staticmethod
    def _push_dumbbell_context(
        preferences: list[str],
        known_constraints: list[str],
    ) -> RoutineContext:
        return RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["push_day"]),
            goal=ContextField(status="skipped"),
            experience=ContextField(status="skipped"),
            sessions_per_week=ContextField(status="provided", value=1),
            minutes_per_session=ContextField(status="skipped"),
            equipment=ContextField(
                status="provided",
                value=EquipmentIntent(mode="specified", equipment_ids=["dumbbell"]),
            ),
            preferences=ContextField(status="provided", value=preferences),
            known_constraints=ContextField(status="provided", value=known_constraints),
        )

    def _post_confirmed_with_context(
        self,
        client: TestClient,
        messages: list[dict[str, str]],
        context: RoutineContext,
    ):
        return client.post(
            "/api/chat",
            json={
                "messages": [
                    *messages,
                    {"role": "user", "content": "확인하고 루틴 만들기"},
                ],
                "state": ConversationState(
                    phase="confirming_context",
                    context=context,
                ).model_dump(mode="json"),
                "action": "confirm_context",
            },
        )

    @staticmethod
    def _all_response_exercises(body):
        exercises = list(body["exploration_exercises"])
        routine = body["state"]["routine"]
        if routine is not None:
            for session in routine["sessions"]:
                for planned in session["exercises"]:
                    exercises.append(planned["exercise"])
                    exercises.extend(planned["alternatives"])
        return exercises

    @staticmethod
    def _default_recommendation_ids(body):
        routine = body["state"]["routine"]
        if routine is None:
            return set()
        return {
            exercise["source_id"]
            for session in routine["sessions"]
            for planned in session["exercises"]
            for exercise in (planned["exercise"], *planned["alternatives"])
        }

    def test_context_must_be_confirmed_and_schedule_edits_change_the_draft(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay, 근비대 목표, 초보자, 만 18세 이상 성인, 덤벨, 주 2회, 회당 30분, 선호 없음, 제약 없음.",
            }
        ]

        with TestClient(app) as client:
            review = client.post("/api/chat", json={"messages": messages})
            self.assertEqual(review.status_code, 200)
            reviewed = review.json()
            self.assertEqual(reviewed["state"]["phase"], "confirming_context")
            self.assertIsNone(reviewed["state"]["routine"])
            self.assertEqual(reviewed["exploration_exercises"], [])
            self.assertIn("주당 빈도: 2회", reviewed["reply"])
            self.assertIn("회당 가능 시간: 30분", reviewed["reply"])

            changed_messages = [
                *messages,
                {"role": "user", "content": "주 1회, 회당 45분으로 수정할게요."},
            ]
            revised_summary = client.post(
                "/api/chat",
                json={
                    "messages": changed_messages,
                    "state": reviewed["state"],
                    "action": "message",
                },
            )
            revised_state = revised_summary.json()["state"]
            self.assertEqual(revised_summary.status_code, 200)
            self.assertEqual(revised_state["phase"], "confirming_context")
            self.assertEqual(revised_state["context"]["sessions_per_week"]["value"], 1)
            self.assertEqual(revised_state["context"]["minutes_per_session"]["value"], 45)
            self.assertIsNone(revised_state["routine"])

            routine_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        *changed_messages,
                        {"role": "user", "content": "확인하고 루틴 만들기"},
                    ],
                    "state": revised_state,
                    "action": "confirm_context",
                },
            )

            routine_body = routine_response.json()
            feedback_messages = [
                *changed_messages,
                {"role": "user", "content": "주 2회, 회당 20분으로 조정해 주세요."},
            ]
            updated_summary = client.post(
                "/api/chat",
                json={
                    "messages": feedback_messages,
                    "state": routine_body["state"],
                    "action": "message",
                },
            )
            updated_state = updated_summary.json()["state"]
            self.assertEqual(updated_state["phase"], "confirming_context")
            self.assertEqual(updated_state["context"]["sessions_per_week"]["value"], 2)
            self.assertEqual(updated_state["context"]["minutes_per_session"]["value"], 20)
            routine_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        *feedback_messages,
                        {"role": "user", "content": "확인하고 루틴 만들기"},
                    ],
                    "state": updated_state,
                    "action": "confirm_context",
                },
            )

        self.assertEqual(routine_response.status_code, 200)
        body = routine_response.json()
        routine = body["state"]["routine"]
        self.assertEqual(body["state"]["phase"], "reviewing_routine")
        self.assertEqual(routine["sessions_per_week"], 2)
        self.assertEqual(routine["minutes_per_session"], 20)
        self.assertEqual(len(routine["sessions"]), 2)
        planned_ids = {
            item["exercise"]["source_id"]
            for session in routine["sessions"]
            for item in session["exercises"]
        }
        default_ids = self._default_recommendation_ids(body)
        exploration_ids = {
            item["source_id"] for item in body["exploration_exercises"]
        }
        self.assertTrue(planned_ids)
        self.assertTrue(default_ids.isdisjoint(exploration_ids))
        self.assertIsNotNone(routine["hypertrophy_prescription"])


    def test_safety_signal_on_confirmation_still_blocks_routine(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay, 근비대 목표, 초보자, 만 18세 이상 성인, 덤벨, 주 2회, 회당 시간 건너뛰기, 선호 없음, 제약 없음.",
            }
        ]

        with TestClient(app) as client:
            review = client.post("/api/chat", json={"messages": messages})
            review_body = review.json()
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        *messages,
                        {"role": "user", "content": "양쪽 다리가 저리고 회음부 감각이 없어요."},
                    ],
                    "state": review_body["state"],
                    "action": "confirm_context",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("응급 진료", response.json()["reply"])
        self.assertEqual(response.json()["exploration_exercises"], [])
        self.assertIsNone(response.json()["state"]["routine"])

    def test_unverified_model_exercise_is_rejected(self) -> None:
        class InvalidPlanCoach(FixtureCoachModel):
            async def plan_routine(
                self,
                _messages: Sequence[ConversationMessage],
                context: RoutineContext,
                _candidates_by_day: dict[str, Sequence[Exercise]],
                _workout_days: Sequence[WorkoutDay],
                _recommendation_profiles: Sequence[ExerciseRecommendationProfile],
                _current_routine,
            ) -> RoutineProposal:
                session_count = context.sessions_per_week.value
                day_ids = context.workout_day_ids.value
                assert session_count is not None and day_ids
                return RoutineProposal(
                    sessions=[
                        PlannedSession(
                            workout_day_id=day_ids[index % len(day_ids)],
                            exercises=[
                                PlannedExercise(
                                    source_id="9999",
                                )
                            ],
                        )
                        for index in range(session_count)
                    ]
                )

        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=InvalidPlanCoach(),
        )
        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "PushDay 근비대 목표, 경력 건너뛰고 덤벨 추천해줘."}],
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "The LLM provider request failed.")

    def test_named_preference_promotes_eligible_exercise_outside_top_five(self) -> None:
        catalog = load_exercise_catalog()
        push_day = next(day for day in catalog.workout_days if day.id == "push_day")
        eligible = [
            exercise
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in push_day.focus_muscle_ids
            and exercise.equipment_id == "dumbbell"
        ]
        self.assertGreater(len(eligible), 5)
        preferred = eligible[5]
        preference = f"좋아하는 운동은 {preferred.name}"
        context = self._push_dumbbell_context([preference], [])

        class PreferenceCoach(ContextPreservingCoachModel):
            async def plan_routine(
                self,
                _messages: Sequence[ConversationMessage],
                context: RoutineContext,
                _candidates_by_day: dict[str, Sequence[Exercise]],
                _workout_days: Sequence[WorkoutDay],
                _recommendation_profiles: Sequence[ExerciseRecommendationProfile],
                _current_routine,
            ) -> RoutineProposal:
                session_count = context.sessions_per_week.value
                day_ids = context.workout_day_ids.value
                assert session_count is not None and day_ids
                return RoutineProposal(
                    sessions=[
                        PlannedSession(
                            workout_day_id=day_ids[index % len(day_ids)],
                            exercises=[PlannedExercise(source_id=preferred.source_id)],
                        )
                        for index in range(session_count)
                    ]
                )

        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=PreferenceCoach(),
        )
        with TestClient(app) as client:
            response = self._post_confirmed_with_context(
                client,
                [
                    {
                        "role": "user",
                        "content": f"PushDay 덤벨 운동에서 {preference}.",
                    }
                ],
                context,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        planned = body["state"]["routine"]["sessions"][0]["exercises"][0]
        self.assertEqual(planned["exercise"]["source_id"], preferred.source_id)
        self.assertEqual(
            planned["rationale"],
            "사용자가 명시한 운동명·동작 선호가 카탈로그 정보와 일치합니다.",
        )
        self.assertNotIn(
            preferred.source_id,
            {item["source_id"] for item in body["exploration_exercises"]},
        )

    def test_unmatched_preference_asks_before_planning(self) -> None:
        context = self._push_dumbbell_context(
            ["선호하는 운동은 고강도 인터벌 방식"],
            [],
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=ContextPreservingCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_with_context(
                client,
                [{"role": "user", "content": "PushDay 덤벨 운동을 추천해 주세요."}],
                context,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["state"]["routine"])
        self.assertEqual(body["exploration_exercises"], [])
        self.assertIn("카탈로그의 운동명이나 동작 분류", body["reply"])

    def test_known_constraint_blocks_candidates_even_if_interpreter_misses_safety(self) -> None:
        context = self._push_dumbbell_context([], ["현재 무릎 통증"])
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=ContextPreservingCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_with_context(
                client,
                [{"role": "user", "content": "PushDay 덤벨 운동을 추천해 주세요."}],
                context,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["state"]["routine"])
        self.assertEqual(body["exploration_exercises"], [])
        self.assertIn("제약을 운동별 금기로 임의 해석하지 않겠습니다", body["reply"])

    def test_avoided_catalog_exercise_is_not_recommended_or_explorable(self) -> None:
        catalog = load_exercise_catalog()
        push_day = next(day for day in catalog.workout_days if day.id == "push_day")
        avoided = next(
            exercise
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in push_day.focus_muscle_ids
            and exercise.equipment_id == "dumbbell"
        )
        context = self._push_dumbbell_context(
            [f"피하고 싶은 운동은 {avoided.name}"],
            [],
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=ContextPreservingCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_with_context(
                client,
                [
                    {
                        "role": "user",
                        "content": f"PushDay 덤벨 운동에서 {avoided.name}은 피하고 싶어요.",
                    }
                ],
                context,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn(
            avoided.source_id,
            {item["source_id"] for item in self._all_response_exercises(body)},
        )

    def test_skipped_weekly_frequency_does_not_create_an_assumed_schedule(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay, 주당 횟수 건너뛰기, 목표 건너뛰기, 경력 건너뛰기, 회당 시간 건너뛰기, 장비 건너뛰기, 선호 건너뛰기, 제약 건너뛰기.",
            }
        ]

        with TestClient(app) as client:
            review = client.post("/api/chat", json={"messages": messages})
            review_body = review.json()
            self.assertEqual(review_body["state"]["phase"], "confirming_context")
            self.assertEqual(
                review_body["state"]["context"]["sessions_per_week"]["status"],
                "skipped",
            )
            response = client.post(
                "/api/chat",
                json={
                    "messages": [*messages, {"role": "user", "content": "확인하고 루틴 만들기"}],
                    "state": review_body["state"],
                    "action": "confirm_context",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["state"]["routine"])
        self.assertEqual(response.json()["exploration_exercises"], [])
        self.assertIn("주당 횟수를 건너뛰어서", response.json()["reply"])

    def test_partial_interpretation_preserves_confirmed_context(self) -> None:
        class PartialUpdateCoach(FixtureCoachModel):
            async def interpret(
                self,
                _messages: Sequence[ConversationMessage],
                _current_context: RoutineContext,
                _current_mode: str,
                _equipment_options: Sequence[Equipment],
                _workout_days: Sequence[WorkoutDay],
                _current_recommendation: WorkoutDayRecommendation | None,
                _muscles: Sequence[Muscle],
            ) -> CoachTurn:
                return CoachTurn(
                    context=RoutineContext(
                        minutes_per_session=ContextField(
                            status="provided",
                            value=20,
                        )
                    ),
                    safety_status="none",
                    message="",
                )

        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=PartialUpdateCoach(),
        )
        context = RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["abs_day"]),
            goal=ContextField(status="provided", value="hypertrophy"),
            experience=ContextField(status="skipped"),
            sessions_per_week=ContextField(status="provided", value=2),
            minutes_per_session=ContextField(status="provided", value=30),
            equipment=ContextField(status="skipped"),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="skipped"),
            adult_eligibility=ContextField(status="provided", value="adult"),
        )
        state = ConversationState(phase="confirming_context", context=context)

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "회당 시간을 20분으로 수정합니다."}
                    ],
                    "state": state.model_dump(mode="json"),
                    "action": "message",
                },
            )

        self.assertEqual(response.status_code, 200)
        updated = response.json()["state"]["context"]
        self.assertEqual(response.json()["state"]["phase"], "confirming_context")
        self.assertEqual(updated["workout_day_ids"]["value"], ["abs_day"])
        self.assertEqual(updated["goal"]["value"], "hypertrophy")
        self.assertEqual(updated["sessions_per_week"]["value"], 2)
        self.assertEqual(updated["minutes_per_session"]["value"], 20)
        self.assertEqual(updated["experience"]["status"], "skipped")
    def test_unknown_context_is_not_silently_treated_as_skipped(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "PushDay, 근비대 목표, 만 18세 이상 성인, 운동 경력은 모르겠어요, 덤벨, 주 2회, 선호 없음, 제약 없음.",
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"]["context"]["experience"]["status"], "unknown")
        self.assertEqual(response.json()["state"]["phase"], "collecting_context")
        self.assertIsNone(response.json()["state"]["routine"])
        self.assertIn("모르시는 걸로 기록했어요", response.json()["reply"])

    def test_context_confirmation_action_requires_review_phase(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "확인하고 루틴 만들기"}],
                    "action": "confirm_context",
                },
            )

        self.assertEqual(response.status_code, 422)
    def test_followup_context_returns_only_pyrewire_candidates(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay 근비대 목표, 경력 건너뛰고 운동 추천해줘.",
            },
            {"role": "assistant", "content": "사용할 수 있는 장비가 있나요?"},
            {"role": "user", "content": "맨몸만 사용할 수 있어."},
        ]

        with TestClient(app) as client:
            response = self._post_confirmed_routine(client, messages)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("주간 루틴 초안", body["reply"])
        catalog = load_exercise_catalog()
        focus_muscle_ids = next(
            set(day.focus_muscle_ids)
            for day in catalog.workout_days
            if day.id == "push_day"
        )
        expected = {
            exercise.source_id: exercise
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in focus_muscle_ids
            and exercise.equipment_id == "body_weight"
        }
        recommendations = {
            item["source_id"]: item for item in self._all_response_exercises(body)
        }
        self.assertEqual(set(recommendations), set(expected))
        equipment_names = {
            item.id: item.name_ko or f"원문 장비명: {item.source_term}"
            for item in catalog.equipment
        }
        muscle_names = {
            item.id: item.name_ko or f"원문 근육명: {item.source_terms[0]}"
            for item in catalog.muscles
        }
        pattern_names = {item.id: item.name_ko for item in catalog.movement_patterns}
        for source_id, source in expected.items():
            recommendation = recommendations[source_id]
            self.assertEqual(recommendation["name"], source.name)
            self.assertEqual(recommendation["name_ko"], source.name_ko)
            self.assertEqual(
                recommendation["primary_muscle_ko"],
                muscle_names[source.primary_muscle_id],
            )
            self.assertEqual(
                recommendation["secondary_muscles_ko"],
                [muscle_names[muscle_id] for muscle_id in source.secondary_muscle_ids],
            )
            self.assertEqual(
                recommendation["equipment_ko"],
                equipment_names[source.equipment_id],
            )
            self.assertEqual(
                recommendation["movement_pattern_ko"],
                pattern_names.get(source.movement_pattern_id)
                if source.movement_pattern_id is not None
                else None,
            )

    def test_current_pain_is_clarified_before_candidates_are_returned(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay 근비대 목표, 경력 건너뛰고 덤벨 추천해줘.",
            },
            {"role": "assistant", "content": "알겠습니다."},
            {"role": "user", "content": "엉치뼈가 아픈데 어떤 운동을 해야 해?"},
        ]

        with TestClient(app) as client:
            response = client.post("/api/chat", json={"messages": messages})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exploration_exercises"], [])
        self.assertIn("통증 위치", response.json()["reply"])
        self.assertIn("심해지는지", response.json()["reply"])
        self.assertIn("악화시키는 운동은 중단", response.json()["reply"])

    def test_explicitly_resolved_pain_restores_normal_recommendations(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay 근비대 목표, 경력 건너뛰고 덤벨 추천해줘.",
            },
            {"role": "assistant", "content": "알겠습니다."},
            {"role": "user", "content": "엉치뼈가 아파요."},
            {
                "role": "assistant",
                "content": "통증 위치와 악화되는 동작을 알려주세요.",
            },
            {"role": "user", "content": "통증은 이제 없어."},
        ]

        with TestClient(app) as client:
            response = self._post_confirmed_routine(client, messages)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "0334",
            {
                item["source_id"]
                for item in self._all_response_exercises(response.json())
            },
        )
        self.assertIn("주간 루틴 초안", response.json()["reply"])

    def test_red_flag_symptoms_stop_recommendations_and_escalate(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "하체 운동 추천해줘. 허리가 아프고 양쪽 다리가 저리며 "
                            "회음부 감각이 없고 소변을 보기 어려워요.",
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exploration_exercises"], [])
        self.assertIn("응급 진료", response.json()["reply"])

    def test_known_technical_complexity_is_reported_but_missing_data_is_null(
        self,
    ) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "PushDay 근비대 목표, 경력 건너뛰고 덤벨 추천해줘."}],
            )

        self.assertEqual(response.status_code, 200)
        by_id = {
            item["source_id"]: item
            for item in self._all_response_exercises(response.json())
        }
        self.assertEqual(by_id["0334"]["technical_complexity"], "low")
        self.assertIsNone(by_id["0355"]["technical_complexity"])


    def test_korean_muscle_alias_maps_to_same_push_candidates(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [
                    {
                        "role": "user",
                        "content": "위팔세갈래근 운동을 덤벨로 추천해줘. 근비대 목표, 초보자.",
                    }
                ],
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        catalog = load_exercise_catalog()
        push_muscle_ids = next(
            set(day.focus_muscle_ids)
            for day in catalog.workout_days
            if day.id == "push_day"
        )
        expected_ids = {
            exercise.source_id
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in push_muscle_ids
            and exercise.equipment_id == "dumbbell"
        }
        self.assertEqual(
            {
                exercise["source_id"]
                for exercise in self._all_response_exercises(body)
            },
            expected_ids,
        )
        kickback = next(
            exercise
            for exercise in self._all_response_exercises(body)
            if exercise["source_id"] == "0333"
        )
        self.assertEqual(kickback["primary_muscle_ko"], "삼두근")

    def test_goal_changes_candidate_order_using_pinned_source_metadata(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        requests = (
            "PushDay 근비대 목표, 경력 건너뛰고 알아서 추천해줘.",
            "PushDay 근력 목표, 경력 건너뛰고 알아서 추천해줘.",
        )

        with TestClient(app) as client:
            responses = [
                self._post_confirmed_routine(
                    client, [{"role": "user", "content": content}]
                )
                for content in requests
            ]

        for response, source_id in zip(responses, ("0178", "0025"), strict=True):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["state"]["routine"]["sessions"][0]["exercises"][0][
                    "exercise"
                ]["source_id"],
                source_id,
            )

    def test_novice_self_report_promotes_only_research_supported_exercises(
        self,
    ) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "PushDay 근비대 목표, 초보자, 덤벨 추천해줘."}],
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        planned = body["state"]["routine"]["sessions"][0]["exercises"][0]
        self.assertEqual(planned["exercise"]["source_id"], "0334")

    def test_missing_and_unsupported_contexts_ask_instead_of_guessing(
        self,
    ) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        requests = (
            "PushDay 덤벨 추천해줘.",
            "PushDay 감량 목표, 초보자, 덤벨 추천해줘.",
            "PushDay 근비대 목표, 덤벨 추천해줘.",
        )

        with TestClient(app) as client:
            responses = [
                self._post_confirmed_routine(
                    client, [{"role": "user", "content": content}]
                )
                for content in requests
            ]

        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(
            all(response.json()["exploration_exercises"] == [] for response in responses)
        )
        self.assertIn("두 목표를 함께", responses[0].json()["reply"])
        self.assertIn("근력 진행", responses[1].json()["reply"])
        self.assertIn("복귀", responses[2].json()["reply"])

    def test_combined_goals_are_preserved_and_rank_jointly_supported_exercises(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{
                    "role": "user",
                    "content": "PushDay 근비대와 근력 목표 둘 다, 초보자, 덤벨 추천해줘.",
                }],
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body["state"]["context"]["goal"],
            {"status": "provided", "value": "both"},
        )
        routine = body["state"]["routine"]
        self.assertIsNotNone(routine)
        self.assertIsNotNone(routine["hypertrophy_prescription"])
        exercise_ids = [
            item["exercise"]["source_id"]
            for session in routine["sessions"]
            for item in session["exercises"]
        ]
        profiles = {
            profile.source_id: profile.exercise_api
            for profile in load_exercise_catalog().recommendations.profiles
        }
        self.assertTrue(exercise_ids)
        for source_id in exercise_ids:
            evidence = profiles[source_id]
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.modality, "hypertrophy")
            self.assertTrue(evidence.loadable)
            self.assertIsNotNone(evidence.e1rm_substitution_group)

    def test_abs_day_chat_returns_only_abdominal_primary_targets(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "맨몸 복근 운동 추천해줘. 목표 건너뛰고 경력 건너뛰고."}],
            )

        self.assertEqual(response.status_code, 200)
        catalog = load_exercise_catalog()
        eligible_order = [
            exercise.source_id
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in {"abs", "lower_abs"}
            and exercise.equipment_id == "body_weight"
        ]
        expected_ids = set(eligible_order)
        body = response.json()
        all_ids = {
            exercise["source_id"] for exercise in self._all_response_exercises(body)
        }
        default_ids = self._default_recommendation_ids(body)
        exploration_ids = {
            exercise["source_id"] for exercise in body["exploration_exercises"]
        }
        self.assertEqual(len(expected_ids), 89)
        self.assertEqual(all_ids, expected_ids)
        self.assertTrue(default_ids)
        self.assertLessEqual(default_ids, set(eligible_order[:5]))
        self.assertTrue(default_ids.isdisjoint(exploration_ids))
        self.assertEqual(default_ids | exploration_ids, expected_ids)

    def test_added_workout_areas_match_primary_secondary_targets_and_equipment(
        self,
    ) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        catalog = load_exercise_catalog()
        cases = (
            ("등/허리", "back_day", "덤벨", "dumbbell", "0326"),
            ("이두", "biceps_day", "덤벨", "dumbbell", "0285"),
            ("하체", "legs_day", "맨몸", "body_weight", "0001"),
            ("전완", "forearms_day", "덤벨", "dumbbell", "0285"),
            ("견갑", "scapula_day", "맨몸", "body_weight", "1403"),
            ("코어", "core_day", "맨몸", "body_weight", "3297"),
        )

        with TestClient(app) as client:
            for area_name, day_id, equipment_name, equipment_id, source_id in cases:
                with self.subTest(area=area_name):
                    response = self._post_confirmed_routine(
                        client,
                        [
                            {
                                "role": "user",
                                "content": (
                                    f"{equipment_name} {area_name} 운동 추천해줘. "
                                    "목표 건너뛰고 경력 건너뛰고."
                                ),
                            }
                        ],
                    )

                    self.assertEqual(response.status_code, 200)
                    day = next(
                        day for day in catalog.workout_days if day.id == day_id
                    )
                    focus_muscles = set(day.focus_muscle_ids)
                    expected_ids = {
                        exercise.source_id
                        for exercise in catalog.exercises
                        if exercise.equipment_id == equipment_id
                        and (
                            exercise.primary_muscle_id in focus_muscles
                            or day.include_secondary_muscles
                            and not focus_muscles.isdisjoint(
                                exercise.secondary_muscle_ids
                            )
                        )
                    }
                    body = response.json()
                    self.assertEqual(
                        {
                            exercise["source_id"]
                            for exercise in self._all_response_exercises(body)
                        },
                        expected_ids,
                    )
                    self.assertIn(
                        source_id,
                        {
                            exercise["source_id"]
                            for exercise in self._all_response_exercises(body)
                        },
                    )
                    self.assertTrue(
                        all(
                            exercise["equipment_ko"] == equipment_name
                            for exercise in self._all_response_exercises(body)
                        )
                    )
                    default_ids = self._default_recommendation_ids(body)
                    exploration_ids = {
                        exercise["source_id"]
                        for exercise in body["exploration_exercises"]
                    }
                    self.assertTrue(default_ids.isdisjoint(exploration_ids))
                    self.assertEqual(default_ids | exploration_ids, expected_ids)


    def test_untranslated_catalog_labels_are_explicit(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "복근 운동 알아서 골라줘. 근비대 목표, 경력 건너뛰고."}],
            )

        self.assertEqual(response.status_code, 200)
        exercise = next(
            exercise
            for exercise in self._all_response_exercises(response.json())
            if exercise["source_id"] == "0011"
        )
        self.assertIsNone(exercise["name_ko"])
        self.assertEqual(exercise["name"], "assisted hanging knee raise")
        self.assertEqual(exercise["primary_muscle_ko"], "복근")
        self.assertEqual(exercise["equipment_ko"], "원문 장비명: assisted")

    def test_obliques_day_chat_includes_secondary_muscle_candidates(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "복사근 운동 추천해줘. 알아서 골라줘. 목표 건너뛰고 경력 건너뛰고."}],
            )

        self.assertEqual(response.status_code, 200)
        catalog = load_exercise_catalog()
        expected_ids = {
            exercise.source_id
            for exercise in catalog.exercises
            if exercise.primary_muscle_id == "obliques"
            or "obliques" in exercise.secondary_muscle_ids
        }
        self.assertEqual(
            {
                exercise["source_id"]
                for exercise in self._all_response_exercises(response.json())
            },
            expected_ids,
        )
        self.assertTrue(
            any(
                "복사근" in exercise["secondary_muscles_ko"]
                for exercise in self._all_response_exercises(response.json())
            )
        )

    def test_missing_candidate_evidence_requires_explicit_personalization_opt_out(
        self,
    ) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "복사근 운동, 근비대 목표, 초보자로 알아서 추천해줘."}],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exploration_exercises"], [])
        self.assertIn("경력 기준 정렬을 건너뛰고", response.json()["reply"])

    def test_generic_chat_request_asks_for_workout_area(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "운동 추천해줘."}]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exploration_exercises"], [])
        self.assertIn("복근", response.json()["reply"])
        self.assertIn("복사근", response.json()["reply"])

    def test_missing_equipment_produces_a_clarifying_turn(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{"role": "user", "content": "PushDay 근비대 목표, 초보자 추천해줘."}],
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("장비를 알려주세요", response.json()["reply"])
        self.assertIn("건너뛰", response.json()["reply"])
        self.assertEqual(response.json()["exploration_exercises"], [])

    def test_explicit_delegation_returns_candidates_across_equipment(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {"role": "user", "content": "PushDay 운동 추천해줘. 근비대 목표, 초보자."},
            {"role": "assistant", "content": "어떤 장비를 쓸 수 있나요?"},
            {"role": "user", "content": "모르겠어. 알아서 추천해줘."},
        ]

        with TestClient(app) as client:
            response = self._post_confirmed_routine(client, messages)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("제한하지 않고", body["reply"])
        catalog = load_exercise_catalog()
        focus_muscle_ids = next(
            set(day.focus_muscle_ids)
            for day in catalog.workout_days
            if day.id == "push_day"
        )
        expected_ids = {
            exercise.source_id
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in focus_muscle_ids
        }
        self.assertEqual(
            {
                exercise["source_id"]
                for exercise in self._all_response_exercises(body)
            },
            expected_ids,
        )
        self.assertLess(len(body["exploration_exercises"]), len(catalog.exercises))
        source_exercises = {
            exercise.source_id: exercise for exercise in catalog.exercises
        }
        equipment_names = {
            item.id: item.name_ko or f"원문 장비명: {item.source_term}"
            for item in catalog.equipment
        }
        muscle_names = {
            item.id: item.name_ko or f"원문 근육명: {item.source_terms[0]}"
            for item in catalog.muscles
        }
        pattern_names = {item.id: item.name_ko for item in catalog.movement_patterns}
        for recommendation in self._all_response_exercises(body):
            source = source_exercises[recommendation["source_id"]]
            self.assertEqual(recommendation["name"], source.name)
            self.assertEqual(recommendation["name_ko"], source.name_ko)
            self.assertEqual(
                recommendation["primary_muscle_ko"],
                muscle_names[source.primary_muscle_id],
            )
            self.assertEqual(
                recommendation["equipment_ko"], equipment_names[source.equipment_id]
            )
            self.assertEqual(
                recommendation["movement_pattern_ko"],
                pattern_names.get(source.movement_pattern_id)
                if source.movement_pattern_id is not None
                else None,
            )
        self.assertTrue(
            all(
                exercise["primary_muscle_ko"] and exercise["equipment_ko"]
                for exercise in self._all_response_exercises(body)
            )
        )
        self.assertGreater(
            len(
                {
                    exercise["equipment_ko"]
                    for exercise in self._all_response_exercises(body)
                }
            ), 1
        )

    def test_unsupported_workout_request_does_not_return_exercises(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        requests = ("심혈관계 운동 추천해줘.", "회전근개 운동 추천해줘.")

        with TestClient(app) as client:
            responses = [
                client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": request}]},
                )
                for request in requests
            ]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["exploration_exercises"], [])
            for supported_area in (
                "가슴·어깨·삼두 운동",
                "등·허리 운동",
                "이두 운동",
                "하체 운동",
                "전완·손목 운동",
                "견갑·전거근 운동",
                "코어 보조 운동",
                "복근 운동",
                "복사근 운동",
            ):
                self.assertIn(supported_area, response.json()["reply"])


    def test_chat_rejects_blank_messages_and_non_user_final_message(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            blank = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "  "}]},
            )
            assistant_last = client.post(
                "/api/chat",
                json={"messages": [{"role": "assistant", "content": "hello"}]},
            )

        self.assertEqual(blank.status_code, 422)
        self.assertEqual(assistant_last.status_code, 422)

    def test_chat_reports_missing_configuration(self) -> None:
        app = create_app(
            settings=Settings(
                _env_file=None,
                openrouter_api_key=None,
                openrouter_model=None,
            )
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENROUTER_API_KEY", response.json()["detail"])

    def test_chat_hides_provider_error_details(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FailingCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "PushDay 추천"}]},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "The LLM provider request failed.")

    def test_hypertrophy_routine_returns_sourced_volume_and_progression_without_kg(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{
                    "role": "user",
                    "content": "PushDay, 근비대 목표, 초보자, 만 18세 이상 성인, 덤벨, 주 2회, 회당 30분, 선호 없음, 제약 없음.",
                }],
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        routine = body["state"]["routine"]
        prescription = routine["hypertrophy_prescription"]
        self.assertIsNotNone(prescription)
        self.assertTrue(prescription["weekly_direct_sets"])
        self.assertTrue(
            all(
                target["sets_per_week"] == 4
                and target["basis"] == "source_starting_point"
                for target in prescription["weekly_direct_sets"]
            )
        )
        self.assertEqual(prescription["repetition_range_rm"], [6, 12])
        self.assertEqual(prescription["rest_seconds_range"], [60, 120])
        self.assertEqual(
            (
                prescription["progression"]["extra_repetitions_min"],
                prescription["progression"]["extra_repetitions_max"],
                prescription["progression"]["load_increase_percent_min"],
                prescription["progression"]["load_increase_percent_max"],
            ),
            (1, 2, 2, 10),
        )
        self.assertIn("개인별 절대 중량은 계산하거나 추천하지 않습니다", prescription["progression"]["instruction"])
        source_ids = {source["id"] for source in prescription["sources"]}
        self.assertEqual(
            source_ids,
            {
                "acsm_2026_overview",
                "acsm_2009_progression",
                "iversen_2021_time_efficiency",
            },
        )
        self.assertTrue(
            all("hypertrophy_prescription" not in exercise for exercise in body["exploration_exercises"])
        )

    def test_hypertrophy_waits_for_adult_scope_confirmation(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "PushDay, 근비대 목표, 초보자, 덤벨, 주 2회, 시간 건너뛰기, 선호 없음, 제약 없음.",
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["state"]["routine"])
        self.assertEqual(body["state"]["context"]["adult_eligibility"]["status"], "not_asked")
        self.assertIn("만 18세 이상인가요", body["reply"])

    def test_experienced_hypertrophy_asks_for_recent_muscle_volume(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{
                    "role": "user",
                    "content": "PushDay, 근비대 목표, 경험자, 만 18세 이상 성인, 덤벨, 주 2회, 시간 건너뛰기, 선호 없음, 제약 없음.",
                }],
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["state"]["routine"])
        self.assertIn("최근 한 주의 근육별 직접 세트 수", body["reply"])
        self.assertEqual(body["exploration_exercises"], [])

    def _post_experienced_push_volume(self, sets_per_week: int):
        catalog = load_exercise_catalog()
        target_muscle_ids = next(
            day.focus_muscle_ids for day in catalog.workout_days if day.id == "push_day"
        )
        context = RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["push_day"]),
            goal=ContextField(status="provided", value="hypertrophy"),
            experience=ContextField(status="provided", value="experienced"),
            sessions_per_week=ContextField(status="provided", value=1),
            minutes_per_session=ContextField(status="skipped"),
            equipment=ContextField(
                status="provided",
                value=EquipmentIntent(mode="specified", equipment_ids=["dumbbell"]),
            ),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="provided", value=[]),
            adult_eligibility=ContextField(status="provided", value="adult"),
            weekly_direct_sets_by_muscle=ContextField(
                status="provided",
                value={muscle_id: sets_per_week for muscle_id in target_muscle_ids},
            ),
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=ContextPreservingCoachModel(),
        )
        with TestClient(app) as client:
            return self._post_confirmed_with_context(
                client,
                [
                    {
                        "role": "user",
                        "content": f"근비대 목표 경험자, 각 표적 근육 주 {sets_per_week}세트",
                    }
                ],
                context,
            )

    def test_experienced_hypertrophy_uses_only_reported_weekly_volume(self) -> None:
        response = self._post_experienced_push_volume(8)

        self.assertEqual(response.status_code, 200)
        prescription = response.json()["state"]["routine"]["hypertrophy_prescription"]
        self.assertTrue(prescription["weekly_direct_sets"])
        self.assertTrue(
            all(
                target["sets_per_week"] == 8 and target["basis"] == "user_reported"
                for target in prescription["weekly_direct_sets"]
            )
        )

    def test_experienced_hypertrophy_preserves_reported_zero_sets(self) -> None:
        response = self._post_experienced_push_volume(0)

        self.assertEqual(response.status_code, 200)
        prescription = response.json()["state"]["routine"]["hypertrophy_prescription"]
        self.assertTrue(prescription["weekly_direct_sets"])
        self.assertTrue(
            all(
                target["sets_per_week"] == 0 and target["basis"] == "user_reported"
                for target in prescription["weekly_direct_sets"]
            )
        )

    def test_minor_hypertrophy_routine_has_no_general_prescription(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [{
                    "role": "user",
                    "content": "PushDay, 근비대 목표, 초보자, 미성년자입니다, 덤벨, 주 2회, 시간 건너뛰기, 선호 없음, 제약 없음.",
                }],
            )

        self.assertEqual(response.status_code, 200)
        routine = response.json()["state"]["routine"]
        self.assertIsNone(routine["hypertrophy_prescription"])
        self.assertIn("근거 적용 범위 밖", routine["prescription_note"])

    def test_general_chat_stays_general_until_a_routine_is_requested(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            question = client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "근비대랑 근력의 차이가 뭐야?"}],
                    "state": ConversationState(mode="general").model_dump(mode="json"),
                },
            ).json()
            start = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "근비대랑 근력의 차이가 뭐야?"},
                        {"role": "assistant", "content": question["reply"]},
                        {"role": "user", "content": "근비대 운동 루틴 추천해줘"},
                    ],
                    "state": question["state"],
                },
            )

        self.assertEqual(question["state"]["mode"], "general")
        self.assertIn("근육 크기 증가", question["reply"])
        self.assertNotIn("운동 부위를 알려주세요", question["reply"])
        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.json()["state"]["mode"], "routine")
        self.assertIn("운동 부위", start.json()["reply"])
        self.assertNotIn("에이전트", start.json()["reply"])

    def test_one_turn_records_multiple_user_provided_routine_facts(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [{
                        "role": "user",
                        "content": "푸시 데이, 초보자, 주 4회, 45분, 덤벨, 선호 없음, 제약 없음",
                    }],
                    "state": ConversationState(mode="routine").model_dump(mode="json"),
                },
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["state"]["context"]["workout_day_ids"], {
            "status": "provided", "value": ["push_day"]
        })
        self.assertEqual(body["state"]["context"]["experience"], {
            "status": "provided", "value": "novice"
        })
        self.assertEqual(body["state"]["context"]["sessions_per_week"], {
            "status": "provided", "value": 4
        })
        self.assertEqual(body["state"]["context"]["minutes_per_session"], {
            "status": "provided", "value": 45
        })
        self.assertIn("목표", body["reply"])


    def test_assistant_split_must_be_confirmed_before_drafting(self) -> None:
        context = RoutineContext(
            workout_day_ids=ContextField(
                status="provided", value=["push_day", "legs_day"]
            ),
            workout_split_type=ContextField(status="provided", value="ab"),
            workout_split_assignment=ContextField(status="delegated"),
            goal=ContextField(status="skipped"),
            experience=ContextField(status="skipped"),
            sessions_per_week=ContextField(status="provided", value=4),
            minutes_per_session=ContextField(status="skipped"),
            equipment=ContextField(status="skipped"),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="provided", value=[]),
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            proposal_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "주 4회 2분할, 가슴·어깨·삼두와 하체 부위로, 분할 구성을 맡길게요.",
                        }
                    ],
                    "state": ConversationState(context=context).model_dump(mode="json"),
                    "action": "message",
                },
            )
            proposal = proposal_response.json()
            self.assertEqual(proposal_response.status_code, 200)
            self.assertEqual(proposal["state"]["phase"], "confirming_split")
            self.assertIsNone(proposal["state"]["routine"])
            self.assertIn("A: 가슴·어깨·삼두 운동", proposal["reply"])
            self.assertIn("B: 하체 운동", proposal["reply"])
            self.assertEqual(
                set(proposal["quick_replies"][0]), {"label", "message"}
            )
            self.assertEqual(
                proposal["state"]["context"]["sessions_per_week"]["value"], 4
            )
            self.assertEqual(
                proposal["state"]["context"]["workout_split_assignment"]["status"],
                "delegated",
            )

            confirmed_split_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "이 A/B 분할을 확인합니다."}
                    ],
                    "state": proposal["state"],
                    "action": "message",
                },
            )
            confirmed_split = confirmed_split_response.json()
            self.assertEqual(confirmed_split["state"]["phase"], "confirming_context")
            self.assertIsNone(confirmed_split["state"]["routine"])
            self.assertIn("A: 가슴·어깨·삼두 운동", confirmed_split["reply"])
            self.assertIn("B: 하체 운동", confirmed_split["reply"])

            routine_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "확인하고 루틴 만들기"}
                    ],
                    "state": confirmed_split["state"],
                    "action": "confirm_context",
                },
            )

        self.assertEqual(routine_response.status_code, 200)
        routine = routine_response.json()["state"]["routine"]
        self.assertEqual(routine["sessions_per_week"], 4)
        self.assertEqual(
            [session["workout_day_id"] for session in routine["sessions"]],
            ["push_day", "legs_day", "push_day", "legs_day"],
        )

    def test_experienced_set_reports_are_staged_and_never_filled_in(self) -> None:
        context = RoutineContext(
            workout_day_ids=ContextField(
                status="provided", value=["push_day", "legs_day"]
            ),
            goal=ContextField(status="provided", value="hypertrophy"),
            experience=ContextField(status="provided", value="experienced"),
            sessions_per_week=ContextField(status="provided", value=4),
            minutes_per_session=ContextField(status="skipped"),
            equipment=ContextField(status="skipped"),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="provided", value=[]),
            adult_eligibility=ContextField(status="provided", value="adult"),
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            first_stage_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "경험자 맞춤 정보를 알려드릴게요."}
                    ],
                    "state": ConversationState(context=context).model_dump(mode="json"),
                    "action": "message",
                },
            )
            first_stage = first_stage_response.json()
            self.assertIn("이번 단계: 가슴, 삼각근, 삼두근", first_stage["reply"])
            why_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "왜 이 정보가 필요해요? 부담스러워요."}
                    ],
                    "state": first_stage["state"],
                    "action": "message",
                },
            )
            why_body = why_response.json()
            self.assertIn("현재 보고", why_body["reply"])
            self.assertIn("건너뛸 수", why_body["reply"])
            self.assertNotIn("이번 단계: 가슴, 삼각근, 삼두근", why_body["reply"])
            self.assertEqual(
                why_body["state"]["context"]["weekly_direct_sets_by_muscle"]["status"],
                "not_asked",
            )


            second_stage_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "가슴 8세트, 삼각근 6세트, 삼두근 4세트.",
                        }
                    ],
                    "state": why_body["state"],
                    "action": "message",
                },
            )
            second_stage = second_stage_response.json()
            reported = second_stage["state"]["context"]["weekly_direct_sets_by_muscle"]["value"]
            self.assertEqual(
                reported,
                {"chest": 8, "deltoids": 6, "triceps": 4},
            )
            self.assertEqual(
                second_stage["state"]["context"]["workout_day_ids"]["value"],
                ["push_day", "legs_day"],
            )
            self.assertIn("이번 단계: 외전근, 내전근, 발목 안정근", second_stage["reply"])

            stopped_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "세트 보고 건너뛰기"}
                    ],
                    "state": second_stage["state"],
                    "action": "message",
                },
            )
            stopped = stopped_response.json()

        self.assertEqual(stopped_response.status_code, 200)
        self.assertEqual(
            stopped["state"]["context"]["weekly_direct_sets_by_muscle"]["value"],
            {"chest": 8, "deltoids": 6, "triceps": 4},
        )
        self.assertEqual(
            stopped["state"]["context"]["weekly_direct_sets_follow_up"]["status"],
            "skipped",
        )

    def test_time_ranges_require_a_user_selected_target_and_venues_do_not_set_equipment(
        self,
    ) -> None:
        base_context = RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["push_day"]),
            goal=ContextField(status="skipped"),
            experience=ContextField(status="skipped"),
            sessions_per_week=ContextField(status="provided", value=3),
            equipment=ContextField(status="skipped"),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="provided", value=[]),
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            range_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "회당 30분~1시간 가능해요."}
                    ],
                    "state": ConversationState(context=base_context).model_dump(mode="json"),
                    "action": "message",
                },
            )
            range_body = range_response.json()
            self.assertEqual(range_response.status_code, 200)
            self.assertIn("목표 시간 하나", range_body["reply"])
            self.assertIn("중간값을 대신 선택하지 않습니다", range_body["reply"])
            self.assertEqual(
                range_body["state"]["context"]["minutes_per_session"]["status"],
                "unknown",
            )
            self.assertEqual(
                range_body["state"]["context"]["minutes_per_session"]["value"], None
            )
            self.assertEqual(
                range_body["state"]["context"]["minutes_per_session_range"]["value"],
                {"minimum_minutes": 30, "maximum_minutes": 60},
            )

            target_response = client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "45분으로 정할게요."}],
                    "state": range_body["state"],
                    "action": "message",
                },
            )
            self.assertEqual(
                target_response.json()["state"]["context"]["minutes_per_session"]["value"],
                45,
            )

            venue_context = base_context.model_copy(
                update={
                    "minutes_per_session": ContextField(status="skipped"),
                    "equipment": ContextField(status="unknown"),
                }
            )
            venue_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "자양동 휘트니스 캐리스타"}
                    ],
                    "state": ConversationState(context=venue_context).model_dump(mode="json"),
                    "action": "message",
                },
            )
            venue = venue_response.json()

        self.assertEqual(venue_response.status_code, 200)
        self.assertIn("장소 이름", venue["reply"])
        self.assertIn("장비를 추측하지 않겠습니다", venue["reply"])
        self.assertEqual(venue["state"]["context"]["equipment"]["status"], "unknown")
        self.assertIsNone(venue["state"]["context"]["equipment"]["value"])

    def test_legacy_push_day_alias_keeps_id_and_uses_korean_display_label(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = self._post_confirmed_routine(
                client,
                [
                    {
                        "role": "user",
                        "content": "푸시데이 운동을 덤벨로 추천해줘. 목표 건너, 경력 건너.",
                    }
                ],
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        session = body["state"]["routine"]["sessions"][0]
        self.assertEqual(session["workout_day_id"], "push_day")
        self.assertEqual(session["workout_day_name_ko"], "가슴·어깨·삼두 운동")
        self.assertEqual(body["quick_replies"], [])

    def test_sessions_per_week_quick_replies_select_normal_answers_and_keep_opt_outs(
        self,
    ) -> None:
        context = RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["push_day"])
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            prompt_response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "운동 계획을 세우고 싶어요."}
                    ],
                    "state": ConversationState(context=context).model_dump(mode="json"),
                    "action": "message",
                },
            )
            prompt = prompt_response.json()
            expected_choices = [
                {"label": f"주 {frequency}회", "message": f"주 {frequency}회"}
                for frequency in range(1, 8)
            ]
            self.assertEqual(prompt_response.status_code, 200)
            self.assertIn("주당 운동 횟수", prompt["reply"])
            self.assertEqual(prompt["quick_replies"], expected_choices)

            chosen = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": prompt["quick_replies"][3]["message"]}
                    ],
                    "state": prompt["state"],
                    "action": "message",
                },
            )
            chosen_body = chosen.json()
            self.assertEqual(chosen.status_code, 200)
            self.assertEqual(
                chosen_body["state"]["context"]["sessions_per_week"],
                {"status": "provided", "value": 4},
            )
            self.assertIn("우선할 목표", chosen_body["reply"])
            self.assertIsNone(chosen_body["state"]["routine"])

            unknown = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "주당 횟수를 모르겠어요."}
                    ],
                    "state": prompt["state"],
                    "action": "message",
                },
            ).json()
            self.assertEqual(
                unknown["state"]["context"]["sessions_per_week"]["status"],
                "unknown",
            )
            self.assertEqual(unknown["quick_replies"], expected_choices)

            skipped = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "주당 횟수 건너뛰기"}
                    ],
                    "state": prompt["state"],
                    "action": "message",
                },
            ).json()
            self.assertEqual(
                skipped["state"]["context"]["sessions_per_week"]["status"],
                "skipped",
            )
            self.assertEqual(skipped["quick_replies"], [])

    def test_side_question_preserves_pending_context_and_resumes_on_a_later_answer(self) -> None:
        context = RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["abs_day"])
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )

        with TestClient(app) as client:
            question = client.post(
                "/api/chat",
                json={
                    "messages": [{
                        "role": "user",
                        "content": "근비대와 근력의 차이가 뭐예요?",
                    }],
                    "state": ConversationState(mode="routine", context=context).model_dump(mode="json"),
                },
            ).json()
            answer = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "근비대와 근력의 차이가 뭐예요?"},
                        {"role": "assistant", "content": question["reply"]},
                        {"role": "user", "content": "주 4회"},
                    ],
                    "state": question["state"],
                },
            )

        body = answer.json()
        self.assertIn("근육 크기 증가", question["reply"])
        self.assertNotIn("주당 운동 횟수", question["reply"])
        self.assertEqual(question["state"]["context"], context.model_dump(mode="json"))
        self.assertEqual(question["quick_replies"], [])
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(body["state"]["context"]["sessions_per_week"], {
            "status": "provided", "value": 4
        })
        self.assertIn("우선할 목표", body["reply"])

    def test_delegated_workout_area_is_proposed_and_only_saved_after_acceptance(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            proposed = client.post(
                "/api/chat",
                json={
                    "messages": [{
                        "role": "user",
                        "content": "운동 부위는 잘 모르겠어. 추천해줘.",
                    }],
                    "state": ConversationState(mode="routine").model_dump(mode="json"),
                },
            ).json()
            recommendation = proposed["state"]["workout_day_recommendation"]
            accepted = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "운동 부위는 잘 모르겠어. 추천해줘."},
                        {"role": "assistant", "content": proposed["reply"]},
                        {"role": "user", "content": "추천한 운동 부위로 진행해줘"},
                    ],
                    "state": proposed["state"],
                },
            )

        body = accepted.json()
        self.assertEqual(proposed["state"]["context"]["workout_day_ids"]["status"], "delegated")
        self.assertTrue(recommendation["workout_day_ids"])
        self.assertIn("제안해요", proposed["reply"])
        self.assertNotIn("에이전트", proposed["reply"])
        self.assertEqual(len(proposed["quick_replies"]), 3)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(body["state"]["context"]["workout_day_ids"], {
            "status": "provided", "value": recommendation["workout_day_ids"]
        })
        self.assertIsNone(body["state"]["workout_day_recommendation"])
        self.assertIn("주당 운동 횟수", body["reply"])

    def test_safety_clarification_blocks_recommendation_call(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [{
                        "role": "user",
                        "content": "무릎이 아파요. 운동 부위는 추천해줘.",
                    }],
                    "state": ConversationState(mode="routine").model_dump(mode="json"),
                },
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("통증 위치", body["reply"])
        self.assertIsNone(body["state"]["workout_day_recommendation"])

    def test_cancelling_routine_returns_to_general_conversation(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "루틴 취소할게"}],
                    "state": ConversationState(mode="routine").model_dump(mode="json"),
                },
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["state"]["mode"], "general")
        self.assertIn("멈출게요", body["reply"])
        self.assertNotIn("에이전트", body["reply"])

    def test_unknown_client_split_id_returns_safe_clarification(self) -> None:
        context = RoutineContext(
            workout_day_ids=ContextField(
                status="provided", value=["push_day", "legs_day"]
            ),
            workout_split_type=ContextField(status="provided", value="ab"),
            workout_split_assignment=ContextField(status="delegated"),
            split_template=WorkoutSplitTemplate(
                day_a_ids=["unknown_day"],
                day_b_ids=["legs_day"],
                confirmation_status="confirmed",
            ),
            goal=ContextField(status="skipped"),
            experience=ContextField(status="skipped"),
            sessions_per_week=ContextField(status="provided", value=4),
            minutes_per_session=ContextField(status="skipped"),
            equipment=ContextField(status="skipped"),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="provided", value=[]),
        )
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=ContextPreservingCoachModel(),
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "확인하고 루틴 만들기"}
                    ],
                    "state": ConversationState(
                        phase="confirming_context", context=context
                    ).model_dump(mode="json"),
                    "action": "confirm_context",
                },
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(body["state"]["routine"])
        self.assertIn("지원되지 않거나 선택 부위와 맞지 않는", body["reply"])
        self.assertIn("가슴·어깨·삼두 운동", body["reply"])
        self.assertIsNone(body["state"]["context"]["split_template"])
        self.assertEqual(body["quick_replies"][0]["label"], "다시 제안받기")
