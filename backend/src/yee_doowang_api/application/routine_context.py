from __future__ import annotations

from typing import Literal

from yee_doowang_api.application.chat_models import (
    ChatReply,
    ContextField,
    ConversationState,
    QuickReply,
    RoutineContext,
    WorkoutSplitTemplate,
)
from yee_doowang_api.application.exercise_catalog import ExerciseCatalog


class RoutineContextManager:
    def __init__(self, catalog: ExerciseCatalog) -> None:
        self._catalog = catalog
        self._workout_days_by_id = {day.id: day for day in catalog.workout_days}
        self._workout_day_names = {day.id: day.name_ko for day in catalog.workout_days}
        self._focus_muscle_ids_by_day = {
            day.id: set(day.focus_muscle_ids) for day in catalog.workout_days
        }
        self._muscle_names = {
            item.id: item.name_ko or f"원문 근육명: {item.source_terms[0]}"
            for item in catalog.muscles
        }
        self._equipment_names = {
            item.id: item.name_ko or f"원문 장비명: {item.source_term}"
            for item in catalog.equipment
        }

    def merge(self, previous: RoutineContext, updates: RoutineContext) -> RoutineContext:
        merged = previous.model_dump()
        changed_fields: set[str] = set()
        system_fields = {"split_template", "split_proposal_rejected"}
        stopped_set_report: Literal["unknown", "skipped", "delegated"] | None = None
        for field_name in RoutineContext.model_fields:
            if field_name in system_fields:
                continue
            previous_field = getattr(previous, field_name)
            update_field = getattr(updates, field_name)
            if update_field.status == "not_asked":
                continue
            if update_field.model_dump() != previous_field.model_dump():
                changed_fields.add(field_name)
            if field_name == "weekly_direct_sets_by_muscle" and previous_field.status == "provided":
                if update_field.status == "provided":
                    values = dict(previous_field.value or {})
                    values.update(update_field.value or {})
                    merged[field_name] = {"status": "provided", "value": values}
                elif update_field.status in {"unknown", "skipped", "delegated"}:
                    merged[field_name] = previous_field.model_dump()
                    stopped_set_report = update_field.status
                else:
                    merged[field_name] = update_field.model_dump()
            else:
                merged[field_name] = update_field.model_dump()

        if stopped_set_report is not None:
            follow_up_status = updates.weekly_direct_sets_follow_up.status
            if follow_up_status not in {"unknown", "skipped", "delegated"}:
                follow_up_status = stopped_set_report
            merged["weekly_direct_sets_follow_up"] = {
                "status": follow_up_status,
                "value": None,
            }
        if merged["workout_split_type"]["status"] == "skipped":
            merged["workout_split_assignment"] = {
                "status": "skipped",
                "value": None,
            }
        context_changed_days = "workout_day_ids" in changed_fields
        split_request_changed = bool(
            changed_fields & {"workout_split_type", "workout_split_assignment"}
        )
        if context_changed_days or split_request_changed:
            merged["split_template"] = None
            merged["split_proposal_rejected"] = False
        else:
            merged["split_template"] = (
                previous.split_template.model_dump()
                if previous.split_template is not None
                else None
            )
            merged["split_proposal_rejected"] = previous.split_proposal_rejected

        return RoutineContext.model_validate(merged)

    @staticmethod
    def replace_split_template_status(
        context: RoutineContext,
        status: Literal["proposed", "confirmed"],
    ) -> RoutineContext:
        data = context.model_dump()
        template = data["split_template"]
        template["confirmation_status"] = status
        return RoutineContext.model_validate(data)

    @staticmethod
    def reject_split_proposal(context: RoutineContext) -> RoutineContext:
        data = context.model_dump()
        data["split_template"] = None
        data["split_proposal_rejected"] = True
        return RoutineContext.model_validate(data)

    def _split_template_matches_context(
        self,
        template: WorkoutSplitTemplate,
        context: RoutineContext,
    ) -> bool:
        if context.workout_day_ids.status != "provided":
            return False
        template_day_ids = set(template.day_a_ids + template.day_b_ids)
        selected_day_ids = set(context.workout_day_ids.value or [])
        return (
            template_day_ids == selected_day_ids
            and not (template_day_ids - self._workout_day_names.keys())
        )

    def invalid_split_configuration_reply(
        self,
        context: RoutineContext,
    ) -> ChatReply | None:
        assignment = (
            context.workout_split_assignment.value
            if context.workout_split_assignment.status == "provided"
            else None
        )
        invalid_assignment = assignment is not None and not self._split_template_matches_context(
            assignment, context
        )
        invalid_proposal = (
            context.split_template is not None
            and not self._split_template_matches_context(context.split_template, context)
        )
        if not invalid_assignment and not invalid_proposal:
            return None

        data = context.model_dump()
        if invalid_assignment:
            data["workout_split_assignment"] = {"status": "unknown", "value": None}
        if invalid_proposal or (invalid_assignment and context.split_template is not None):
            data["split_template"] = None
            data["split_proposal_rejected"] = not (
                assignment is not None and not invalid_assignment
            )
        safe_context = RoutineContext.model_validate(data)
        supported = ", ".join(self._workout_day_names.values())
        return ChatReply(
            reply=(
                "A/B 구성에 지원되지 않거나 선택 부위와 맞지 않는 운동일 ID가 있어요. "
                f"현재 지원 부위: {supported}. A/B 그룹을 지원 부위 이름으로 다시 알려주세요."
            ),
            state=ConversationState(context=safe_context),
            exploration_exercises=[],
            quick_replies=self.split_assignment_quick_replies(),
        )

    def _split_names(self, template: WorkoutSplitTemplate) -> tuple[str, str]:
        day_a = ", ".join(self._workout_day_names[item] for item in template.day_a_ids)
        day_b = ", ".join(self._workout_day_names[item] for item in template.day_b_ids)
        return day_a, day_b

    def split_confirmation_prompt(self, context: RoutineContext) -> str:
        template = context.split_template
        if template is None:
            raise ValueError("a split confirmation requires a proposed template")
        day_a, day_b = self._split_names(template)
        return (
            "주당 운동 횟수와 별도로 2분할 구성을 제안해요. "
            f"A: {day_a}; B: {day_b}. "
            "이 구성을 명시적으로 확인하기 전에는 루틴 초안을 만들지 않아요. "
            "맞으면 ‘이 A/B 분할을 확인합니다’라고 답하고, 바꾸려면 원하는 A/B 부위를 알려주세요."
        )

    @staticmethod
    def _session_frequency_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label=f"주 {frequency}회", message=f"주 {frequency}회")
            for frequency in range(1, 8)
        ]

    def context_question_quick_replies(
        self,
        context: RoutineContext,
    ) -> list[QuickReply]:
        if context.workout_day_ids.status in {"not_asked", "unknown", "delegated"}:
            return []
        if context.workout_split_type.status in {"unknown", "delegated"}:
            return self._split_type_quick_replies()
        if (
            context.workout_split_type.status == "provided"
            and context.workout_split_assignment.status
            in {"not_asked", "unknown", "skipped"}
        ):
            return self.split_assignment_quick_replies()
        if context.sessions_per_week.status in {"not_asked", "unknown", "delegated"}:
            return self._session_frequency_quick_replies()
        return []

    @staticmethod
    def _split_type_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="2분할", message="2분할을 선택합니다."),
            QuickReply(label="분할 없이", message="분할 없이 진행합니다."),
        ]

    @staticmethod
    def split_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="이 분할로 진행", message="이 A/B 분할을 확인합니다."),
            QuickReply(label="분할 바꾸기", message="A/B 분할을 바꾸고 싶어요."),
        ]

    @staticmethod
    def split_assignment_question(context: RoutineContext) -> str:
        requested = context.workout_split_type.status == "provided"
        if not requested:
            return "A/B 분할 요청이 없어졌어요. 원하는 운동 부위를 알려주세요."
        return (
            "앞서 제안한 A/B 구성은 확인되지 않았어요. "
            "A와 B에 넣을 지원 운동 부위를 각각 알려주시거나, 새 제안을 맡기려면 ‘A/B 분할을 다시 제안해줘’라고 해주세요."
        )

    @staticmethod
    def split_assignment_quick_replies() -> list[QuickReply]:
        return [
            QuickReply(label="다시 제안받기", message="A/B 분할을 다시 제안해줘."),
            QuickReply(label="직접 정하기", message="A/B 분할을 직접 정하겠습니다."),
        ]

    def _split_missing_area_reply(self, context: RoutineContext) -> ChatReply:
        selected_ids = context.workout_day_ids.value or []
        selected_names = ", ".join(
            self._workout_day_names[day_id] for day_id in selected_ids
        )
        selected_text = f"현재 선택한 부위: {selected_names}. " if selected_names else ""
        quick_replies = [
            QuickReply(
                label=f"{day.name_ko} 추가",
                message=f"{selected_text}{day.name_ko}를 추가해 2분할 A/B를 제안해줘.",
            )
            for day in self._workout_days_by_id.values()
            if day.id not in selected_ids
        ]
        quick_replies.append(
            QuickReply(label="2분할 취소", message="2분할 없이 진행합니다.")
        )
        return ChatReply(
            reply=(
                "A/B 분할을 제안하려면 서로 다른 지원 운동 부위가 두 개 이상 필요해요. "
                f"{selected_text}추가할 부위를 골라 주세요. 선택하지 않은 부위를 임의로 넣지 않습니다."
            ),
            state=ConversationState(context=context),
            exploration_exercises=[],
            quick_replies=quick_replies,
        )
    def propose_split(self, context: RoutineContext) -> ChatReply:
        day_ids = context.workout_day_ids.value or []
        if len(day_ids) < 2:
            return self._split_missing_area_reply(context)
        midpoint = (len(day_ids) + 1) // 2
        template = WorkoutSplitTemplate(
            day_a_ids=day_ids[:midpoint],
            day_b_ids=day_ids[midpoint:],
            confirmation_status="proposed",
        )
        data = context.model_dump()
        data["split_template"] = template.model_dump()
        proposed_context = RoutineContext.model_validate(data)
        return ChatReply(
            reply=self.split_confirmation_prompt(proposed_context),
            state=ConversationState(phase="confirming_split", context=proposed_context),
            exploration_exercises=[],
            quick_replies=self.split_quick_replies(),
        )

    def next_context_question(self, context: RoutineContext) -> str | None:
        if context.workout_day_ids.status in {"not_asked", "unknown", "delegated"}:
            supported = ", ".join(self._workout_day_names.values())
            if context.workout_day_ids.status == "unknown":
                return f"운동 부위를 아직 모르시는 걸로 기록했어요. 지원 부위({supported}) 중 하나 이상을 직접 골라 주세요. 선택을 맡기거나 건너뛰어도 됩니다."
            if context.workout_day_ids.status == "delegated":
                return f"부위 선택은 맡기셨지만 임의로 고르지 않겠습니다. 지원 부위({supported}) 중 원하는 부위를 알려주시거나 건너뛰어 주세요."
            return (
                "주간 일정에 넣을 운동 부위를 알려주세요. 현재 지원 범위: "
                f"{supported}. 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.workout_split_type.status in {"unknown", "delegated"}:
            return (
                "주당 빈도와 분할 방식은 별개예요. 2분할 여부를 모르시거나 선택을 맡기신 것으로 기록했어요. "
                "2분할 A/B 구성을 정할지, 분할 없이 선택 부위별 일정을 만들지 알려주세요."
            )
        if context.workout_split_type.status == "provided":
            assignment_status = context.workout_split_assignment.status
            if context.split_proposal_rejected:
                return self.split_assignment_question(context)
            if assignment_status in {"not_asked", "unknown"}:
                return (
                    "주당 빈도는 별도로 보존했어요. 2분할 A/B에 넣을 운동 부위를 각각 알려주세요. "
                    "예: A는 가슴·어깨, B는 하체. 구성을 맡기려면 ‘A/B 분할을 알아서 제안해줘’라고 해주세요."
                )
            if assignment_status == "skipped":
                return (
                    "A/B 구성을 건너뛰어 2분할 초안은 만들지 않아요. A/B 부위를 직접 정하거나, "
                    "제안을 맡기거나, 2분할 요청을 취소해 주세요."
                )
        if context.sessions_per_week.status in {"not_asked", "unknown", "delegated"}:
            if context.sessions_per_week.status == "unknown":
                return "주당 운동 횟수를 모르시는 걸로 기록했어요. 주 1~7회 중 정확한 횟수를 고르거나, 주간 일정 항목을 건너뛰어 주세요."
            if context.sessions_per_week.status == "delegated":
                return "주당 횟수 선택을 맡기셨지만 빈도를 임의로 정하지 않겠습니다. 주 1~7회 중 하나를 알려주시거나 주간 일정 항목을 건너뛰어 주세요."
            return (
                "주간 일정을 만들려면 주당 운동 횟수가 필요해요. "
                "주 1~7회 중 알려주세요. 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.goal.status in {"not_asked", "unknown"}:
            if context.goal.status == "unknown":
                return "우선 목표를 아직 정하지 않으신 걸로 기록했어요. 근비대, 근력 중 하나를 고르거나 두 목표를 함께 추구할 수 있어요. 목표 분류를 건너뛰어도 됩니다."
            return (
                "우선할 목표를 근비대, 근력 중에서 고르거나 두 목표를 함께 추구할 수 있어요. 모르거나 답하고 싶지 않으면 "
                "목표 분류를 건너뛸 수 있어요."
            )
        if context.goal.status == "provided" and context.goal.value == "other":
            return (
                "현재 출처가 연결된 목표는 근비대와 근력 진행이에요. "
                "하나를 고르거나 두 목표를 함께 선택하거나 목표 분류를 건너뛰어 주세요."
            )
        if context.adult_eligibility.status in {"not_asked", "unknown", "delegated"} and (
            context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}
        ):
            if context.adult_eligibility.status in {"unknown", "delegated"}:
                return "성인 여부는 추정하지 않아요. 근비대 처방의 적용 범위를 확인하려면 만 18세 이상인지 직접 알려주시거나 해당 확인을 건너뛰어 주세요."
            return (
                "근비대 처방 근거는 건강한 성인 대상이에요. 만 18세 이상인가요? "
                "답하고 싶지 않으면 성인 여부를 건너뛸 수 있어요."
            )
        if context.experience.status in {"not_asked", "unknown"}:
            if context.experience.status == "unknown":
                return "운동 경력을 모르시는 걸로 기록했어요. 처음 시작·여러 해 쉬었다가 복귀·경험자 중 자기보고로 알려주시거나 경력 분류를 건너뛰어 주세요."
            return (
                "저항 운동을 처음 시작했거나 몇 년 쉬었다가 복귀했나요? "
                "경력은 자기보고로만 반영하며, 모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if context.experience.status == "provided" and context.experience.value == "experienced" and not (
            context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}
        ):
            return (
                "경험자 적합도 근거는 아직 없어요. 경력 기준을 건너뛰고 "
                "목표·다른 조건만 반영할까요?"
            )
        if context.minutes_per_session.status in {"not_asked", "unknown"}:
            if context.minutes_per_session_range.status == "provided":
                time_range = context.minutes_per_session_range.value
                return (
                    f"회당 {time_range.minimum_minutes}~{time_range.maximum_minutes}분 범위로 기록했어요. "
                    "초안에 사용할 목표 시간 하나를 직접 골라 주세요. 중간값을 대신 선택하지 않습니다."
                )
            if context.minutes_per_session.status == "unknown":
                return "회당 시간을 모르시는 걸로 기록했어요. 사용 가능한 분 수 하나를 알려주시거나 시간 조건을 건너뛰어 주세요."
            return (
                "한 번 운동할 때 가능한 시간을 알려주세요. 모르거나 답하고 싶지 않으면 "
                "시간 조건을 건너뛸 수 있어요."
            )
        if context.equipment.status in {"not_asked", "unknown"} or (
            context.equipment.value is not None
            and context.equipment.value.mode == "unknown"
        ):
            if context.equipment.status == "unknown" or (
                context.equipment.value is not None
                and context.equipment.value.mode == "unknown"
            ):
                return (
                    "장비를 모르신다고 기록했어요. 장소 이름으로 장비를 추측하지 않겠습니다. "
                    "사용 가능한 장비를 직접 적거나 ‘알아서 선택’으로 맡기거나, 장비 조건을 건너뛰어 주세요."
                )
            return (
                "사용할 수 있는 장비를 알려주세요. 모르거나 답하고 싶지 않으면 건너뛰어도 돼요. "
                "건너뛰면 보유 장비를 가정하지 않고 장비 제한 없이 후보를 살펴봅니다."
            )
        if context.preferences.status in {"not_asked", "unknown"}:
            if context.preferences.status == "unknown":
                return "선호를 모르시는 걸로 기록했어요. 선호 운동이나 피하고 싶은 동작을 알려주시거나 선호 항목을 건너뛸 수 있어요."
            return "선호하거나 피하고 싶은 동작이 있나요? 없거나 답하고 싶지 않으면 건너뛰어도 돼요."
        if context.known_constraints.status in {"not_asked", "unknown", "delegated"}:
            if context.known_constraints.status == "unknown":
                return "알고 있는 제약을 모르시는 걸로 기록했어요. 진단을 추정하지 않으며, 알고 있는 제한을 말하거나 제약 확인을 건너뛸 수 있어요."
            if context.known_constraints.status == "delegated":
                return "제약 확인을 맡기셨지만 제약이 없다고 추정하지 않겠습니다. 알고 있는 제한을 직접 알려주시거나 확인을 건너뛰어 주세요."
            return (
                "운동에서 고려할 제약이나 불편함을 알고 있나요? 진단명은 추정하지 않으며, "
                "모르거나 답하고 싶지 않으면 건너뛸 수 있어요."
            )
        if (
            context.goal.status == "provided"
            and context.goal.value in {"hypertrophy", "both"}
            and context.adult_eligibility.status == "provided"
            and context.adult_eligibility.value == "adult"
            and context.known_constraints.status == "provided"
            and not context.known_constraints.value
            and context.experience.status == "provided"
            and context.experience.value == "experienced"
            and context.weekly_direct_sets_by_muscle.status not in {"unknown", "skipped", "delegated"}
            and context.weekly_direct_sets_follow_up.status not in {"unknown", "skipped", "delegated"}
        ):
            focus_muscle_ids = {
                muscle_id
                for day_id in (context.workout_day_ids.value or [])
                for muscle_id in self._focus_muscle_ids_by_day.get(day_id, set())
            }
            reported = context.weekly_direct_sets_by_muscle.value or {}
            missing_muscle_ids = [
                muscle.id
                for muscle in self._catalog.muscles
                if muscle.id in focus_muscle_ids and muscle.id not in reported
            ]
            if missing_muscle_ids:
                stage_ids = missing_muscle_ids[:3]
                missing_names = ", ".join(self._muscle_names[muscle_id] for muscle_id in stage_ids)
                return (
                    "최근 한 주의 근육별 직접 세트 수는 경험자 처방을 현재 보고에 맞추기 위해 필요해요. "
                    "한 번에 세 근육씩 받을게요. "
                    f"이번 단계: {missing_names}. 형식: 근육명마다 지난 한 주의 직접 세트 수를 적어주세요. "
                    "값을 추정하지 않으며, 모르는 값은 비워 두거나 보고를 건너뛸 수 있어요."
                )
        return None

    def context_summary(self, context: RoutineContext) -> str:
        goal_names = {"hypertrophy": "근비대", "strength": "근력", "both": "근비대와 근력 진행", "other": "기타 목표"}
        experience_names = {"novice": "초보·복귀(자기보고)", "experienced": "경험자(자기보고)"}
        if context.workout_day_ids.status == "provided":
            workout_days = ", ".join(
                self._workout_day_names[item]
                for item in context.workout_day_ids.value or []
            )
        else:
            workout_days = self._field_status_label(context.workout_day_ids.status)
        if context.equipment.status == "provided" and context.equipment.value is not None:
            equipment = context.equipment.value
            if equipment.mode == "specified":
                equipment_text = ", ".join(
                    self._equipment_names[item] for item in equipment.equipment_ids
                )
            elif equipment.mode == "unknown":
                equipment_text = "모름"
            else:
                equipment_text = "선택 위임(보유 장비는 가정하지 않음)"
        else:
            equipment_text = self._field_status_label(context.equipment.status)

        if context.minutes_per_session.status == "provided":
            time_text = f"{context.minutes_per_session.value}분"
            if context.minutes_per_session_range.status == "provided":
                time_range = context.minutes_per_session_range.value
                time_text += f" (보고 범위 {time_range.minimum_minutes}~{time_range.maximum_minutes}분)"
        elif context.minutes_per_session_range.status == "provided":
            time_range = context.minutes_per_session_range.value
            time_text = f"{time_range.minimum_minutes}~{time_range.maximum_minutes}분 범위"
            if context.minutes_per_session.status in {"skipped", "delegated"}:
                time_text += f", 목표 {self._field_status_label(context.minutes_per_session.status)}"
            else:
                time_text += ", 목표 미선택"
        else:
            time_text = self._field_status_label(context.minutes_per_session.status)

        split_text = self._context_value_label(
            context.workout_split_type,
            {"ab": "2분할(A/B)"},
        )
        if context.workout_split_assignment.status == "provided":
            day_a, day_b = self._split_names(context.workout_split_assignment.value)
            split_text += f"; A: {day_a}, B: {day_b} (사용자 지정)"
        elif context.split_template is not None:
            day_a, day_b = self._split_names(context.split_template)
            confirmation = "확인됨" if context.split_template.confirmation_status == "confirmed" else "제안됨"
            split_text += f"; A: {day_a}, B: {day_b} ({confirmation})"
        elif context.workout_split_type.status == "provided":
            split_text += f"; A/B 구성: {self._field_status_label(context.workout_split_assignment.status)}"

        context_lines = [
            "제가 이해한 내용이에요. 확인하거나 채팅으로 수정해 주세요.",
            f"- 운동 부위: {workout_days}",
            f"- 주당 빈도: {self._value_with_unit(context.sessions_per_week, '회')}",
            f"- 운동 분할: {split_text}",
            f"- 목표: {self._context_value_label(context.goal, goal_names)}",
            f"- 운동 경력: {self._context_value_label(context.experience, experience_names)}",
            f"- 회당 가능 시간: {time_text}",
            f"- 장비: {equipment_text}",
            f"- 선호: {self._list_value_or_status(context.preferences)}",
            f"- 알고 있는 제약: {self._list_value_or_status(context.known_constraints)}",
        ]
        if context.goal.status == "provided" and context.goal.value in {"hypertrophy", "both"}:
            context_lines.append(
                f"- 성인 여부: {self._context_value_label(context.adult_eligibility, {'adult': '성인', 'minor': '미성년'})}"
            )
            if context.experience.status == "provided" and context.experience.value == "experienced":
                sets_text = self._weekly_sets_label(context.weekly_direct_sets_by_muscle)
                follow_up = context.weekly_direct_sets_follow_up
                if follow_up.status in {"unknown", "skipped", "delegated"}:
                    sets_text += f"; 추가 보고 {self._field_status_label(follow_up.status)}"
                context_lines.append(f"- 최근 근육별 주간 직접 세트: {sets_text}")
        context_lines.append("이 요약이 맞으면 ‘확인하고 루틴 만들기’를 눌러주세요.")
        return "\n".join(context_lines)

    @staticmethod
    def _field_status_label(status: str) -> str:
        return {"unknown": "모름", "skipped": "건너뜀", "delegated": "선택 위임"}.get(status, "미입력")

    @classmethod
    def _value_with_unit(cls, field: ContextField[int], unit: str) -> str:
        if field.status == "provided":
            return f"{field.value}{unit}"
        return cls._field_status_label(field.status)

    @classmethod
    def _context_value_label(
        cls,
        field: ContextField[str],
        labels: dict[str, str],
    ) -> str:
        if field.status == "provided" and field.value is not None:
            return labels[field.value]
        return cls._field_status_label(field.status)

    @classmethod
    def _list_value_or_status(cls, field: ContextField[list[str]]) -> str:
        if field.status != "provided":
            return cls._field_status_label(field.status)
        return ", ".join(field.value or []) or "없음"
    def _weekly_sets_label(self, field: ContextField[dict[str, int]]) -> str:
        if field.status != "provided":
            return self._field_status_label(field.status)
        return ", ".join(
            f"{self._muscle_names.get(muscle_id, muscle_id)} {sets}세트"
            for muscle_id, sets in sorted((field.value or {}).items())
        ) or "없음"
    @staticmethod
    def _normalize_catalog_text(value: str) -> str:
        return " ".join(
            "".join(char.casefold() if char.isalnum() else " " for char in value).split()
        )

    def has_unresolved_constraints(self, field: ContextField[list[str]]) -> bool:
        if field.status != "provided":
            return False
        no_constraint_values = {
            "none",
            "no constraints",
            "no restrictions",
            "no limitation",
            "no limitations",
            "no known constraints",
            "no physical restrictions",
            "no injuries",
            "제약 사항 없음",
            "제약은 없어요",
            "제약 없음",
            "현재 제약 없음",
            "제한 없음",
            "운동 제한 없음",
            "불편함 없음",
            "없음",
        }
        return any(
            normalized and normalized not in no_constraint_values
            for value in field.value or []
            if (normalized := self._normalize_catalog_text(value))
        )
