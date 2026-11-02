const coachingAreas = [
  {
    number: "01",
    label: "TRAINING",
    title: "목표에 맞는 운동",
    description: "운동 목표와 조건을 바탕으로 적합한 선택지를 좁혀갑니다.",
  },
  {
    number: "02",
    label: "COACHING",
    title: "이해하기 쉬운 코칭",
    description: "복잡한 운동 정보를 실제로 이어갈 수 있는 안내로 풀어냅니다.",
  },
  {
    number: "03",
    label: "PROGRESS",
    title: "꾸준히 쌓이는 기록",
    description: "사용자의 목표와 운동 경험을 반영하는 코칭을 지향합니다.",
  },
];

export default function Home() {
  return (
    <main className="min-h-svh bg-[#f5f5ef] text-[#162720]">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5 sm:px-8 sm:py-7">
        <a
          href="#home"
          className="flex items-center gap-3"
          aria-label="이두왕 홈"
        >
          <span className="grid size-10 place-items-center rounded-xl bg-[#183d31] text-sm font-black tracking-tight text-[#d8f36c]">
            YD
          </span>
          <span className="text-lg font-extrabold tracking-tight">이두왕</span>
        </a>
        <a
          href="#approach"
          className="rounded-full border border-[#d9ddd4] px-4 py-2 text-sm font-semibold transition hover:border-[#183d31] hover:bg-white"
        >
          코칭 방식 <span aria-hidden="true">↘</span>
        </a>
      </header>

      <section
        id="home"
        className="mx-auto grid w-full max-w-6xl gap-10 px-5 pb-16 pt-10 sm:px-8 sm:pb-24 sm:pt-16 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:gap-16"
      >
        <div>
          <p className="mb-5 text-xs font-bold tracking-[0.22em] text-[#537064] sm:text-sm">
            PERSONAL TRAINER, REIMAGINED
          </p>
          <h1 className="max-w-3xl text-4xl font-black leading-[1.12] tracking-[-0.055em] sm:text-6xl lg:text-7xl">
            내 목표에 맞는
            <br />
            <span className="text-[#527c42]">운동의 기준을</span>
            <br />
            세우다.
          </h1>
          <p className="mt-6 max-w-xl text-base leading-8 text-[#59665e] sm:mt-8 sm:text-lg">
            근성장과 체중 감량을 목표로 하는 사람을 위한 AI 퍼스널 트레이너. 더
            분명한 운동 선택과 오래 이어갈 수 있는 코칭을 지향합니다.
          </p>
          <a
            href="#approach"
            className="mt-8 inline-flex min-h-12 items-center gap-3 rounded-full bg-[#183d31] px-6 text-sm font-bold text-white transition hover:bg-[#285c48]"
          >
            이두왕의 코칭 방식 보기 <span aria-hidden="true">↓</span>
          </a>
        </div>

        <div className="relative overflow-hidden rounded-[2rem] bg-[#183d31] p-6 text-white shadow-[0_24px_70px_-36px_rgba(24,61,49,0.65)] sm:p-9">
          <div
            className="absolute -right-16 -top-20 size-56 rounded-full border border-white/10 sm:size-72"
            aria-hidden="true"
          />
          <div
            className="absolute -right-5 -top-9 size-40 rounded-full border border-white/10 sm:size-52"
            aria-hidden="true"
          />
          <div className="relative">
            <p className="text-xs font-bold tracking-[0.2em] text-[#d8f36c]">
              A BETTER WAY TO TRAIN
            </p>
            <h2 className="mt-12 max-w-sm text-3xl font-bold leading-tight tracking-tight sm:mt-16 sm:text-4xl">
              운동은 더 명확하게,
              <br />
              코칭은 더 개인적으로.
            </h2>
            <div className="mt-10 grid grid-cols-2 gap-3 sm:mt-14">
              <div className="rounded-2xl border border-white/15 bg-white/[0.06] p-4 sm:p-5">
                <span className="text-xs font-semibold tracking-wide text-white/55">
                  FOCUS
                </span>
                <p className="mt-2 text-sm font-semibold sm:text-base">
                  근성장 · 체중 감량
                </p>
              </div>
              <div className="rounded-2xl border border-white/15 bg-white/[0.06] p-4 sm:p-5">
                <span className="text-xs font-semibold tracking-wide text-white/55">
                  APPROACH
                </span>
                <p className="mt-2 text-sm font-semibold sm:text-base">
                  규칙 + AI 코칭
                </p>
              </div>
            </div>
            <p className="mt-5 text-xs leading-6 text-white/55">
              개인의 상황을 고려한 피트니스 코칭 에이전트를 만드는
              프로젝트입니다.
            </p>
          </div>
        </div>
      </section>

      <section id="approach" className="bg-white px-5 py-16 sm:px-8 sm:py-24">
        <div className="mx-auto max-w-6xl">
          <div className="max-w-2xl">
            <p className="text-xs font-bold tracking-[0.22em] text-[#537064] sm:text-sm">
              THE COACHING APPROACH
            </p>
            <h2 className="mt-4 text-3xl font-black leading-tight tracking-[-0.04em] sm:text-5xl">
              규칙으로 선택하고,
              <br className="hidden sm:block" />
              AI가 이해를 돕습니다.
            </h2>
            <p className="mt-5 text-base leading-7 text-[#59665e]">
              명시적인 운동 규칙과 생성형 AI의 설명을 구분해, 코칭을 더 쉽게
              이해하고 활용할 수 있도록 설계합니다.
            </p>
          </div>

          <div className="mt-10 grid gap-4 sm:mt-14 md:grid-cols-3">
            {coachingAreas.map((area) => (
              <article
                key={area.number}
                className="rounded-3xl border border-[#e5e8e1] p-6 sm:p-7"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-black text-[#527c42]">
                    {area.number}
                  </span>
                  <span className="text-[10px] font-bold tracking-[0.18em] text-[#849087]">
                    {area.label}
                  </span>
                </div>
                <h3 className="mt-8 text-xl font-bold tracking-tight">
                  {area.title}
                </h3>
                <p className="mt-3 text-sm leading-7 text-[#59665e]">
                  {area.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-7 text-xs text-[#718077] sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <span className="font-bold text-[#344b3f]">이두왕 · Yee Doo-Wang</span>
        <span>Personal Trainer AI Agent</span>
      </footer>
    </main>
  );
}
