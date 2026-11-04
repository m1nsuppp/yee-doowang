import unittest
from collections.abc import Sequence

from fastapi.testclient import TestClient

from yee_doowang_api.application.chat import (
    ChatCompletionError,
    CoachAnswer,
    ConversationMessage,
    EquipmentConstraint,
    EquipmentIntent,
    IntentDecision,
    RecommendationPreferences,
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
    def _preferences(transcript: str) -> RecommendationPreferences:
        has_hypertrophy = any(term in transcript for term in ("근비대", "근육 증가"))
        has_strength = "근력" in transcript
        if has_hypertrophy and has_strength:
            goal = "unknown"
        elif has_hypertrophy:
            goal = "hypertrophy"
        elif has_strength:
            goal = "strength"
        elif any(term in transcript for term in ("목표 건너", "목표는 상관없")):
            goal = "skip"
        elif any(term in transcript for term in ("감량", "지구력", "일반 체력")):
            goal = "unsupported"
        else:
            goal = "unknown"

        if any(term in transcript for term in ("초보", "처음 시작", "복귀")):
            experience = "novice"
        elif any(term in transcript for term in ("경력 건너", "경력은 상관없")):
            experience = "skip"
        elif any(term in transcript for term in ("숙련자", "경험자")):
            experience = "experienced"
        else:
            experience = "unknown"
        return RecommendationPreferences(goal=goal, experience=experience)

    @staticmethod
    def _safety(transcript: str) -> tuple[str, str]:
        resolved_terms = ("통증은 이제 없어", "통증은 없어", "이제 안 아파", "완전히 나았")
        if any(term in transcript for term in resolved_terms):
            return "none", ""

        urgent_terms = (
            "양쪽 다리",
            "회음부",
            "소변을 보기 어렵",
            "대소변",
            "교통사고",
        )
        if any(term in transcript for term in urgent_terms):
            return "urgent", "운동을 중단하고 지금 응급 진료를 받으세요."
        pain_terms = ("통증", "아파", "아프", "엉치", "꼬리뼈", "저림", "부상")
        if any(term in transcript for term in pain_terms):
            return (
                "clarify",
                (
                    "통증 위치와 어떤 동작에서 심해지는지 알려주세요. "
                    "통증을 악화시키는 운동은 중단해 주세요."
                ),
            )
        return "none", ""

    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        _equipment_options: Sequence[Equipment],
        _workout_days: Sequence[WorkoutDay],
        muscle_options: Sequence[Muscle],
    ) -> IntentDecision:
        transcript = " ".join(
            message.content.lower() for message in messages if message.role == "user"
        )
        safety_status, safety_message = self._safety(transcript)
        personalization = self._preferences(transcript)
        if "하체" in transcript or "등 운동" in transcript or "이두" in transcript:
            return IntentDecision(
                workout_intent="unsupported",
                equipment=EquipmentIntent(mode="unknown", equipment_ids=[]),
                personalization=personalization,
                safety_status=safety_status,
                message=safety_message or "현재는 푸시 데이, 복근, 복사근 운동 추천을 지원합니다.",
            )

        if "복사근" in transcript or "옆구리" in transcript:
            workout_intent = "obliques_day"
        elif "복근" in transcript or "하복근" in transcript:
            workout_intent = "abs_day"
        elif any(
            term in transcript for term in ("push", "가슴", "삼두", "어깨")
        ) or any(
            alias.lower() in transcript
            for muscle in muscle_options
            if muscle.id in {"chest", "deltoids", "triceps"}
            for alias in muscle.aliases_ko
        ):
            workout_intent = "push_day"
        else:
            return IntentDecision(
                workout_intent="clarify",
                equipment=EquipmentIntent(mode="unknown", equipment_ids=[]),
                personalization=personalization,
                safety_status=safety_status,
                message=safety_message or "푸시 데이, 복근, 복사근 중 원하는 운동 부위를 알려주세요.",
            )

        if "알아서" in transcript or "아무거나" in transcript:
            equipment = EquipmentIntent(mode="delegate_any", equipment_ids=[])
            message = ""
        elif "맨몸" in transcript or "no equipment" in transcript:
            equipment = EquipmentIntent(mode="specified", equipment_ids=["body_weight"])
            message = ""
        elif "덤벨" in transcript:
            equipment = EquipmentIntent(mode="specified", equipment_ids=["dumbbell"])
            message = ""
        else:
            equipment = EquipmentIntent(mode="unknown", equipment_ids=[])
            message = (
                "사용할 수 있는 장비를 모르셔도 괜찮아요. ‘알아서 골라줘’라고 해주세요."
            )

        if personalization.goal == "unknown":
            message = "근비대와 근력 중 우선할 목표를 알려주세요."
        elif personalization.goal == "unsupported":
            message = "현재 근거가 있는 목표는 근비대와 근력 진행입니다."
        elif personalization.experience == "unknown":
            message = "운동을 처음 시작했거나 몇 년 쉬었다가 복귀했는지 알려주세요."
        elif personalization.experience == "experienced":
            message = "초보·복귀 운동자 외의 경력 적합도 근거는 없어요. 경력 분류를 건너뛸까요?"

        return IntentDecision(
            workout_intent=workout_intent,
            equipment=equipment,
            personalization=personalization,
            safety_status=safety_status,
            message=safety_message or message,
        )

    async def answer(
        self,
        _messages: Sequence[ConversationMessage],
        _candidates: Sequence[Exercise],
        equipment_constraint: EquipmentConstraint,
        _personalization: RecommendationPreferences,
        _recommendation_profiles: Sequence[ExerciseRecommendationProfile],
    ) -> CoachAnswer:
        if equipment_constraint.mode == "unrestricted":
            return CoachAnswer(reply="장비 조건은 제한하지 않고 후보를 모았어요.")
        return CoachAnswer(reply="조건에 맞는 운동 후보를 찾았어요.")


class FailingCoachModel:
    async def interpret(
        self,
        _messages: Sequence[ConversationMessage],
        _equipment_options: Sequence[Equipment],
        _workout_days: Sequence[WorkoutDay],
        _muscles: Sequence[Muscle],
    ) -> IntentDecision:
        raise ChatCompletionError("provider detail must not reach the caller")

    async def answer(
        self,
        _messages: Sequence[ConversationMessage],
        _candidates: Sequence[Exercise],
        _equipment_constraint: EquipmentConstraint,
        _personalization: RecommendationPreferences,
        _recommendation_profiles: Sequence[ExerciseRecommendationProfile],
    ) -> CoachAnswer:
        raise AssertionError("answer must not run after interpretation fails")


class ChatApiTests(unittest.TestCase):
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
            response = client.post("/api/chat", json={"messages": messages})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["reply"], "조건에 맞는 운동 후보를 찾았어요.")
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
            response = client.post("/api/chat", json={"messages": messages})

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "0334", {item["source_id"] for item in response.json()["exercises"]}
        )
        self.assertEqual(response.json()["reply"], "조건에 맞는 운동 후보를 찾았어요.")

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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "PushDay 근비대 목표, 경력 건너뛰고 덤벨 추천해줘.",
                        }
                    ]
                },
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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "위팔세갈래근 운동을 덤벨로 추천해줘. 근비대 목표, 초보자.",
                        }
                    ]
                },
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
                client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": content}]},
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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "PushDay 근비대 목표, 초보자, 덤벨 추천해줘.",
                        }
                    ]
                },
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
                client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": content}]},
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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "맨몸 복근 운동 추천해줘. 목표 건너뛰고 경력 건너뛰고.",
                        }
                    ]
                },
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

    def test_untranslated_catalog_labels_are_explicit(self) -> None:
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
                            "content": "복근 운동 알아서 골라줘. 근비대 목표, 경력 건너뛰고.",
                        }
                    ]
                },
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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "복사근 운동 추천해줘. 알아서 골라줘. 목표 건너뛰고 경력 건너뛰고.",
                        }
                    ]
                },
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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "복사근 운동, 근비대 목표, 초보자로 알아서 추천해줘.",
                        }
                    ]
                },
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
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "PushDay 근비대 목표, 초보자 추천해줘.",
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["reply"],
            "사용할 수 있는 장비를 모르셔도 괜찮아요. ‘알아서 골라줘’라고 해주세요.",
        )
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
            response = client.post("/api/chat", json={"messages": messages})

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

        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "하체 운동 추천해줘."}]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exercises"], [])
        self.assertIn("복근", response.json()["reply"])
        self.assertIn("복사근", response.json()["reply"])

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
