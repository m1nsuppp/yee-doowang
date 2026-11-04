export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
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

export type ChatResponse = {
  reply: string;
  exercises: RecommendedExercise[];
};

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function sendChatMessage(
  messages: ChatMessage[],
  signal: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch(`${apiBaseUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
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
