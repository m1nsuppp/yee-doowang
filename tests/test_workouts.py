import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from yee_doowang.catalog import Catalog
from yee_doowang.ontology import ExerciseOntology
from yee_doowang.storage import WorkoutStore
from yee_doowang.workouts import (
    BodyMetricInput,
    ExerciseInput,
    LogWorkoutRequest,
    SetInput,
    WorkoutHistoryRequest,
    WorkoutService,
)


class WorkoutServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.catalog = Catalog.load()
        self.store = WorkoutStore(Path(self._tmp.name) / "coach.db")
        self.service = WorkoutService(
            self.store,
            self.catalog,
            ExerciseOntology(self.catalog),
        )

    def _log(
        self,
        *,
        name: str = "스쿼트",
        weight_kg: float = 100,
        reps: int = 5,
        sets: int = 5,
        performed_at: datetime | None = None,
        client_request_id: str | None = None,
    ):
        return self.service.log_workout(
            LogWorkoutRequest(
                exercises=[
                    ExerciseInput(
                        name=name,
                        sets=[
                            SetInput(weight_kg=weight_kg, reps=reps, sets=sets)
                        ],
                    )
                ],
                performed_at=performed_at,
                client_request_id=client_request_id,
            )
        )

    def test_log_workout_resolves_korean_alias_and_stores_sets(self) -> None:
        result = self._log()

        self.assertEqual(result.working_sets, 5)
        self.assertEqual(result.total_volume_kg, 2500.0)
        self.assertEqual(result.exercises[0].exercise_id, "0043")
        self.assertEqual(result.exercises[0].display_name, "바벨 풀 스쿼트")
        self.assertEqual(
            [(item.muscle.id, item.sets) for item in result.muscle_sets],
            [("glutes", 5)],
        )
        self.assertEqual(len(result.new_prs), 1)
        self.assertEqual(len(self.store.get_sets(session_id=result.session_id)), 5)

    def test_history_and_progression_signal(self) -> None:
        self._log(
            weight_kg=100,
            performed_at=datetime(2026, 11, 1, 18, tzinfo=UTC),
        )
        self._log(
            weight_kg=105,
            performed_at=datetime(2026, 11, 8, 18, tzinfo=UTC),
        )
        self._log(
            weight_kg=110,
            performed_at=datetime(2026, 11, 15, 18, tzinfo=UTC),
        )

        history = self.service.workout_history(
            WorkoutHistoryRequest(
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                group_by="exercise",
            )
        )
        self.assertEqual(len(history.exercises), 1)
        exercise = history.exercises[0]
        self.assertEqual(exercise.sessions, 3)
        self.assertEqual(exercise.total_volume_kg, 7875.0)
        self.assertEqual(exercise.best_weight_kg, 110.0)
        self.assertEqual(exercise.best_e1rm_kg, 128.3)
        self.assertEqual(history.signals[0].trend, "up")
        self.assertGreater(history.signals[0].change_pct or 0, 2)

        muscles = self.service.workout_history(
            WorkoutHistoryRequest(
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                group_by="muscle",
            )
        )
        self.assertEqual(muscles.muscles[0].muscle.id, "glutes")
        self.assertEqual(muscles.muscles[0].direct_sets, 15)

        weeks = self.service.workout_history(
            WorkoutHistoryRequest(
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                group_by="week",
            )
        )
        self.assertEqual(len(weeks.weeks), 3)
        self.assertTrue(all(week.sessions == 1 for week in weeks.weeks))

    def test_sessions_can_include_individual_sets(self) -> None:
        self._log(
            performed_at=datetime(2026, 11, 1, 18, tzinfo=UTC)
        )

        history = self.service.workout_history(
            WorkoutHistoryRequest(
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 2),
                include_sets=True,
            )
        )

        self.assertEqual(len(history.sessions), 1)
        self.assertEqual(len(history.sessions[0].sets or []), 5)
        self.assertEqual(history.sessions[0].sets[0].display_name, "바벨 풀 스쿼트")

    def test_body_metrics_and_undo(self) -> None:
        first = self.service.log_body_metrics(
            BodyMetricInput(body_weight_kg=80, sleep_hours=7, fatigue=3)
        )
        self.assertIsNone(first.body_weight_change_kg)

        second = self.service.log_body_metrics(
            BodyMetricInput(body_weight_kg=79.5)
        )
        self.assertEqual(second.body_weight_change_kg, -0.5)

        summary = self.service.body_metrics(28)
        self.assertEqual(summary.latest.body_weight_kg, 79.5)
        self.assertEqual(summary.average_body_weight_kg, 79.75)
        self.assertEqual(summary.average_sleep_hours, 7.0)

        with self.assertRaises(ValidationError):
            BodyMetricInput(notes="no metrics")

        deleted = self.service.undo_last_entry("body_metrics")
        self.assertEqual(deleted.kind, "body_metrics")
        self.assertEqual(self.service.body_metrics(28).latest.body_weight_kg, 80.0)

    def test_duplicate_request_id_lb_conversion_and_unknown_exercise(self) -> None:
        first = self._log(client_request_id="req-1")
        second = self._log(client_request_id="req-1")
        self.assertTrue(second.duplicate)
        self.assertEqual(first.session_id, second.session_id)
        self.assertEqual(len(self.store.get_sets(session_id=first.session_id)), 5)

        pounds = self.service.log_workout(
            LogWorkoutRequest(
                exercises=[
                    ExerciseInput(
                        name="벤치프레스",
                        sets=[SetInput(weight_kg=100, reps=5)],
                    )
                ],
                weight_unit="lb",
            )
        )
        self.assertEqual(pounds.exercises[0].exercise_id, "0025")
        self.assertAlmostEqual(pounds.total_volume_kg, 226.8, places=1)

        with self.assertRaises(ValueError):
            self._log(name="존재하지 않는 운동")

    def test_export_and_training_context(self) -> None:
        self._log()
        self.service.log_body_metrics(
            BodyMetricInput(body_weight_kg=80, sleep_hours=7, fatigue=3)
        )

        export = self.service.export_data("json")
        path = Path(export.path)
        self.assertTrue(path.exists())
        self.assertEqual(export.sessions, 1)
        self.assertEqual(export.sets, 5)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["sessions"]), 1)

        markdown = self.service.export_data("markdown")
        self.assertTrue(Path(markdown.path).exists())

        context = self.service.training_context(28)
        self.assertEqual(len(context.recent_sessions), 1)
        self.assertEqual(context.personal_records[0].exercise_id, "0043")
        self.assertEqual(context.weekly_direct_sets[0].muscle.id, "glutes")

        deleted = self.service.undo_last_entry("workout")
        self.assertEqual(deleted.kind, "workout")
        self.assertIsNone(self.store.latest_session())
