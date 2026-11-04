import unittest
from dataclasses import FrozenInstanceError

from yee_doowang_api.application.chat_models import (
    ContextField,
    EquipmentIntent,
    RoutineContext,
    SessionTimeRange,
    WorkoutSplitTemplate,
)
from yee_doowang_api.application.routine_context import (
    IntakeQuestion,
    RoutineContextManager,
)
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog


class IntakeQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_exercise_catalog()
        cls.manager = RoutineContextManager(cls.catalog)

    def _context(self, **overrides: object) -> RoutineContext:
        fields = {
            "workout_day_ids": ContextField(
                status="provided", value=[self.catalog.workout_days[0].id]
            ),
            "goal": ContextField(status="provided", value="strength"),
            "experience": ContextField(status="provided", value="novice"),
            "sessions_per_week": ContextField(status="provided", value=3),
            "minutes_per_session": ContextField(status="skipped"),
            "equipment": ContextField(status="skipped"),
            "preferences": ContextField(status="provided", value=[]),
            "known_constraints": ContextField(status="provided", value=[]),
        }
        return RoutineContext.model_validate(fields | overrides)

    @staticmethod
    def _range(minimum: int, maximum: int) -> ContextField[SessionTimeRange]:
        return ContextField(
            status="provided",
            value=SessionTimeRange(minimum_minutes=minimum, maximum_minutes=maximum),
        )

    def test_each_gate_owns_its_question_reason_and_choices(self) -> None:
        cases = [
            ("workout_day_ids", {"workout_day_ids": ContextField(status="unknown")}),
            ("workout_split_type", {"workout_split_type": ContextField(status="delegated")}),
            (
                "workout_split_assignment",
                {"workout_split_type": ContextField(status="provided", value="ab")},
            ),
            (
                "workout_split_assignment",
                {
                    "workout_split_type": ContextField(status="provided", value="ab"),
                    "workout_split_assignment": ContextField(status="delegated"),
                    "split_proposal_rejected": True,
                },
            ),
            ("sessions_per_week", {"sessions_per_week": ContextField(status="unknown")}),
            ("goal", {"goal": ContextField(status="unknown")}),
            ("goal", {"goal": ContextField(status="provided", value="other")}),
            (
                "adult_eligibility",
                {"goal": ContextField(status="provided", value="hypertrophy")},
            ),
            ("experience", {"experience": ContextField(status="unknown")}),
            ("experience", {"experience": ContextField(status="provided", value="experienced")}),
            ("minutes_per_session", {"minutes_per_session": ContextField(status="unknown")}),
            ("equipment", {"equipment": ContextField(status="unknown")}),
            (
                "equipment",
                {
                    "equipment": ContextField(
                        status="provided", value=EquipmentIntent(mode="unknown", equipment_ids=[])
                    )
                },
            ),
            ("preferences", {"preferences": ContextField(status="unknown")}),
            ("known_constraints", {"known_constraints": ContextField(status="delegated")}),
            (
                "weekly_direct_sets_by_muscle",
                {
                    "goal": ContextField(status="provided", value="hypertrophy"),
                    "experience": ContextField(status="provided", value="experienced"),
                    "adult_eligibility": ContextField(status="provided", value="adult"),
                },
            ),
        ]
        for expected_field, overrides in cases:
            with self.subTest(field=expected_field, overrides=overrides):
                context = self._context(**overrides)
                before = context.model_dump()
                question = self.manager.next_context_question(context)
                self.assertIsInstance(question, IntakeQuestion)
                self.assertEqual(question.field, expected_field)
                self.assertTrue(question.prompt)
                self.assertTrue(question.rationale)
                self.assertTrue(question.quick_replies)
                self.assertTrue(all(reply.label and reply.message for reply in question.quick_replies))
                self.assertEqual(context.model_dump(), before)

    def test_area_choice_offers_a_recommendation_without_recording_one(self) -> None:
        context = self._context(workout_day_ids=ContextField(status="unknown"))
        question = self.manager.next_context_question(context)
        self.assertEqual(question.field, "workout_day_ids")
        self.assertEqual(question.quick_replies[0].label, "부위 추천받기")
        self.assertEqual(
            question.quick_replies[0].message,
            "운동 부위 선택을 맡길게요. 목표와 주당 횟수에 맞춰 추천해 주세요.",
        )
        self.assertIsNone(context.workout_day_ids.value)

    def test_decision_is_frozen_and_follows_the_first_pending_field(self) -> None:
        context = self._context(
            goal=ContextField(status="unknown"),
            minutes_per_session=ContextField(status="unknown"),
            minutes_per_session_range=self._range(30, 60),
        )
        question = self.manager.next_context_question(context)
        self.assertEqual(question.field, "goal")
        self.assertEqual(
            [reply.label for reply in question.quick_replies],
            ["근비대", "근력", "둘 다", "목표 건너뛰기"],
        )
        with self.assertRaises(FrozenInstanceError):
            question.field = "minutes_per_session"

    def test_range_is_sufficient_availability_without_inventing_a_single_target(self) -> None:
        for minimum, maximum in ((30, 60), (47, 53), (1, 2)):
            for status in ("not_asked", "unknown", "delegated"):
                with self.subTest(minimum=minimum, maximum=maximum, status=status):
                    context = self._context(
                        minutes_per_session=ContextField(status=status),
                        minutes_per_session_range=self._range(minimum, maximum),
                    )
                    before = context.model_dump()
                    self.assertIsNone(self.manager.next_context_question(context))
                    self.assertEqual(context.minutes_per_session.status, status)
                    self.assertEqual(
                        context.minutes_per_session_range.value,
                        SessionTimeRange(
                            minimum_minutes=minimum, maximum_minutes=maximum
                        ),
                    )
                    self.assertEqual(context.model_dump(), before)

    def test_unknown_or_delegated_time_without_a_range_still_blocks(self) -> None:
        for status in ("not_asked", "unknown", "delegated"):
            with self.subTest(status=status):
                context = self._context(minutes_per_session=ContextField(status=status))
                question = self.manager.next_context_question(context)
                self.assertEqual(question.field, "minutes_per_session")
                self.assertEqual(
                    [reply.label for reply in question.quick_replies], ["시간 조건 건너뛰기"]
                )
                self.assertIsNone(context.minutes_per_session.value)

    def test_explicit_time_skip_advances_and_retains_the_range(self) -> None:
        previous = self._context(
            minutes_per_session=ContextField(status="unknown"),
            minutes_per_session_range=self._range(30, 60),
        )
        merged = self.manager.merge(
            previous,
            RoutineContext(minutes_per_session=ContextField(status="skipped")),
        )
        self.assertIsNone(self.manager.next_context_question(merged))
        self.assertEqual(merged.minutes_per_session.status, "skipped")
        self.assertIsNone(merged.minutes_per_session.value)
        self.assertEqual(merged.minutes_per_session_range, previous.minutes_per_session_range)

    def test_new_range_clears_inherited_target_before_validation(self) -> None:
        for old_target in (20, 45):
            for explicit_flag in (False, True):
                with self.subTest(old_target=old_target, explicit_flag=explicit_flag):
                    previous = self._context(
                        minutes_per_session=ContextField(status="provided", value=old_target),
                        minutes_per_session_range=self._range(15, 60),
                    )
                    before = previous.model_dump()
                    updates = RoutineContext(minutes_per_session_range=self._range(40, 60))
                    merged = self.manager.merge(
                        previous, updates, explicit_minutes_target=explicit_flag
                    )
                    self.assertEqual(merged.minutes_per_session.status, "unknown")
                    self.assertIsNone(merged.minutes_per_session.value)
                    self.assertEqual(merged.minutes_per_session_range, updates.minutes_per_session_range)
                    self.assertEqual(previous.model_dump(), before)

    def test_nonexplicit_target_update_never_chooses_from_a_saved_range(self) -> None:
        for target in (20, 45):
            with self.subTest(target=target):
                previous = self._context(
                    minutes_per_session=ContextField(status="unknown"),
                    minutes_per_session_range=self._range(30, 60),
                )
                merged = self.manager.merge(
                    previous,
                    RoutineContext(minutes_per_session=ContextField(status="provided", value=target)),
                )
                self.assertEqual(merged.minutes_per_session.status, "unknown")
                self.assertIsNone(merged.minutes_per_session.value)
                self.assertEqual(merged.minutes_per_session_range, previous.minutes_per_session_range)

    def test_explicit_target_and_new_range_are_preserved_together(self) -> None:
        previous = self._context(minutes_per_session=ContextField(status="provided", value=20))
        updates = RoutineContext(
            minutes_per_session=ContextField(status="provided", value=45),
            minutes_per_session_range=self._range(40, 60),
        )
        merged = self.manager.merge(previous, updates, explicit_minutes_target=True)
        self.assertEqual(merged.minutes_per_session, updates.minutes_per_session)
        self.assertEqual(merged.minutes_per_session_range, updates.minutes_per_session_range)
        self.assertIsNone(self.manager.next_context_question(merged))

    def test_explicit_single_target_replaces_only_an_incompatible_historical_range(self) -> None:
        for target in (20, 50):
            with self.subTest(target=target):
                previous = self._context(
                    minutes_per_session=ContextField(status="provided", value=45),
                    minutes_per_session_range=self._range(30, 60),
                )
                merged = self.manager.merge(
                    previous,
                    RoutineContext(minutes_per_session=ContextField(status="provided", value=target)),
                    explicit_minutes_target=True,
                )
                self.assertEqual(merged.minutes_per_session.value, target)
                if target == 20:
                    self.assertEqual(merged.minutes_per_session_range.status, "not_asked")
                    self.assertIsNone(merged.minutes_per_session_range.value)
                else:
                    self.assertEqual(merged.minutes_per_session_range, previous.minutes_per_session_range)
                for field in ("goal", "experience", "workout_day_ids", "sessions_per_week"):
                    self.assertEqual(getattr(merged, field), getattr(previous, field))

    def test_unrelated_turn_preserves_an_unchanged_confirmed_target(self) -> None:
        previous = self._context(
            minutes_per_session=ContextField(status="provided", value=45),
            minutes_per_session_range=self._range(30, 60),
        )
        for echo_time in (False, True):
            with self.subTest(echo_time=echo_time):
                updates = RoutineContext(
                    preferences=ContextField(status="skipped"),
                    minutes_per_session=previous.minutes_per_session if echo_time else ContextField(),
                    minutes_per_session_range=previous.minutes_per_session_range if echo_time else ContextField(),
                )
                merged = self.manager.merge(previous, updates)
                self.assertEqual(merged.minutes_per_session, previous.minutes_per_session)
                self.assertEqual(merged.minutes_per_session_range, previous.minutes_per_session_range)

    def test_new_nonvalue_target_update_is_not_overwritten_by_range_reset(self) -> None:
        previous = self._context(
            minutes_per_session=ContextField(status="provided", value=20),
            minutes_per_session_range=self._range(15, 30),
        )
        for status in ("unknown", "skipped", "delegated"):
            with self.subTest(status=status):
                updates = RoutineContext(
                    minutes_per_session=ContextField(status=status),
                    minutes_per_session_range=self._range(45, 75),
                )
                merged = self.manager.merge(previous, updates)
                self.assertEqual(merged.minutes_per_session, updates.minutes_per_session)
                self.assertEqual(merged.minutes_per_session_range, updates.minutes_per_session_range)

    def test_range_changes_preserve_target_status_without_blocking_on_a_range(self) -> None:
        for status in ("unknown", "skipped", "delegated"):
            for update_status in (False, True):
                with self.subTest(status=status, update_status=update_status):
                    previous = self._context(
                        minutes_per_session=ContextField(status=status),
                        minutes_per_session_range=self._range(30, 60),
                    )
                    updates = RoutineContext(
                        minutes_per_session=ContextField(status=status) if update_status else ContextField(),
                        minutes_per_session_range=self._range(45, 75),
                    )
                    merged = self.manager.merge(previous, updates)
                    self.assertEqual(merged.minutes_per_session.status, status)
                    self.assertIsNone(merged.minutes_per_session.value)
                    self.assertIsNone(self.manager.next_context_question(merged))

    def test_time_edit_does_not_change_split_proposal(self) -> None:
        days = [day.id for day in self.catalog.workout_days[:2]]
        previous = self._context(
            workout_day_ids=ContextField(status="provided", value=days),
            workout_split_type=ContextField(status="provided", value="ab"),
            workout_split_assignment=ContextField(status="delegated"),
            split_template=WorkoutSplitTemplate(
                day_a_ids=days[:1], day_b_ids=days[1:], confirmation_status="proposed"
            ),
            minutes_per_session=ContextField(status="provided", value=20),
        )
        merged = self.manager.merge(
            previous, RoutineContext(minutes_per_session_range=self._range(45, 60))
        )
        self.assertEqual(merged.split_template, previous.split_template)
        self.assertEqual(merged.workout_split_assignment, previous.workout_split_assignment)
        self.assertEqual(merged.workout_day_ids, previous.workout_day_ids)

    def test_skipping_remaining_volume_preserves_reported_sets(self) -> None:
        days = self.catalog.workout_days
        reported_id = days[0].focus_muscle_ids[0]
        previous = self._context(
            workout_day_ids=ContextField(status="provided", value=[day.id for day in days]),
            goal=ContextField(status="provided", value="hypertrophy"),
            experience=ContextField(status="provided", value="experienced"),
            adult_eligibility=ContextField(status="provided", value="adult"),
            weekly_direct_sets_by_muscle=ContextField(status="provided", value={reported_id: 8}),
        )
        question = self.manager.next_context_question(previous)
        self.assertEqual(question.field, "weekly_direct_sets_by_muscle")
        self.assertEqual(question.quick_replies[0].label, "세트 수 보고 건너뛰기")
        merged = self.manager.merge(
            previous,
            RoutineContext(weekly_direct_sets_by_muscle=ContextField(status="skipped")),
        )
        self.assertEqual(merged.weekly_direct_sets_by_muscle.value, {reported_id: 8})
        self.assertEqual(merged.weekly_direct_sets_follow_up.status, "skipped")
        self.assertIsNone(self.manager.next_context_question(merged))
