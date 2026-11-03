import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from pydantic import SecretStr

from yee_doowang_api.application.chat import (
    ConversationMessage,
    EquipmentConstraint,
)
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog
from yee_doowang_api.infrastructure.openrouter import OpenRouterCoachModel


class OpenRouterAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_intent_and_coach_answer_use_tool_responses(self) -> None:
        requests: list[dict[str, object]] = []
        outputs = [
            {
                "workout_intent": "push_day",
                "equipment": {"mode": "delegate_any", "equipment_ids": []},
                "message": "",
            },
            {"reply": "장비 제한 없이 후보를 골랐어요."},
        ]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                request = json.loads(self.rfile.read(length))
                requests.append(request)
                tool_name = request["tools"][0]["function"]["name"]
                output = outputs[len(requests) - 1]
                payload = {
                    "id": f"fixture-completion-{len(requests)}",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "fixture/model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": f"fixture-call-{len(requests)}",
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(output),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        model = OpenRouterCoachModel(
            api_key=SecretStr("fixture-key"),
            model="fixture/model",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
        )
        catalog = load_exercise_catalog()
        candidate_without_name_ko = next(
            exercise for exercise in catalog.exercises if exercise.name_ko is None
        )
        candidate_without_pattern = next(
            exercise
            for exercise in catalog.exercises
            if exercise.movement_pattern_id is None
            and exercise.source_id != candidate_without_name_ko.source_id
        )
        prompt_candidates = [candidate_without_name_ko, candidate_without_pattern]
        messages = [
            ConversationMessage(
                role="user",
                content="모르겠어. 알아서 골라줘.",
            )
        ]

        try:
            intent = await model.interpret(
                messages,
                catalog.equipment,
                catalog.workout_days,
                catalog.muscles,
            )
            answer = await model.answer(
                messages,
                prompt_candidates,
                EquipmentConstraint(mode="unrestricted", equipment_ids=[]),
            )
        finally:
            await model.aclose()
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

        self.assertEqual(intent.workout_intent, "push_day")
        self.assertEqual(intent.equipment.mode, "delegate_any")
        self.assertEqual(intent.equipment.equipment_ids, [])
        self.assertEqual(answer.reply, "장비 제한 없이 후보를 골랐어요.")
        self.assertEqual(len(requests), 2)
        prompt = requests[1]["messages"][0]["content"]
        prompt_facts = json.loads(prompt.split("검증된 후보(JSON): ", 1)[1])
        self.assertEqual(
            [
                (fact["name"], fact["name_ko"], fact["movement_pattern_id"])
                for fact in prompt_facts
            ],
            [
                (item.name, item.name_ko, item.movement_pattern_id)
                for item in prompt_candidates
            ],
        )
