import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

_ROOT = Path(__file__).resolve().parents[1]


def _structured(result: Any) -> dict[str, Any]:
    if result.structured_content is not None:
        return result.structured_content
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool result has no structured content")


class McpServerTests(unittest.TestCase):
    def test_workout_tools_over_stdio(self) -> None:
        asyncio.run(self._run_tools())

    async def _run_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "coach.db"
            server = StdioServerParameters(
                command=sys.executable,
                args=["-m", "yee_doowang.mcp_server"],
                cwd=_ROOT,
                env={"YEE_DOOWANG_DB": str(db_path)},
            )
            async with Client(server, read_timeout_seconds=20) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {tool.name for tool in tools.tools},
                    {
                        "log_workout",
                        "get_workout_history",
                        "log_body_metrics",
                        "get_body_metrics",
                        "estimate_1rm",
                        "calculate_macros",
                        "undo_last_entry",
                        "get_training_context",
                        "export_data",
                    },
                )

                logged = _structured(
                    await client.call_tool(
                        "log_workout",
                        {
                            "exercises": [
                                {
                                    "name": "스쿼트",
                                    "sets": [
                                        {"weight_kg": 100, "reps": 5, "sets": 5}
                                    ],
                                }
                            ],
                            "client_request_id": "mcp-1",
                            "locale": "ko",
                        },
                    )
                )
                self.assertEqual(logged["working_sets"], 5)
                self.assertEqual(logged["total_volume_kg"], 2500.0)
                self.assertEqual(logged["exercises"][0]["exercise_id"], "0043")
                self.assertEqual(logged["exercises"][0]["display_name"], "바벨 풀 스쿼트")
                self.assertEqual(len(logged["new_prs"]), 1)

                history = _structured(
                    await client.call_tool(
                        "get_workout_history",
                        {
                            "exercise": "스쿼트",
                            "group_by": "muscle",
                            "locale": "ko",
                        },
                    )
                )
                self.assertEqual(history["muscles"][0]["muscle"]["id"], "glutes")
                self.assertEqual(history["muscles"][0]["direct_sets"], 5)

                one_rm = _structured(
                    await client.call_tool(
                        "estimate_1rm", {"weight_kg": 100, "reps": 5}
                    )
                )
                self.assertEqual(one_rm["epley_kg"], 116.7)
                self.assertTrue(one_rm["reliable"])

                macros = _structured(
                    await client.call_tool(
                        "calculate_macros",
                        {"body_weight_kg": 80, "goal": "maintain"},
                    )
                )
                self.assertEqual(macros["protein_g_min"], 128.0)
                self.assertEqual(macros["protein_g_max"], 176.0)
                self.assertIsNone(macros["bmr_kcal"])

                metric = _structured(
                    await client.call_tool(
                        "log_body_metrics",
                        {
                            "body_weight_kg": 80,
                            "sleep_hours": 7,
                            "fatigue": 3,
                        },
                    )
                )
                self.assertEqual(metric["record"]["body_weight_kg"], 80.0)

                metrics = _structured(
                    await client.call_tool("get_body_metrics", {"days": 28})
                )
                self.assertEqual(metrics["latest"]["body_weight_kg"], 80.0)
                self.assertEqual(metrics["average_sleep_hours"], 7.0)

                context = _structured(
                    await client.call_tool(
                        "get_training_context", {"days": 28, "locale": "ko"}
                    )
                )
                self.assertEqual(len(context["recent_sessions"]), 1)
                self.assertEqual(
                    context["personal_records"][0]["exercise_id"], "0043"
                )
                self.assertEqual(
                    context["weekly_direct_sets"][0]["muscle"]["id"], "glutes"
                )

                exported = _structured(
                    await client.call_tool("export_data", {"format": "markdown"})
                )
                self.assertTrue(Path(exported["path"]).exists())
                self.assertEqual(exported["sessions"], 1)
                self.assertEqual(exported["sets"], 5)

                deleted = _structured(
                    await client.call_tool(
                        "undo_last_entry", {"kind": "body_metrics"}
                    )
                )
                self.assertEqual(deleted["kind"], "body_metrics")
                remaining = _structured(
                    await client.call_tool("get_body_metrics", {"days": 28})
                )
                self.assertIsNone(remaining["latest"])
