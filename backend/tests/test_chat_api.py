import re
import unittest
from collections.abc import Sequence

from fastapi.testclient import TestClient

from yee_doowang_api.application.chat import (
    ChatCompletionError,
    ContextField,
    ConversationMessage,
    ConversationState,
    EquipmentIntent,
    IntentDecision,
    PlannedExercise,
    PlannedSession,
    RoutineContext,
    RoutineProposal,
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
    ) -> tuple[RoutineContext, str]:
        updates: dict[str, ContextField] = {}
        message = ""
        text = transcript.lower()
        latest = (latest_user_message or transcript).lower()

        def field_text(terms: tuple[str, ...]) -> str:
            return latest if any(term in latest for term in terms) else text

        area_terms = {
            "push_day": ("push", "가슴", "삼두", "어깨", "위팔세갈래근"),
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
        workout_terms = tuple(
            term for terms in area_terms.values() for term in terms
        )
        workout_text = field_text((*workout_terms, *unsupported_terms))
        selected_days = [
            day.id
            for day in workout_days
            if any(term in workout_text for term in area_terms.get(day.id, ()))
        ]
        if selected_days:
            updates["workout_day_ids"] = cls._field(list(dict.fromkeys(selected_days)))
        elif any(term in workout_text for term in unsupported_terms):
            updates["workout_day_ids"] = cls._field(status="unknown")
            message = "요청한 운동 부위는 아직 지원하지 않습니다."

        goal_text = field_text(
            ("근비대", "근육 증가", "근력", "목표 건너", "목표는 상관없", "감량", "지구력", "일반 체력", "목표 모르")
        )
        has_hypertrophy = any(term in goal_text for term in ("근비대", "근육 증가"))
        has_strength = "근력" in goal_text
        if any(term in goal_text for term in ("목표 건너", "목표는 상관없")):
            updates["goal"] = cls._field(status="skipped")
        elif "목표 모르" in goal_text or (has_hypertrophy and has_strength):
            updates["goal"] = cls._field(status="unknown")
        elif has_hypertrophy:
            updates["goal"] = cls._field("hypertrophy")
        elif has_strength:
            updates["goal"] = cls._field("strength")
        elif any(term in goal_text for term in ("감량", "지구력", "일반 체력")):
            updates["goal"] = cls._field("other")

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
        if any(term in latest for term in ("횟수 건너", "빈도 건너")):
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

        time_text = field_text(("분", "시간", "시간 건너", "시간은 상관", "시간을 모르"))
        if any(term in latest for term in ("시간 건너", "시간 조건 건너", "회당 시간 건너", "시간은 상관없")):
            updates["minutes_per_session"] = cls._field(status="skipped")
        elif any(term in latest for term in ("시간을 모르", "시간은 모르")):
            updates["minutes_per_session"] = cls._field(status="unknown")
        else:
            minute_matches = list(re.finditer(r"([1-9][0-9]*)\s*분", text))
            minutes = re.search(r"([1-9][0-9]*)\s*분", latest)
            if minutes is None and minute_matches:
                minutes = minute_matches[-1]
            if minutes:
                updates["minutes_per_session"] = cls._field(int(minutes.group(1)))
            elif any(term in time_text for term in ("시간 건너", "시간 조건 건너", "회당 시간 건너", "시간은 상관없")):
                updates["minutes_per_session"] = cls._field(status="skipped")
            elif "시간을 모르" in time_text:
                updates["minutes_per_session"] = cls._field(status="unknown")
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
            updates["preferences"] = cls._field(["사용자 선호"])

        constraints_text = field_text(("제약", "제한", "불편함", "부상"))
        if any(term in constraints_text for term in ("제약 없음", "제한 없음", "불편함 없음")):
            updates["known_constraints"] = cls._field([])
        elif any(term in constraints_text for term in ("제약 건너", "제약은 상관없")):
            updates["known_constraints"] = cls._field(status="skipped")

        context_data = current.model_dump()
        context_data.update({key: value.model_dump() for key, value in updates.items()})
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

    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        current_context: RoutineContext,
        _equipment_options: Sequence[Equipment],
        workout_days: Sequence[WorkoutDay],
        _muscle_options: Sequence[Muscle],
    ) -> IntentDecision:
        user_messages = [message.content.lower() for message in messages if message.role == "user"]
        transcript = " ".join(user_messages)
        latest_user_message = user_messages[-1] if user_messages else ""
        safety_status, safety_message = self._safety(transcript)
        context, context_message = self._context(
            transcript,
            current_context,
            workout_days,
            latest_user_message,
        )
        return IntentDecision(
            context=context,
            safety_status=safety_status,
            message=safety_message or context_message,
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
        sessions = []
        for index in range(session_count):
            day_id = day_ids[index % len(day_ids)]
            candidates = candidates_by_day[day_id]
            selected = candidates[0]
            sessions.append(
                PlannedSession(
                    workout_day_id=day_id,
                    exercises=[
                        PlannedExercise(
                            source_id=selected.source_id,
                            rationale="선택된 부위와 근거 기반 순위를 반영했어요.",
                            alternative_source_ids=[
                                item.source_id for item in candidates[1:3]
                            ],
                        )
                    ],
                )
            )
        return RoutineProposal(sessions=sessions)


class FailingCoachModel:
    async def interpret(
        self,
        _messages: Sequence[ConversationMessage],
        _current_context: RoutineContext,
        _equipment_options: Sequence[Equipment],
        _workout_days: Sequence[WorkoutDay],
        _muscles: Sequence[Muscle],
    ) -> IntentDecision:
        raise ChatCompletionError("provider detail must not reach the caller")

    async def plan_routine(self, *_args: object, **_kwargs: object) -> RoutineProposal:
        raise AssertionError("routine planning must not run after interpretation fails")


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
        catalog = load_exercise_catalog()
        user_messages = [message["content"] for message in conversation if message["role"] == "user"]
        transcript = " ".join(user_messages)
        context, _ = FixtureCoachModel._context(
            transcript,
            RoutineContext(),
            catalog.workout_days,
            user_messages[-1] if user_messages else "",
        )
        state = ConversationState(phase="confirming_context", context=context)
        return client.post(
            "/api/chat",
            json={
                "messages": [*conversation, {"role": "user", "content": "확인하고 루틴 만들기"}],
                "state": state.model_dump(mode="json"),
                "action": "confirm_context",
            },
        )

    def test_context_must_be_confirmed_and_schedule_edits_change_the_draft(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay, 근비대 목표, 초보자, 덤벨, 주 2회, 회당 30분, 선호 없음, 제약 없음.",
            }
        ]

        with TestClient(app) as client:
            review = client.post("/api/chat", json={"messages": messages})
            self.assertEqual(review.status_code, 200)
            reviewed = review.json()
            self.assertEqual(reviewed["state"]["phase"], "confirming_context")
            self.assertIsNone(reviewed["state"]["routine"])
            self.assertEqual(reviewed["exercises"], [])
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
        candidate_ids = {item["source_id"] for item in body["exercises"]}
        self.assertTrue(planned_ids)
        self.assertLessEqual(planned_ids, candidate_ids)
        self.assertNotIn("sets", routine["sessions"][0]["exercises"][0])


    def test_safety_signal_on_confirmation_still_blocks_routine(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {
                "role": "user",
                "content": "PushDay, 근비대 목표, 초보자, 덤벨, 주 2회, 회당 시간 건너뛰기, 선호 없음, 제약 없음.",
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
        self.assertEqual(response.json()["exercises"], [])
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
                                    rationale="잘못된 후보",
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
        self.assertEqual(response.json()["exercises"], [])
        self.assertIn("주당 횟수를 건너뛰어서", response.json()["reply"])

    def test_partial_interpretation_preserves_confirmed_context(self) -> None:
        class PartialUpdateCoach(FixtureCoachModel):
            async def interpret(
                self,
                _messages: Sequence[ConversationMessage],
                _current_context: RoutineContext,
                _equipment_options: Sequence[Equipment],
                _workout_days: Sequence[WorkoutDay],
                _muscles: Sequence[Muscle],
            ) -> IntentDecision:
                return IntentDecision(
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
                            "content": "PushDay, 근비대 목표, 운동 경력은 모르겠어요, 덤벨, 주 2회, 선호 없음, 제약 없음.",
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"]["context"]["experience"]["status"], "unknown")
        self.assertEqual(response.json()["state"]["phase"], "collecting_context")
        self.assertIsNone(response.json()["state"]["routine"])
        self.assertIn("모르거나 답하고 싶지 않으면", response.json()["reply"])

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
        recommendations = {item["source_id"]: item for item in body["exercises"]}
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
        self.assertEqual(response.json()["exercises"], [])
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
            "0334", {item["source_id"] for item in response.json()["exercises"]}
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
        self.assertEqual(response.json()["exercises"], [])
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
            item["source_id"]: item for item in response.json()["exercises"]
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
            {exercise["source_id"] for exercise in body["exercises"]},
            expected_ids,
        )
        kickback = next(
            exercise
            for exercise in body["exercises"]
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

        for response in responses:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(responses[0].json()["exercises"][0]["source_id"], "0178")
        self.assertEqual(responses[1].json()["exercises"][0]["source_id"], "0025")

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
        source_ids = [item["source_id"] for item in response.json()["exercises"]]
        self.assertEqual(source_ids[0], "0334")
        self.assertLess(source_ids.index("0333"), source_ids.index("0355"))

    def test_missing_conflicting_and_unsupported_contexts_ask_instead_of_guessing(
        self,
    ) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        requests = (
            "PushDay 덤벨 추천해줘.",
            "PushDay 근비대와 근력 목표 둘 다, 초보자, 덤벨 추천해줘.",
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
            all(response.json()["exercises"] == [] for response in responses)
        )
        self.assertIn("근비대와 근력", responses[0].json()["reply"])
        self.assertIn("근비대와 근력", responses[1].json()["reply"])
        self.assertIn("근력 진행", responses[2].json()["reply"])
        self.assertIn("복귀", responses[3].json()["reply"])

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
        expected_ids = {
            exercise.source_id
            for exercise in catalog.exercises
            if exercise.primary_muscle_id in {"abs", "lower_abs"}
            and exercise.equipment_id == "body_weight"
        }
        self.assertEqual(
            {exercise["source_id"] for exercise in response.json()["exercises"]},
            expected_ids,
        )

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
                        {exercise["source_id"] for exercise in body["exercises"]},
                        expected_ids,
                    )
                    self.assertIn(
                        source_id,
                        {exercise["source_id"] for exercise in body["exercises"]},
                    )
                    self.assertTrue(
                        all(
                            exercise["equipment_ko"] == equipment_name
                            for exercise in body["exercises"]
                        )
                    )


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
            for exercise in response.json()["exercises"]
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
            {exercise["source_id"] for exercise in response.json()["exercises"]},
            expected_ids,
        )
        self.assertTrue(
            any(
                "복사근" in exercise["secondary_muscles_ko"]
                for exercise in response.json()["exercises"]
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
        self.assertEqual(response.json()["exercises"], [])
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
        self.assertEqual(response.json()["exercises"], [])
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
        self.assertEqual(response.json()["exercises"], [])

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
            {exercise["source_id"] for exercise in body["exercises"]},
            expected_ids,
        )
        self.assertLess(len(body["exercises"]), len(catalog.exercises))
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
        for recommendation in body["exercises"]:
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
                for exercise in body["exercises"]
            )
        )
        self.assertGreater(
            len({exercise["equipment_ko"] for exercise in body["exercises"]}), 1
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
            self.assertEqual(response.json()["exercises"], [])
            for supported_area in (
                "푸시 데이",
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
