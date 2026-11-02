# 이두왕(Yee DooWang)

헬스트레이너 AI 에이전트(Personal Trainer AI Agent)의 이름이자, 프로젝트의 이름이다.

운동하는 사람, 근성장/다이어트가 목표인 사용자를 대상으로 피트니스, 운동 루틴, 자세 교정, 근성장/다이어트 코칭을 제공합니다.

## 기술 구성

- `frontend/`: Next.js App Router, React, TypeScript, Tailwind CSS, Biome
- `backend/`: Python 3.12, FastAPI, Pydantic
- `compose.yaml`: 로컬 PostgreSQL 개발용 컨테이너
- LLM: OpenRouter를 FastAPI 외부 provider 어댑터 경계로 연결합니다. 모델과 API 키는 `backend/.env`에서 설정합니다.
- 규칙 추론: PyreWire (wirelog Datalog 엔진; 프로젝트 규칙은 아직 정의하지 않았습니다)
- Python 의존성·환경: `uv`

서비스는 로컬 개발 단계이며 배포 설정은 포함하지 않습니다. API는 PostgreSQL에 연결하지 않으며, LLM 요청은 설정된 OpenRouter 모델로 전달합니다.

## 로컬 실행

필요한 도구: Node.js 20.9 이상, `uv`. Python 3.12는 `uv`가 프로젝트 설정에 맞춰 관리합니다. Docker Compose는 로컬 PostgreSQL을 사용할 때만 필요합니다.

OpenRouter를 사용하려면 `backend/.env.example`을 `backend/.env`로 복사하고 `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`을 설정합니다. 실제 키는 커밋하지 않습니다. OMP 세션은 프로젝트 확장 `.omp/extensions/guard-env-files.ts`로 `.env*` 파일을 직접 읽거나 수정하는 도구 호출을 차단합니다 (`*.example` 제외). OMP 확장은 샌드박스가 아니므로 임의 코드 실행까지 막는 운영체제 수준의 보안 경계는 아닙니다.

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
uv run ruff check src tests
uv run python -m unittest discover -s tests
```

- 웹 앱: <http://localhost:3000>
- API 상태 확인: <http://localhost:8000/health>
- API 문서: <http://localhost:8000/docs>
- Chat API: `POST http://localhost:8000/api/chat`

키와 모델을 설정한 뒤 실제 응답을 확인합니다.

```bash
curl -sS http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"운동 전 준비운동을 짧게 추천해줘."}'
```

요청 본문은 `{"prompt":"..."}`, 성공 응답은 `{"reply":"..."}`입니다. 설정이 없으면 `503`, 공급자 요청 실패는 `502`로 반환합니다.
