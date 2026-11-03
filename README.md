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

## PushDay 운동 데이터

- `backend/data/pushday-exercises.json`에 PushDay용 운동 17개를 로컬 파일로 큐레이션했습니다. 채팅 요청에서 PyreWire 규칙 추론에 사용하며, DB에는 저장하지 않습니다.
- 원본: [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset), revision `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`. 원본 운동 데이터는 MIT 라이선스이며, 고지문은 `backend/data/EXERCISES-DATA-LICENSE`에 보관합니다. 이미지/GIF는 가져오지 않았습니다.
- 관계 모델: 운동은 주 표적 근육·보조 근육, 장비, 동작 패턴을 ID로 참조하고, 운동일은 집중 근육을 참조합니다. PushDay 후보는 주 표적 근육이 가슴·삼각근·삼두근 중 하나인 운동입니다. 보조 근육은 문맥 정보이며 PushDay 포함 여부를 단독으로 결정하지 않습니다.
- 원본에는 동작 패턴 관계가 없어 `horizontal_press`, `vertical_press`, `shoulder_abduction`, `elbow_extension`은 로컬에서 직접 분류했습니다. 따라서 이 파일은 원본을 그대로 옮긴 데이터가 아니라 추적 가능한 큐레이션입니다.

PushDay 채팅은 대화 내역에서 운동 의도와 장비 선택을 해석합니다. 장비를 모르면 확인하지만, 사용자가 “알아서 골라줘”라고 위임하면 맨몸으로 단정하지 않고 모든 카탈로그 장비를 대상으로 후보를 추립니다. 지원 범위 밖의 요청에는 현재 지원 범위를 안내합니다.

애플리케이션은 장비를 `specified`, `unknown`, `delegate_any`로 구분하고, PyreWire에는 검증된 장비 제한 또는 명시적인 `unrestricted` 조건만 전달합니다. 고정 규칙은 운동일 집중 근육·주 표적 근육과 장비 조건을 조합합니다. LLM은 추론된 후보를 설명하고, 화면은 카탈로그 정보를 카드로 표시합니다. 현재 데이터에는 난이도나 세트·횟수·중량 처방이 없으므로 초보자 적합성을 단정하거나 처방을 생성하지 않습니다.

## 로컬 실행

필요한 도구: Node.js 20.9 이상, `uv`. Python 3.12는 `uv`가 프로젝트 설정에 맞춰 관리합니다. Docker Compose는 로컬 PostgreSQL을 사용할 때만 필요합니다.

OpenRouter를 사용하려면 `backend/.env.example`을 `backend/.env`로 복사하고 `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`을 설정합니다. 실제 키는 커밋하지 않습니다. OMP 확장은 시작 시 로드되므로 `.omp/extensions/guard-env-files.ts`를 적용하려면 새 OMP 세션을 시작해야 합니다. 이 확장은 `.env*` 직접 경로를 읽거나 수정하는 도구 호출을 차단합니다 (`*.example` 제외). OMP 확장은 샌드박스가 아니므로 임의 코드 실행까지 막는 운영체제 수준의 보안 경계는 아닙니다.

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

웹 앱은 `NEXT_PUBLIC_API_BASE_URL`로 API를 호출하며 기본값은 `http://localhost:8000`입니다. 다른 출처를 사용할 때는 backend의 `FRONTEND_ORIGIN`도 웹 앱 출처와 일치시킵니다.

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
- PushDay 채팅: <http://localhost:3000/chat>
- API 상태 확인: <http://localhost:8000/health>
- API 문서: <http://localhost:8000/docs>
- Chat API: `POST http://localhost:8000/api/chat`

키와 모델을 설정한 뒤 PushDay 채팅을 확인합니다.

```bash
curl -sS http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"맨몸으로 PushDay 운동을 추천해줘."}]}'
```

요청은 시간순 `messages` 배열이며 각 항목은 `user` 또는 `assistant` 역할과 메시지 내용을 가집니다. 마지막 메시지는 `user`여야 하며 최대 30개 메시지를 받습니다. 응답은 자연어 `reply`와 PyreWire가 추론한 카탈로그 운동 `exercises` 목록입니다. 조건 확인·지원 범위 안내 응답은 빈 `exercises`를 반환할 수 있습니다. 설정이 없으면 `503`, 공급자 또는 구조화 응답 처리 실패는 `502`로 반환합니다.
