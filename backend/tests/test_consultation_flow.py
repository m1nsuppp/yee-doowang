import unittest

from fastapi.testclient import TestClient
from test_chat_api import FixtureCoachModel

from yee_doowang_api.application.chat_models import (
    CoachTurn,
    ContextField,
    ConversationState,
    RoutineContext,
    SessionTimeRange,
    WorkoutSplitTemplate,
)
from yee_doowang_api.main import create_app
from yee_doowang_api.settings import Settings


class ConsultationCoach(FixtureCoachModel):
    """Deterministic semantic turns; routine selection uses the catalog fixture."""

    async def interpret(self, messages, current_context, *_args):
        text = messages[-1].content
        context = RoutineContext()
        action = "continue_intake"
        answer = ""
        if text == "1~2시간":
            context = RoutineContext(
                minutes_per_session_range=ContextField(
                    status="provided",
                    value=SessionTimeRange(minimum_minutes=60, maximum_minutes=120),
                ),
                # A provider may try to select the midpoint despite the policy.
                minutes_per_session=ContextField(status="provided", value=90),
            )
        elif text == "왜 하나를 골라야 해? 범위로 해줘":
            action = "explain_intake"
            answer = "범위 그대로 반영해서 지금 루틴을 만들게요."
        elif text.startswith("시간 조건") and "건너뛸게요" in text:
            context = RoutineContext(minutes_per_session=ContextField(status="skipped"))
        elif text == "90분으로 정할게요.":
            context = RoutineContext(minutes_per_session=ContextField(status="provided", value=90))
        elif text == "근력으로 바꿀게. 근비대랑 차이는 뭐야?":
            action = "answer_only"
            context = RoutineContext(goal=ContextField(status="provided", value="strength"))
            answer = "근력은 힘을 내는 능력, 근비대는 근육 크기의 증가를 목표로 해요."
        elif text == "왜 아직 질문하는 거야?":
            action = "explain_intake"
        return CoachTurn(
            context=context,
            safety_status="none",
            message="",
            conversation_action=action,
            training_answer=answer,
        )


class ConsultationFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(
            settings=Settings(_env_file=None), coach_model=ConsultationCoach(),
        ))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.state = ConversationState(context=RoutineContext(
            workout_day_ids=ContextField(status="provided", value=["push_day", "legs_day"]),
            workout_split_type=ContextField(status="provided", value="ab"),
            workout_split_assignment=ContextField(
                status="provided",
                value=WorkoutSplitTemplate(day_a_ids=["push_day"], day_b_ids=["legs_day"]),
            ),
            sessions_per_week=ContextField(status="provided", value=4),
            goal=ContextField(status="skipped"),
            experience=ContextField(status="skipped"),
            equipment=ContextField(status="skipped"),
            preferences=ContextField(status="provided", value=[]),
            known_constraints=ContextField(status="provided", value=[]),
        )).model_dump(mode="json")
        self.messages = []

    def send(self, text, action="message"):
        self.messages.append({"role": "user", "content": text})
        response = self.client.post("/api/chat", json={
            "messages": self.messages[-30:], "state": self.state, "action": action,
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.state = body["state"]
        self.messages.append({"role": "assistant", "content": body["reply"]})
        return body

    def test_objection_acknowledgment_and_routine_request_keep_recorded_range(self) -> None:
        initial = self.send("1~2시간")
        objection = self.send("왜 하나를 골라야 해? 범위로 해줘")
        acknowledgment = self.send("ㅇㅇ")
        request = self.send("루틴 만들어줘")
        for body in (initial, objection, acknowledgment, request):
            with self.subTest(reply=body["reply"]):
                self.assertEqual(body["state"]["context"]["minutes_per_session"], {
                    "status": "unknown", "value": None,
                })
                self.assertEqual(body["state"]["context"]["minutes_per_session_range"]["value"], {
                    "minimum_minutes": 60, "maximum_minutes": 120,
                })
                self.assertEqual(body["state"]["context"]["sessions_per_week"]["value"], 4)
                self.assertEqual(body["state"]["phase"], "confirming_context")
                self.assertIsNone(body["state"]["routine"])
                self.assertNotIn("지금 루틴을 만들게요", body["reply"])
                self.assertNotIn("목표 시간을 직접 골라", body["reply"])
        self.assertIn("단일 목표 시간을 정하지 않아도", objection["reply"])
        self.assertEqual(initial["quick_replies"], [])
        self.assertEqual(objection["quick_replies"], [])
        selected = self.send("90분으로 정할게요.")
        self.assertEqual(selected["state"]["phase"], "confirming_context")
        self.assertEqual(selected["state"]["context"]["minutes_per_session"]["value"], 90)
        routine = self.send("확인하고 루틴 만들기", "confirm_context")["state"]["routine"]
        self.assertEqual(routine["minutes_per_session"], 90)
        self.assertEqual([s["workout_day_id"] for s in routine["sessions"]], [
            "push_day", "legs_day", "push_day", "legs_day",
        ])

    def test_range_alone_generates_without_a_scalar_target(self) -> None:
        self.send("1~2시간")
        routine = self.send("확인하고 루틴 만들기", "confirm_context")
        self.assertEqual(routine["state"]["phase"], "reviewing_routine")
        self.assertIsNone(routine["state"]["routine"]["minutes_per_session"])
        self.assertEqual(
            routine["state"]["context"]["minutes_per_session_range"]["value"],
            {"minimum_minutes": 60, "maximum_minutes": 120},
        )
        self.assertIn("60~120분으로 기록", routine["reply"])
        self.assertIn("완료된다고 보장하지 않아요", routine["reply"])

    def test_explicit_time_opt_out_retains_availability(self) -> None:
        self.send("1~2시간")
        skipped = self.send("시간 조건을 건너뛸게요.")
        self.assertEqual(skipped["state"]["phase"], "confirming_context")
        self.assertEqual(skipped["state"]["context"]["minutes_per_session"], {
            "status": "skipped", "value": None,
        })
        routine = self.send("확인하고 루틴 만들기", "confirm_context")["state"]["routine"]
        self.assertIsNone(routine["minutes_per_session"])
        self.assertEqual(self.state["context"]["minutes_per_session_range"]["value"], {
            "minimum_minutes": 60, "maximum_minutes": 120,
        })

    def test_knowledge_question_can_update_goal_without_forgetting_availability(self) -> None:
        self.send("1~2시간")
        answer = self.send("근력으로 바꿀게. 근비대랑 차이는 뭐야?")
        self.assertEqual(answer["state"]["context"]["goal"], {
            "status": "provided", "value": "strength",
        })
        self.assertEqual(answer["state"]["context"]["minutes_per_session"]["status"], "unknown")
        self.assertEqual(answer["state"]["phase"], "confirming_context")
        self.assertEqual(answer["state"]["context"]["minutes_per_session_range"]["value"], {
            "minimum_minutes": 60, "maximum_minutes": 120,
        })
