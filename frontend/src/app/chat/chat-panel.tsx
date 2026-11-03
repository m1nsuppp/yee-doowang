"use client";

import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type ChatMessage,
  type RecommendedExercise,
  sendChatMessage,
} from "../../lib/chat-api";

type DisplayMessage = ChatMessage & {
  id: string;
  exercises?: RecommendedExercise[];
};

export default function ChatPanel() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeRequestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    transcript.scrollTop =
      messages.length === 0 && !isSending && error === null
        ? 0
        : transcript.scrollHeight;
  }, [messages.length, isSending, error]);

  async function requestReply(conversation: DisplayMessage[]) {
    const controller = new AbortController();
    activeRequestRef.current?.abort();
    activeRequestRef.current = controller;
    setError(null);
    setIsSending(true);

    try {
      const response = await sendChatMessage(
        conversation.slice(-30).map(({ role, content }) => ({ role, content })),
        controller.signal,
      );
      if (activeRequestRef.current !== controller) return;

      const lastMessage = conversation[conversation.length - 1];
      setMessages([
        ...conversation,
        {
          id: `${lastMessage.id}-reply`,
          role: "assistant",
          content: response.reply,
          exercises: response.exercises,
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
    void requestReply(conversation);
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
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-[#e2e6de] px-4 sm:px-8">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-xl bg-[#183d31] text-xs font-black tracking-tight text-[#d8f36c]">
            YD
          </span>
          <div className="flex items-baseline gap-2">
            <span className="font-extrabold tracking-tight">이두왕</span>
            <span className="text-xs text-[#718077]">PushDay</span>
          </div>
        </div>
        <button
          className="rounded-full border border-[#d9ddd4] px-4 py-2 text-sm font-semibold transition hover:border-[#183d31] hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
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
                {message.exercises && message.exercises.length > 0 && (
                  <ul className="mt-4 grid gap-3 sm:grid-cols-2">
                    {message.exercises.map((exercise) => (
                      <li
                        key={exercise.source_id}
                        className="rounded-2xl border border-[#e2e6de] bg-white p-4 text-[#162720]"
                      >
                        <p className="font-bold text-[#183d31]">
                          {exercise.name_ko ?? exercise.name}
                        </p>
                        <p className="mt-2 text-xs leading-5 text-[#68756d]">
                          {exercise.primary_muscle_ko} · {exercise.equipment_ko}
                          {exercise.movement_pattern_ko && (
                            <>
                              <br />
                              {exercise.movement_pattern_ko}
                            </>
                          )}
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
              운동 후보를 찾고 있어요…
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
                  onClick={() => void requestReply(messages)}
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
            placeholder="메시지를 입력하세요"
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
