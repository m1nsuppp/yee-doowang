import Link from "next/link";

import ChatPanel from "./chat-panel";

export default function ChatPage() {
  return (
    <main className="min-h-svh bg-[#f5f5ef] text-[#162720]">
      <header className="mx-auto flex w-full max-w-4xl items-center justify-between px-5 py-5 sm:px-8 sm:py-7">
        <Link href="/" className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-[#183d31] text-sm font-black tracking-tight text-[#d8f36c]">
            YD
          </span>
          <span className="text-lg font-extrabold tracking-tight">이두왕</span>
        </Link>
        <Link
          href="/"
          className="rounded-full border border-[#d9ddd4] px-4 py-2 text-sm font-semibold transition hover:border-[#183d31] hover:bg-white"
        >
          홈으로
        </Link>
      </header>

      <section className="mx-auto w-full max-w-4xl px-5 pb-12 pt-5 sm:px-8 sm:pb-20 sm:pt-10">
        <p className="text-xs font-bold tracking-[0.22em] text-[#537064] sm:text-sm">
          PUSH DAY COACH
        </p>
        <h1 className="mt-4 text-3xl font-black leading-tight tracking-[-0.04em] sm:text-5xl">
          대화로 푸시 운동을 골라요.
        </h1>
        <p className="mb-8 mt-4 max-w-2xl text-sm leading-7 text-[#59665e] sm:mb-10 sm:text-base">
          운동일과 장비 조건을 알려주세요. 규칙 엔진이 카탈로그에서 후보를
          추리고, AI 코치가 선택 이유를 설명합니다.
        </p>
        <ChatPanel />
      </section>
    </main>
  );
}
