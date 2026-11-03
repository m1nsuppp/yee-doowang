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
)
from yee_doowang_api.application.exercise_catalog import (
    Equipment,
    Exercise,
    Muscle,
    WorkoutDay,
)
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog
from yee_doowang_api.main import create_app
from yee_doowang_api.settings import Settings


class FixtureCoachModel:
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
        if "하체" in transcript or "등 운동" in transcript or "이두" in transcript:
            return IntentDecision(
                workout_intent="unsupported",
                equipment=EquipmentIntent(mode="unknown", equipment_ids=[]),
                message="현재는 푸시 데이, 복근, 복사근 운동 추천을 지원합니다.",
            )

        if "복사근" in transcript or "옆구리" in transcript:
            workout_intent = "obliques_day"
        elif "복근" in transcript or "하복근" in transcript:
            workout_intent = "abs_day"
        elif any(term in transcript for term in ("push", "가슴", "삼두", "어깨")) or any(
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
                message="푸시 데이, 복근, 복사근 중 원하는 운동 부위를 알려주세요.",
            )

        if "알아서" in transcript or "아무거나" in transcript:
            equipment = EquipmentIntent(mode="delegate_any", equipment_ids=[])
        elif "맨몸" in transcript or "no equipment" in transcript:
            equipment = EquipmentIntent(
                mode="specified",
                equipment_ids=["body_weight"],
            )
        elif "덤벨" in transcript:
            equipment = EquipmentIntent(
                mode="specified",
                equipment_ids=["dumbbell"],
            )
        else:
            return IntentDecision(
                workout_intent=workout_intent,
                equipment=EquipmentIntent(mode="unknown", equipment_ids=[]),
                message="사용할 수 있는 장비를 모르셔도 괜찮아요. ‘알아서 골라줘’라고 해주세요.",
            )

        return IntentDecision(
            workout_intent=workout_intent,
            equipment=equipment,
            message="",
        )

    async def answer(
        self,
        _messages: Sequence[ConversationMessage],
        _candidates: Sequence[Exercise],
        equipment_constraint: EquipmentConstraint,
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
    ) -> CoachAnswer:
        raise AssertionError("answer must not run after interpretation fails")


class ChatApiTests(unittest.TestCase):
    def test_followup_context_returns_only_pyrewire_candidates(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            coach_model=FixtureCoachModel(),
        )
        messages = [
            {"role": "user", "content": "PushDay 운동 추천해줘."},
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
                            "content": "위팔세갈래근 운동을 덤벨로 추천해줘.",
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
                        {"role": "user", "content": "맨몸 복근 운동 추천해줘."}
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
                        {"role": "user", "content": "복근 운동 알아서 골라줘."}
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
                            "content": "복사근 운동 추천해줘. 알아서 골라줘.",
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
                json={"messages": [{"role": "user", "content": "PushDay 추천해줘."}]},
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
            {"role": "user", "content": "PushDay 운동 추천해줘."},
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
