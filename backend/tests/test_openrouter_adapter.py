import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from pydantic import SecretStr

from yee_doowang_api.infrastructure.openrouter import OpenRouterChatCompletion


class OpenRouterAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_uses_openai_compatible_response(self) -> None:
        requests: list[dict[str, object]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                requests.append(json.loads(self.rfile.read(length)))
                payload = {
                    "id": "fixture-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "fixture/model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "fixture provider reply",
                            },
                            "finish_reason": "stop",
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
        completion = OpenRouterChatCompletion(
            api_key=SecretStr("fixture-key"),
            model="fixture/model",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
        )

        try:
            reply = await completion.complete("hello")
        finally:
            await completion.aclose()
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

        self.assertEqual(reply, "fixture provider reply")
        self.assertEqual(requests[0]["model"], "fixture/model")
        self.assertEqual(
            requests[0]["messages"],
            [{"role": "user", "content": "hello"}],
        )
