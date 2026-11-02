import unittest

from fastapi.testclient import TestClient

from yee_doowang_api.application.chat import ChatCompletionError
from yee_doowang_api.main import create_app
from yee_doowang_api.settings import Settings


class EchoCompletion:
    async def complete(self, prompt: str) -> str:
        return f"fixture reply: {prompt}"


class FailingCompletion:
    async def complete(self, prompt: str) -> str:
        raise ChatCompletionError("provider detail must not reach the caller")


class ChatApiTests(unittest.TestCase):
    def test_chat_returns_provider_reply(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            completion=EchoCompletion(),
        )
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"prompt": "hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "fixture reply: hello"})

    def test_chat_rejects_blank_prompt(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            completion=EchoCompletion(),
        )
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"prompt": "   "})

        self.assertEqual(response.status_code, 422)

    def test_chat_reports_missing_configuration(self) -> None:
        app = create_app(
            settings=Settings(
                _env_file=None,
                openrouter_api_key=None,
                openrouter_model=None,
            )
        )
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"prompt": "hello"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENROUTER_API_KEY", response.json()["detail"])

    def test_chat_hides_provider_error_details(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            completion=FailingCompletion(),
        )
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"prompt": "hello"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "The LLM provider request failed.")
