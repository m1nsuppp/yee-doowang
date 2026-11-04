"use client";

import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type ChatAction,
  type ChatMessage,
  type ConversationState,
  createInitialConversationState,
  type RecommendedExercise,
  type RoutineDraft,
  sendChatMessage,
} from "../../lib/chat-api";

type DisplayMessage = ChatMessage & {
  id: string;
  explorationExercises?: RecommendedExercise[];
  routine?: RoutineDraft | null;
  state?: ConversationState;
};
const technicalComplexityLabels = {
  low: "낮음",
  moderate: "보통",
  high: "높음",
} as const;
const technicalComplexitySourceUrl =
  "https://pmc.ncbi.nlm.nih.gov/articles/PMC11873903/";

function ExerciseCard({ exercise }: { exercise: RecommendedExercise }) {
  return (
    <div className="rounded-2xl border border-[#e2e6de] bg-white p-4 text-[#162720]">
      <p className="font-bold text-[#183d31]">
        {exercise.name_ko ? (
          exercise.name_ko
        ) : (
          <>
            원문 운동명: <span lang="en">{exercise.name}</span>
          </>
        )}
      </p>
      <p className="mt-2 text-xs leading-5 text-[#68756d]">
        {exercise.primary_muscle_ko} · {exercise.equipment_ko}
        {exercise.secondary_muscles_ko.length > 0 && (
          <>
            <br />
            보조 근육: {exercise.secondary_muscles_ko.join(" · ")}
          </>
        )}
        {exercise.movement_pattern_ko && (
          <>
            <br />
            {exercise.movement_pattern_ko}
          </>
        )}
        {exercise.technical_complexity && (
          <>
            <br />
            전문가 평가 기술 요구도:{" "}
            {technicalComplexityLabels[exercise.technical_complexity]}{" "}
            <a
              className="underline underline-offset-2"
              href={technicalComplexitySourceUrl}
              target="_blank"
              rel="noreferrer"
            >
              연구 출처
            </a>
          </>
        )}
      </p>
    </div>
  );
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [conversationState, setConversationState] = useState(
    createInitialConversationState,
  );
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const lastActionRef = useRef<ChatAction>("message");

  const latestAssistantMessageId = [...messages]
    .reverse()
    .find((message) => message.role === "assistant")?.id;
  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    transcript.scrollTop =
      messages.length === 0 && !isSending && error === null
        ? 0
        : transcript.scrollHeight;
  }, [messages.length, isSending, error]);

  async function requestReply(
    conversation: DisplayMessage[],
    state: ConversationState,
    action: ChatAction,
  ) {
    const controller = new AbortController();
    activeRequestRef.current?.abort();
    activeRequestRef.current = controller;
    lastActionRef.current = action;
    setError(null);
    setIsSending(true);

    try {
      const response = await sendChatMessage(
        conversation.slice(-30).map(({ role, content }) => ({ role, content })),
        state,
        action,
        controller.signal,
      );
      if (activeRequestRef.current !== controller) return;

      const lastMessage = conversation[conversation.length - 1];
      setConversationState(response.state);
      setMessages([
        ...conversation,
        {
          id: `${lastMessage.id}-reply`,
          role: "assistant",
          content: response.reply,
          explorationExercises: response.exploration_exercises,
          routine: response.state.routine,
          state: response.state,
        },
      ]);
    } catch (caughtError) {
      if (
        activeRequestRef.current !== controller ||
        controller.signal.aborted
      ) {
        return;
      }
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "채팅 응답을 받지 못했습니다.",
      );
    } finally {
      if (activeRequestRef.current === controller) {
        activeRequestRef.current = null;
        setIsSending(false);
      }
    }
  }

  function submitMessage(event: FormEvent<HTMLFormElement>) {
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
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    void requestReply(conversation, conversationState, "message");
  }

  function confirmContext() {
    if (isSending || conversationState.phase !== "confirming_context") return;
    const userMessage: DisplayMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: "확인하고 루틴 만들기",
    };
    const conversation = [...messages, userMessage];
    setMessages(conversation);
    void requestReply(conversation, conversationState, "confirm_context");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return;
    }
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function startNewChat() {
    activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    setMessages([]);
    setDraft("");
    setError(null);
    setIsSending(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
    }

    setConversationState(createInitialConversationState());
    lastActionRef.current = "message";
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-[#e2e6de] px-4 sm:px-8">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="grid size-9 place-items-center rounded-xl bg-[#183d31] text-xs font-black tracking-tight text-[#d8f36c]">
            YD
          </span>
          <div className="flex min-w-0 flex-1 items-baseline gap-2">
            <span className="shrink-0 whitespace-nowrap font-extrabold tracking-tight">
              이두왕
            </span>
            <span className="break-keep min-w-0 flex-1 text-xs leading-4 text-[#718077]">
              푸시 · 등/허리 · 이두 · 전완 · 하체 · 견갑 · 코어 · 복근 · 복사근
            </span>
          </div>
        </div>
        <button
          className="shrink-0 whitespace-nowrap rounded-full border border-[#d9ddd4] px-4 py-2 text-sm font-semibold transition hover:border-[#183d31] hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
          type="button"
          onClick={startNewChat}
          disabled={messages.length === 0 && !draft.trim() && !isSending}
        >
          새 대화
        </button>
      </header>

      <div
        ref={transcriptRef}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8"
        role="log"
        aria-live="polite"
        aria-label="대화 내용"
      >
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
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
                {message.role === "assistant" && (
                  <p className="mb-2 text-xs font-semibold text-[#718077]">
                    이두왕
                  </p>
                )}
                <p
                  className={`whitespace-pre-wrap text-sm leading-7 ${
                    message.role === "assistant" ? "text-[#33443b]" : ""
                  }`}
                >
                  {message.content}
                </p>
                {message.routine && (
                  <section className="mt-4 space-y-4">
                    <p className="text-xs leading-5 text-[#68756d]">
                      기술 요구도는 출처에서 평가된 운동에만 표시합니다.
                      미평가는 개인 적합성이나 안전성을 뜻하지 않습니다.
                      루틴에는 근거가 없는 세트·횟수·중량을 넣지 않습니다.
                    </p>
                    {message.routine.minutes_per_session !== null && (
                      <p className="text-xs text-[#68756d]">
                        회당 목표 시간: {message.routine.minutes_per_session}분.
                        운동별 소요 시간 자료가 없어 완료 시간은 보장하지
                        않습니다.
                      </p>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2">
                      {message.routine.sessions.map((session) => (
                        <section
                          className="rounded-2xl border border-[#e2e6de] bg-[#fbfcf9] p-4"
                          key={session.index}
                        >
                          <h3 className="font-bold text-[#183d31]">
                            운동 {session.index} · {session.workout_day_name_ko}
                          </h3>
                          <ol className="mt-3 grid gap-3">
                            {session.exercises.map((planned) => (
                              <li
                                key={`${session.index}-${planned.exercise.source_id}`}
                              >
                                <ExerciseCard exercise={planned.exercise} />
                                <p className="mt-2 text-xs leading-5 text-[#68756d]">
                                  선택 이유: {planned.rationale}
                                </p>
                                {planned.alternatives.length > 0 && (
                                  <details className="mt-2 text-xs text-[#52645a]">
                                    <summary className="cursor-pointer font-semibold">
                                      대안 운동 보기
                                    </summary>
                                    <ul className="mt-2 grid gap-2">
                                      {planned.alternatives.map((exercise) => (
                                        <li key={exercise.source_id}>
                                          <ExerciseCard exercise={exercise} />
                                        </li>
                                      ))}
                                    </ul>
                                  </details>
                                )}
                              </li>
                            ))}
                          </ol>
                        </section>
                      ))}
                    </div>
                  </section>
                )}
                {message.explorationExercises &&
                  message.explorationExercises.length > 0 && (
                    <details className="mt-4 text-sm text-[#52645a]">
                      <summary className="cursor-pointer font-semibold">
                        나머지 조건 일치 후보 탐색 (
                        {message.explorationExercises.length})
                      </summary>
                      <p className="mt-2 text-xs leading-5 text-[#68756d]">
                        기본 루틴 추천과 대안에서 제외된 후보입니다. 부위·장비
                        조건에 일치하며, 카드의 표적 근육과 장비 정보를
                        확인하세요. 미평가는 낮은 난이도나 개인의
                        적합성·안전성을 뜻하지 않습니다.
                      </p>
                      <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                        {message.explorationExercises.map((exercise) => (
                          <li key={exercise.source_id}>
                            <ExerciseCard exercise={exercise} />
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                {message.id === latestAssistantMessageId &&
                  conversationState.phase === "confirming_context" && (
                    <button
                      className="mt-4 rounded-xl bg-[#183d31] px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
                      type="button"
                      onClick={confirmContext}
                      disabled={isSending}
                    >
                      확인하고 루틴 만들기
                    </button>
                  )}
              </div>
            </article>
          ))}
          {isSending && (
            <p className="text-sm text-[#68756d]" role="status">
              {conversationState.phase === "confirming_context"
                ? "주간 루틴 초안을 만들고 있어요…"
                : "대화 맥락을 확인하고 있어요…"}
            </p>
          )}
          {error && (
            <div
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[#fff2ed] px-4 py-3 text-sm text-[#8b3528]"
              role="alert"
            >
              <p>{error}</p>
              {messages[messages.length - 1]?.role === "user" && (
                <button
                  className="font-bold underline underline-offset-2"
                  type="button"
                  onClick={() =>
                    void requestReply(
                      messages,
                      conversationState,
                      lastActionRef.current,
                    )
                  }
                >
                  다시 시도
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <form
        className="shrink-0 border-t border-[#e2e6de] bg-white px-3 py-3 sm:px-6 sm:py-4"
        onSubmit={submitMessage}
      >
        <label className="sr-only" htmlFor="chat-message">
          메시지 입력
        </label>
        <div className="mx-auto flex max-w-3xl items-end gap-3 rounded-3xl border border-[#dce2d9] bg-[#fbfcf9] p-2 focus-within:border-[#527c42]">
          <textarea
            ref={textareaRef}
            id="chat-message"
            className="max-h-40 min-h-11 flex-1 resize-none overflow-y-auto bg-transparent px-3 py-3 text-sm leading-6 outline-none placeholder:text-[#929c94]"
            placeholder="운동 부위·빈도를 말하거나 '모름', '건너뛰기'라고 답해주세요"
            rows={1}
            maxLength={2000}
            value={draft}
            onChange={(event) => {
              setDraft(event.currentTarget.value);
              event.currentTarget.style.height = "auto";
              event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 160)}px`;
            }}
            onKeyDown={handleKeyDown}
          />
          <button
            className="min-h-11 shrink-0 rounded-2xl bg-[#183d31] px-4 text-sm font-bold text-white transition hover:bg-[#285c48] disabled:cursor-not-allowed disabled:opacity-40"
            type="submit"
            disabled={isSending || !draft.trim()}
          >
            보내기
          </button>
        </div>
      </form>
    </section>
  );
}
