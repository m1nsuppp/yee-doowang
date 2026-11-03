"use client";

import { type FormEvent, useState } from "react";

import {
  type ChatMessage,
  type RecommendedExercise,
  sendChatMessage,
} from "../../lib/chat-api";

type DisplayMessage = ChatMessage & {
  id: string;
  exercises?: RecommendedExercise[];
};

const openingMessage: DisplayMessage = {
  id: "opening",
  role: "assistant",
  content:
    "PushDay 운동 추천을 도와드릴게요. 사용할 수 있는 장비를 함께 알려주시면 조건에 맞는 후보를 찾아볼게요.",
};

export default function ChatPanel() {
  const [messages, setMessages] = useState<DisplayMessage[]>([openingMessage]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || isSending) return;

    const userMessage: DisplayMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
    };
    const conversation = [...messages, userMessage];
    setMessages(conversation);
    setDraft("");
    setError(null);
    setIsSending(true);

    try {
      const response = await sendChatMessage(
        conversation.slice(-30).map(({ role, content }) => ({ role, content })),
      );
      setMessages([
        ...conversation,
        {
          id: `${userMessage.id}-reply`,
          role: "assistant",
          content: response.reply,
          exercises: response.exercises,
        },
      ]);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "채팅 응답을 받지 못했습니다.",
      );
    } finally {
      setIsSending(false);
    }
  }

  return (
    <section className="overflow-hidden rounded-3xl border border-[#e2e6de] bg-white shadow-[0_24px_70px_-44px_rgba(24,61,49,0.45)]">
      <div
        className="max-h-[min(62svh,620px)] min-h-80 space-y-5 overflow-y-auto p-5 sm:p-7"
        role="log"
        aria-live="polite"
        aria-label="대화 내용"
      >
        {messages.map((message) => (
          <article
            key={message.id}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[92%] sm:max-w-[82%] ${
                message.role === "user"
                  ? "rounded-3xl rounded-br-md bg-[#183d31] px-4 py-3 text-white"
                  : "w-full"
              }`}
            >
              <p
                className={`whitespace-pre-wrap text-sm leading-7 ${
                  message.role === "assistant" ? "text-[#33443b]" : ""
                }`}
              >
                {message.content}
              </p>
              {message.exercises && message.exercises.length > 0 && (
                <ul className="mt-4 grid gap-3 sm:grid-cols-2">
                  {message.exercises.map((exercise) => (
                    <li
                      key={exercise.source_id}
                      className="rounded-2xl border border-[#e2e6de] bg-[#f8f9f5] p-4"
                    >
                      <p className="font-bold text-[#183d31]">
                        {exercise.name_ko}
                      </p>
                      <p className="mt-2 text-xs leading-5 text-[#68756d]">
                        {exercise.primary_muscle_ko} · {exercise.equipment_ko}
                        <br />
                        {exercise.movement_pattern_ko}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </article>
        ))}
        {isSending && (
          <p className="text-sm text-[#68756d]" role="status">
            조건을 확인하고 운동 후보를 찾고 있어요…
          </p>
        )}
        {error && (
          <p
            className="rounded-xl bg-[#fff2ed] px-4 py-3 text-sm text-[#8b3528]"
            role="alert"
          >
            {error}
          </p>
        )}
      </div>

      <form
        className="border-t border-[#e9ece6] bg-[#fbfcf9] p-4 sm:p-5"
        onSubmit={submitMessage}
      >
        <label className="sr-only" htmlFor="chat-message">
          메시지 입력
        </label>
        <div className="flex items-end gap-3">
          <textarea
            id="chat-message"
            className="min-h-12 flex-1 resize-y rounded-2xl border border-[#dce2d9] bg-white px-4 py-3 text-sm leading-6 outline-none transition placeholder:text-[#929c94] focus:border-[#527c42]"
            placeholder="예: 덤벨과 맨몸으로 푸시데이 운동을 추천해줘"
            rows={2}
            maxLength={2000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={isSending}
          />
          <button
            className="min-h-12 rounded-2xl bg-[#183d31] px-5 text-sm font-bold text-white transition hover:bg-[#285c48] disabled:cursor-not-allowed disabled:opacity-50"
            type="submit"
            disabled={isSending || !draft.trim()}
          >
            보내기
          </button>
        </div>
        <p className="mt-3 text-xs leading-5 text-[#7b877e]">
          현재 카탈로그에 등록된 PushDay 운동 후보만 안내합니다. 세트·횟수
          처방은 제공하지 않습니다.
        </p>
      </form>
    </section>
  );
}
