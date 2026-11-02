# 이두왕(Yee DooWang)

헬스트레이너 AI 에이전트(Personal Trainer AI Agent)의 이름이자, 프로젝트의 이름이다.

운동하는 사람, 근성장/다이어트가 목표인 사용자를 대상으로 피트니스, 운동 루틴, 자세 교정, 근성장/다이어트 코칭을 제공합니다.

## 기술 구성

- `frontend/`: Next.js App Router, React, TypeScript, Tailwind CSS, Biome
- `backend/`: Python 3.12, FastAPI, Pydantic
- `compose.yaml`: 로컬 PostgreSQL 개발용 컨테이너
- LLM (선정): OpenRouter API + Instructor (실제 코칭 요청 경로는 아직 연결하지 않았습니다)
- 규칙 추론: PyreWire (wirelog Datalog 엔진; 프로젝트 규칙은 아직 정의하지 않았습니다)
- Python 의존성·환경: `uv`

서비스는 로컬 개발 단계이며 배포 설정은 포함하지 않습니다. PostgreSQL은 로컬 개발용으로만 준비되어 있고, API 데이터 모델·연결은 아직 추가하지 않았습니다.

## 로컬 실행

필요한 도구: Node.js 20.9 이상, `uv`. Python 3.12는 `uv`가 프로젝트 설정에 맞춰 관리합니다. Docker Compose는 로컬 PostgreSQL을 사용할 때만 필요합니다.

API와 웹 앱을 각각 터미널에서 실행합니다.

선택 사항: 이후 데이터 저장 기능을 개발할 때 사용할 로컬 PostgreSQL입니다. 현재 API는 DB에 연결하지 않습니다.

```bash
docker compose up -d postgres
```

종료할 때는 `docker compose down`을 실행합니다. 데이터 볼륨은 유지됩니다.

```bash
cd backend
uv sync
uv run uvicorn yee_doowang_api.main:app --reload
```

```bash
cd frontend
npm ci
npm run dev
```

정적 검사는 다음 명령으로 실행합니다.

```bash
cd frontend
npm run lint
npm run build
```

```bash
cd backend
uv run ruff check src
```

- 웹 앱: <http://localhost:3000>
- API 상태 확인: <http://localhost:8000/health>
- API 문서: <http://localhost:8000/docs>

OpenRouter 키와 모델 ID는 LLM 기능을 연결할 때 `backend/.env.example`을 `backend/.env`로 복사해 설정합니다. 실제 키는 커밋하지 않습니다.
