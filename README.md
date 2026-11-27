# 이두왕(Yee DooWang)

헬스트레이너 AI 에이전트의 이름이자 프로젝트 이름이다. 피트니스, 운동 루틴, 자세 교정, 근성장·다이어트 코칭을 제공한다.

## 기술 구성

- `frontend/`: Next.js App Router, React, TypeScript, Tailwind CSS, Biome
- `backend/`: Python 3.12, FastAPI, Pydantic, `uv`
- `compose.yaml`: 로컬 PostgreSQL 개발용 컨테이너 (현재 API는 DB에 연결하지 않는다)
- LLM: OpenRouter를 provider 어댑터 경계로 연결하며 모델·API 키는 환경 변수로 설정한다(`backend/.env.example` 참고)
- 규칙 추론: PyreWire (wirelog Datalog 엔진)

배포 설정은 포함하지 않는다.

## 동작 개요

웹 앱은 일반 운동 대화로 시작하고, 루틴을 요청하면 상담으로 전환한다. 상담은 목표·경력·장비·시간·운동 부위·제약 조건을 확인해 루틴 초안을 만든다. 개인 맥락은 브라우저 메모리에만 유지하며 DB나 영구 저장소에 기록하지 않는다. 통증·부상 등 제약이 있으면 확인 전 루틴을 반환하지 않고, 응급 징후에는 진료를 안내한다.

## 운동 데이터

- `backend/data/exercise-catalog.json`에 분류·샤드 목록·순위 프로필을, `backend/data/exercises/`에 주 표적 근육별 샤드로 운동 1,324개를 둔다. 시작 시 로더가 합치며 DB에 저장하지 않는다.
- 근비대 처방 근거: `backend/data/hypertrophy-prescription.json`.
- 원본: [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset) @ `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`, MIT (고지: `backend/data/EXERCISES-DATA-LICENSE`). 이미지/GIF 미디어는 포함하지 않는다.
- 순위 메타데이터: ExerciseAPI v1.1.0 (CC BY 4.0, 표시: “Exercise data by ExerciseAPI (https://exercise-api.com), licensed under CC BY 4.0.”). 초보 적합성: [Kompf et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC11873903/), doi:10.1177/15598276221115662. 안전 안내: [NHS 허리 통증](https://www.nhs.uk/conditions/back-pain/), [NHS 꼬리뼈 통증](https://www.nhs.uk/conditions/tailbone-coccyx-pain/).

## 접속

- 웹 앱: <http://localhost:3000>
- API 상태: <http://localhost:8000/health>
- API 문서: <http://localhost:8000/docs>
