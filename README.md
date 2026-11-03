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

## 운동 데이터 카탈로그

- `backend/data/exercise-catalog.json`은 공통 분류와 샤드 목록을 담고, `backend/data/exercises/`에는 주 표적 근육별 JSON 파일로 운동 1,324개를 나눠 보관합니다. API 시작 시 로더가 샤드를 합쳐 사용하며 DB에는 저장하지 않습니다.
- 원본: [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset), revision `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`. 운동 데이터는 MIT 라이선스이며 고지문은 `backend/data/EXERCISES-DATA-LICENSE`에 있습니다. 별도 라이선스가 필요한 이미지/GIF 미디어는 포함하지 않습니다.
- 근육 taxonomy는 `abdominals`/`abs`를 `abs`로, `lower abs`를 `lower_abs`로, `obliques`와 `core`를 각각 별도 ID로 보존합니다.
- 현재 채팅은 푸시(가슴·어깨·삼두 주 표적), 복근(복근·하복근 주 표적), 복사근 운동을 추천합니다. 복사근이 보조 근육인 운동도 후보에 포함하며, 그 외 부위는 아직 지원하지 않습니다.
- 원본에는 동작 패턴 관계가 없습니다. 현재 일부 운동에만 한국어 이름이 있으며, 동작 패턴은 이전 카탈로그에서 수동 분류한 17개 운동에만 연결되어 있습니다. 나머지 운동의 동작 패턴은 추정하지 않고, 한국어 이름이 없는 운동은 원문 fallback으로 표시합니다.

운동 추천 채팅은 대화 내역에서 운동 부위와 장비 선택을 해석합니다. 부위가 명확하지 않은 일반 요청에는 지원 부위를 확인합니다. 장비를 모르면 확인하지만, 사용자가 “알아서 골라줘”라고 위임하면 맨몸으로 단정하지 않고 모든 카탈로그 장비를 대상으로 후보를 추립니다. 지원 범위 밖의 요청에는 현재 지원 범위를 안내합니다.

애플리케이션은 장비를 `specified`, `unknown`, `delegate_any`로 구분하고, PyreWire에는 검증된 장비 제한 또는 명시적인 `unrestricted` 조건만 전달합니다. 근육 `name_ko`는 대표 표기이고 `aliases_ko`는 같은 근육 ID를 가리키는 별칭이며, 의도 해석에 사용하고 카드에는 대표 표기만 표시합니다. 화면에는 카탈로그에서 추론한 후보만 표시하며, 번역·설명·세트·횟수·중량 처방을 만들어내지 않습니다.

추천 전 대화에서 사용자가 밝힌 목표와 운동 경력을 확인합니다. 현재 근거가 연결된 목표는 근비대와 근력 진행이며, 그 밖의 목표·상충하는 목표는 확인을 요청합니다. 사용자가 원하면 목표나 경력 분류를 건너뛸 수 있습니다. 성별·나이·운동 기간만으로 능력이나 초보 여부를 추정하지 않습니다.

순위는 `backend/data/exercise-catalog.json`의 출처 연결 프로필만 사용합니다. ExerciseAPI v1.1.0의 CC BY 4.0 메타데이터는 근비대의 `is_gold_standard`, `sfr_class`, 같은 대체 그룹 내 `preferred_rank`와 근력 진행 호환성의 `loadable`·`e1rm_substitution_group`에 사용합니다. 근력 호환성은 외부 중량 진행 기록이 가능하다는 뜻이지, 해당 운동이 모두에게 최선이라는 판정이 아닙니다. ExerciseAPI는 `is_gold_standard`를 연구·기전·훈련 관행을 종합한 편집상 지표로, SFR 등 일부 분류도 큐레이터 평가로 설명하므로 확정적 효과를 보장하지 않습니다. 초보자 표기는 Kompf, Rhodes, Lee의 전문가 합의 연구에서 특정 운동이 초보자에게 적절하다고 판단된 경우에만 연결합니다. 원문 프로필이 없는 운동은 해당 항목에서 미평가된 것이며 부적합하다는 뜻이 아닙니다. 세트·횟수·중량 처방값은 생성하지 않습니다.

출처: [ExerciseAPI 데이터 v1.1.0](https://github.com/aschenoni/exercise-api/tree/main/data), CC BY 4.0 (변환된 메타데이터 사용; 표시 문구: “Exercise data by ExerciseAPI (https://exercise-api.com), licensed under CC BY 4.0.”); [Kompf et al., *Selecting Resistance Training Exercises for Novices: A Delphi Study with Expert Consensus*](https://pmc.ncbi.nlm.nih.gov/articles/PMC11873903/), doi:10.1177/15598276221115662. 연구의 초보 정의는 저항 운동 경험이 없거나 여러 해 운동하지 않은 경우이며, 태그가 있는 운동에만 적용합니다.

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
- 운동 추천 채팅: <http://localhost:3000/>
- API 상태 확인: <http://localhost:8000/health>
- API 문서: <http://localhost:8000/docs>
- Chat API: `POST http://localhost:8000/api/chat`

키와 모델을 설정한 뒤 운동 추천 채팅을 확인합니다.

```bash
curl -sS http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"맨몸 복근 운동을 추천해줘. 목표는 근비대이고 운동을 처음 시작했어요."}]}'
```

요청은 시간순 `messages` 배열이며 각 항목은 `user` 또는 `assistant` 역할과 메시지 내용을 가집니다. 마지막 메시지는 `user`여야 하며 최대 30개 메시지를 받습니다. 응답은 자연어 `reply`와 조건에 맞는 카탈로그 운동 `exercises` 목록입니다. 후보는 출처가 연결된 목표·경력 근거에 따라 순위화됩니다. 목표·경력 확인이나 지원되지 않는 기준 확인 응답은 빈 `exercises`를 반환할 수 있습니다. 운동 카드 데이터에는 주 표적·보조 근육, 장비, 분류된 동작 패턴이 포함됩니다. 설정이 없으면 `503`, 공급자 또는 구조화 응답 처리 실패는 `502`로 반환합니다.
