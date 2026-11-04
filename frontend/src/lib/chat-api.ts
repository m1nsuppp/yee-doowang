export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ContextField<T> = {
  status: "not_asked" | "provided" | "unknown" | "skipped";
  value: T | null;
};

export type EquipmentIntent = {
  mode: "specified" | "unknown" | "delegate_any";
  equipment_ids: string[];
};

export type RoutineContext = {
  workout_day_ids: ContextField<string[]>;
  goal: ContextField<"hypertrophy" | "strength" | "other">;
  experience: ContextField<"novice" | "experienced">;
  sessions_per_week: ContextField<number>;
  minutes_per_session: ContextField<number>;
  equipment: ContextField<EquipmentIntent>;
  preferences: ContextField<string[]>;
  known_constraints: ContextField<string[]>;
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

export type RoutineDraft = {
  sessions_per_week: number | null;
  minutes_per_session: number | null;
  sessions: RoutineSession[];
};

export type ConversationState = {
  phase: "collecting_context" | "confirming_context" | "reviewing_routine";
  context: RoutineContext;
  routine: RoutineDraft | null;
};

export type ChatAction = "message" | "confirm_context";

export type ChatResponse = {
  reply: string;
  state: ConversationState;
  exercises: RecommendedExercise[];
};

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function createInitialConversationState(): ConversationState {
  const field = <T>(): ContextField<T> => ({
    status: "not_asked",
    value: null,
  });
  return {
    phase: "collecting_context",
    context: {
      workout_day_ids: field<string[]>(),
      goal: field<"hypertrophy" | "strength" | "other">(),
      experience: field<"novice" | "experienced">(),
      sessions_per_week: field<number>(),
      minutes_per_session: field<number>(),
      equipment: field<EquipmentIntent>(),
      preferences: field<string[]>(),
      known_constraints: field<string[]>(),
    },
    routine: null,
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
