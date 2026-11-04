import type {
  ContextField,
  ConversationState,
  RoutineContext,
} from "../../lib/chat-api";

const phaseLabels: Record<ConversationState["phase"], string> = {
  collecting_context: "조건 상담 중",
  confirming_context: "최종 조건 확인 중",
  confirming_split: "A/B 구성 확인 중",
  reviewing_routine: "루틴 검토 중",
};

const fieldStatusLabels: Record<ContextField<unknown>["status"], string> = {
  not_asked: "아직 확인 전",
  provided: "값 확인 필요",
  unknown: "모름으로 답함",
  skipped: "사용자가 건너뜀",
  delegated: "선택 위임",
};

const goalLabels = {
  hypertrophy: "근비대",
  strength: "근력",
  both: "근비대·근력",
  other: "기타 목표",
};

// Display names from backend/data/exercise-catalog.json; unknown IDs stay unnamed.
const equipmentLabels: Partial<Record<string, string>> = {
  band: "밴드",
  barbell: "바벨",
  body_weight: "맨몸",
  bosu_ball: "보수볼",
  cable: "케이블",
  dumbbell: "덤벨",
  elliptical_machine: "일립티컬 머신",
  ez_barbell: "EZ바",
  hammer: "슬레지 해머",
  kettlebell: "케틀벨",
  leverage_machine: "레버 머신",
  medicine_ball: "메디신볼",
  olympic_barbell: "올림픽 바벨",
  resistance_band: "저항 밴드",
  roller: "롤러",
  rope: "로프",
  skierg_machine: "SkiErg 머신",
  sled_machine: "슬레드 머신",
  smith_machine: "스미스 머신",
  stability_ball: "짐볼",
  stationary_bike: "실내 자전거",
  stepmill_machine: "스텝밀",
  tire: "타이어",
  trap_bar: "트랩바",
  upper_body_ergometer: "상체 에르고미터",
  wheel_roller: "AB 휠",
};

const workoutDayLabels: Partial<Record<string, string>> = {
  push_day: "가슴·어깨·삼두 운동",
  back_day: "등·허리 운동",
  biceps_day: "이두 운동",
  legs_day: "하체 운동",
  forearms_day: "전완·손목 운동",
  scapula_day: "견갑·전거근 운동",
  core_day: "코어 보조 운동",
  abs_day: "복근 운동",
  obliques_day: "복사근 운동",
};

function fieldLabel<T>(field: ContextField<T>, format: (value: T) => string) {
  return field.status === "provided" && field.value !== null
    ? format(field.value)
    : fieldStatusLabels[field.status];
}

function namedItems(ids: string[], labels: Partial<Record<string, string>>) {
  const names = ids.flatMap((id) => {
    const label = labels[id];
    return label ? [label] : [];
  });
  const unnamedCount = ids.length - names.length;
  if (unnamedCount > 0) names.push(`표시 이름 없는 항목 ${unnamedCount}개`);
  return names.join(", ") || "기록된 항목 없음";
}

function targetTimeLabel(context: RoutineContext) {
  const field = context.minutes_per_session;
  if (field.status === "skipped") return "직접 건너뜀 · 시간 목표 미설정";
  if (field.status === "provided" && field.value !== null) {
    return `${field.value}분 · 직접 선택`;
  }
  if (context.minutes_per_session_range.status === "provided") {
    return "범위로 진행 · 별도 목표 불필요";
  }
  if (field.status === "delegated") return "선택 대기 · 추천 요청";
  if (field.status === "unknown") return "확인 대기 · 가능 시간 미제공";
  return "확인 전";
}

function splitLabel(context: RoutineContext) {
  const split = fieldLabel(context.workout_split_type, () => "A/B 2분할");
  if (context.workout_split_type.status !== "provided") return split;
  const template =
    context.workout_split_assignment.status === "provided"
      ? context.workout_split_assignment.value
      : context.split_template;
  if (template) {
    const confirmation =
      template.confirmation_status === "proposed"
        ? "제안 · 아직 확인 전"
        : template.confirmation_status === "confirmed"
          ? "구성 확인됨"
          : "직접 정한 구성";
    return `${split} · ${confirmation}\nA: ${namedItems(template.day_a_ids, workoutDayLabels)}\nB: ${namedItems(template.day_b_ids, workoutDayLabels)}`;
  }
  return `${split} · 구성 ${context.split_proposal_rejected ? "다시 상담 중" : fieldStatusLabels[context.workout_split_assignment.status]}`;
}

export default function ConsultationSummary({
  state,
}: {
  state: ConversationState;
}) {
  const { context } = state;
  const availableTime = fieldLabel(
    context.minutes_per_session_range,
    (range) => `${range.minimum_minutes}–${range.maximum_minutes}분`,
  );
  const targetTime = targetTimeLabel(context);
  const hasTimeContext =
    context.minutes_per_session_range.status !== "not_asked" ||
    context.minutes_per_session.status !== "not_asked";
  const conditions = [
    {
      label: "운동 빈도",
      value: fieldLabel(context.sessions_per_week, (value) => `주 ${value}회`),
    },
    { label: "운동 분할", value: splitLabel(context) },
    {
      label: "운동 목표",
      value: fieldLabel(context.goal, (value) => goalLabels[value]),
    },
    ...(context.workout_day_ids.status !== "not_asked"
      ? [
          {
            label: "운동 부위",
            value: fieldLabel(context.workout_day_ids, (value) =>
              namedItems(value, workoutDayLabels),
            ),
          },
        ]
      : []),
    ...(context.minutes_per_session_range.status !== "not_asked"
      ? [{ label: "가능 시간", value: availableTime }]
      : []),
    { label: "목표 시간", value: targetTime },
    {
      label: "사용 장비",
      value:
        context.equipment.status === "delegated"
          ? "선택 위임 · 보유 장비 가정 없음"
          : fieldLabel(context.equipment, (value) => {
              if (value.mode === "unknown") return "모름으로 답함";
              if (value.mode === "delegate_any") {
                return "선택 위임 · 보유 장비 가정 없음";
              }
              return namedItems(value.equipment_ids, equipmentLabels);
            }),
    },
  ];

  return (
    <aside
      className="shrink-0 border-b border-[#e2e6de] bg-[#f7faf5] px-4 py-2 sm:px-8"
      aria-label="루틴 상담 현황"
    >
      <details className="mx-auto max-h-[30dvh] max-w-3xl overflow-y-auto overscroll-contain text-xs leading-5 text-[#52645a]">
        <summary className="cursor-pointer rounded-lg px-1 py-1 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#527c42]">
          <span className="font-semibold text-[#183d31]">
            루틴 상담 · {phaseLabels[state.phase]}
          </span>
          <span className="ml-2">기억한 조건 보기</span>
          {hasTimeContext && (
            <span className="mt-1 block pl-4">
              {context.minutes_per_session_range.status !== "not_asked" && (
                <span className="mr-3 inline-block">
                  가능 시간 {availableTime}
                </span>
              )}
              <span className="inline-block">목표 시간 {targetTime}</span>
            </span>
          )}
        </summary>
        <dl className="mt-2 space-y-2 border-t border-[#e2e6de] px-1 pt-3 pb-2">
          {conditions.map((condition) => (
            <div
              key={condition.label}
              className="grid grid-cols-[5rem_minmax(0,1fr)] gap-3"
            >
              <dt>{condition.label}</dt>
              <dd className="whitespace-pre-line break-words text-[#33443b]">
                {condition.value}
              </dd>
            </div>
          ))}
        </dl>
        <p className="px-1 pb-2">바꾸고 싶은 조건은 채팅으로 말씀해 주세요.</p>
      </details>
    </aside>
  );
}
