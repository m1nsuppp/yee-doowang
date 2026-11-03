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
from yee_doowang_api.application.exercise_catalog import Equipment, Exercise
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog
from yee_doowang_api.main import create_app
from yee_doowang_api.settings import Settings


class FixtureCoachModel:
    async def interpret(
        self,
        messages: Sequence[ConversationMessage],
        _equipment_options: Sequence[Equipment],
    ) -> IntentDecision:
        transcript = " ".join(
            message.content.lower() for message in messages if message.role == "user"
        )
        if "하체" in transcript:
            return IntentDecision(
                workout_intent="unsupported",
                equipment=EquipmentIntent(mode="unknown", equipment_ids=[]),
                message="현재는 PushDay 운동 후보 추천만 지원합니다.",
            )
        if "알아서" in transcript or "아무거나" in transcript:
            return IntentDecision(
                workout_intent="push_day",
                equipment=EquipmentIntent(mode="delegate_any", equipment_ids=[]),
                message="",
            )
        if "맨몸" in transcript or "no equipment" in transcript:
            return IntentDecision(
                workout_intent="push_day",
                equipment=EquipmentIntent(
                    mode="specified",
                    equipment_ids=["body_weight"],
                ),
                message="",
            )
        if "덤벨" in transcript:
            return IntentDecision(
                workout_intent="push_day",
                equipment=EquipmentIntent(
                    mode="specified",
                    equipment_ids=["dumbbell"],
                ),
                message="",
            )
        return IntentDecision(
            workout_intent="push_day",
            equipment=EquipmentIntent(mode="unknown", equipment_ids=[]),
            message="사용할 수 있는 장비를 모르셔도 괜찮아요. ‘알아서 골라줘’라고 해주세요.",
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
        self.assertEqual(
            {exercise["source_id"] for exercise in body["exercises"]},
            {"0259", "0662"},
        )
        self.assertTrue(
            all(exercise["equipment_ko"] == "맨몸" for exercise in body["exercises"])
        )

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
        equipment_names = {exercise["equipment_ko"] for exercise in body["exercises"]}
        self.assertGreater(len(equipment_names), 1)
        self.assertEqual(
            {exercise["source_id"] for exercise in body["exercises"]},
            {exercise.source_id for exercise in load_exercise_catalog().exercises},
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
        self.assertIn("PushDay", response.json()["reply"])

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
