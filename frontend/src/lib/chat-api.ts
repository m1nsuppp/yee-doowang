export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ContextField<T> = {
  status: "not_asked" | "provided" | "unknown" | "skipped" | "delegated";
  value: T | null;
};

export type EquipmentIntent = {
  mode: "specified" | "unknown" | "delegate_any";
  equipment_ids: string[];
};

export type WorkoutSplitTemplate = {
  day_a_ids: string[];
  day_b_ids: string[];
  confirmation_status: "user_provided" | "proposed" | "confirmed";
};

export type WorkoutDayRecommendation = {
  workout_day_ids: string[];
  rationale: string;
};

export type RoutineContext = {
  workout_day_ids: ContextField<string[]>;
  workout_split_type: ContextField<"ab">;
  workout_split_assignment: ContextField<WorkoutSplitTemplate>;
  goal: ContextField<"hypertrophy" | "strength" | "both" | "other">;
  experience: ContextField<"novice" | "experienced">;
  sessions_per_week: ContextField<number>;
  minutes_per_session: ContextField<number>;
  minutes_per_session_range: ContextField<{
    minimum_minutes: number;
    maximum_minutes: number;
  }>;
  equipment: ContextField<EquipmentIntent>;
  preferences: ContextField<string[]>;
  known_constraints: ContextField<string[]>;
  adult_eligibility: ContextField<"adult" | "minor">;
  weekly_direct_sets_by_muscle: ContextField<Record<string, number>>;
  weekly_direct_sets_follow_up: ContextField<"remaining">;
  split_proposal_rejected: boolean;
  split_template: WorkoutSplitTemplate | null;
};

export type RecommendedExercise = {
  source_id: string;
  name: string;
  name_ko: string | null;
  primary_muscle_ko: string;
  secondary_muscles_ko: string[];
  equipment_ko: string;
  movement_pattern_ko: string | null;
  technical_complexity: "low" | "moderate" | "high" | null;
};

export type RoutineExercise = {
  exercise: RecommendedExercise;
  rationale: string;
  alternatives: RecommendedExercise[];
};

export type RoutineSession = {
  index: number;
  workout_day_id: string;
  workout_day_name_ko: string;
  exercises: RoutineExercise[];
};

export type PrescriptionEvidenceSource = {
  id: string;
  title: string;
  url: string;
  doi: string;
  year: number;
  license: string | null;
  scope: string;
  limitations: string;
};

export type WeeklyDirectSetTarget = {
  muscle_id: string;
  muscle_name_ko: string;
  sets_per_week: number;
  basis: "source_starting_point" | "user_reported";
};

export type HypertrophyPrescription = {
  population_scope: string;
  weekly_direct_sets: WeeklyDirectSetTarget[];
  higher_volume_reference_sets_per_muscle_per_week: number;
  repetition_range_rm: [number, number];
  rest_seconds_range: [number, number];
  progression: {
    extra_repetitions_min: number;
    extra_repetitions_max: number;
    load_increase_percent_min: number;
    load_increase_percent_max: number;
    instruction: string;
  };
  sources: PrescriptionEvidenceSource[];
  caveats: string[];
};

export type RoutineDraft = {
  sessions_per_week: number | null;
  minutes_per_session: number | null;
  sessions: RoutineSession[];
  hypertrophy_prescription: HypertrophyPrescription | null;
  prescription_note: string | null;
};

export type ConversationState = {
  mode: "general" | "routine";
  phase:
    | "collecting_context"
    | "confirming_context"
    | "confirming_split"
    | "reviewing_routine";
  context: RoutineContext;
  routine: RoutineDraft | null;
  workout_day_recommendation: WorkoutDayRecommendation | null;
};

export type ChatAction = "message" | "confirm_context";

export type QuickReply = {
  label: string;
  message: string;
};

export type ChatResponse = {
  reply: string;
  state: ConversationState;
  exploration_exercises: RecommendedExercise[];
  quick_replies: QuickReply[];
};

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function createInitialConversationState(): ConversationState {
  const field = <T>(): ContextField<T> => ({
    status: "not_asked",
    value: null,
  });
  return {
    mode: "general",
    phase: "collecting_context",
    context: {
      workout_day_ids: field<string[]>(),
      workout_split_type: field<"ab">(),
      workout_split_assignment: field<WorkoutSplitTemplate>(),
      goal: field<"hypertrophy" | "strength" | "both" | "other">(),
      experience: field<"novice" | "experienced">(),
      sessions_per_week: field<number>(),
      minutes_per_session: field<number>(),
      minutes_per_session_range: field<{
        minimum_minutes: number;
        maximum_minutes: number;
      }>(),
      equipment: field<EquipmentIntent>(),
      preferences: field<string[]>(),
      known_constraints: field<string[]>(),
      adult_eligibility: field<"adult" | "minor">(),
      weekly_direct_sets_by_muscle: field<Record<string, number>>(),
      weekly_direct_sets_follow_up: field<"remaining">(),
      split_proposal_rejected: false,
      split_template: null,
    },
    routine: null,
    workout_day_recommendation: null,
  };
}

export async function sendChatMessage(
  messages: ChatMessage[],
  state: ConversationState,
  action: ChatAction,
  signal: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch(`${apiBaseUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, state, action }),
    signal,
  });

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? body.detail
        : undefined;
    throw new Error(
      typeof detail === "string"
        ? detail
        : `채팅 요청에 실패했습니다. (${response.status})`,
    );
  }

  return (await response.json()) as ChatResponse;
}
