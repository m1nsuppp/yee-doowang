# 이두왕(Yee DooWang)

운동 코칭에 필요한 기록·측정·계산을 로컬 SQLite에 저장하는 MCP 서버.

## 구성

- `src/`: Python 3.12, MCP(mcp 2.x), Pydantic, pyrewire, SQLite
- `data/`: 운동 카탈로그, 한국어 라벨·별칭, 근거 자료
- SQLite: `$YEE_DOOWANG_DB` 또는 `$XDG_DATA_HOME/yee-doowang/coach.db` (기본 `~/.local/share/yee-doowang/coach.db`)

## 실행

```sh
uv sync
uv run mcp
```

서버는 stdio로만 동작한다. MCP 클라이언트가 프로세스를 실행하며, 배포하지 않는다.

## MCP 클라이언트 설정

```json
{
  "mcpServers": {
    "yee-doowang": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/yee-doowang", "mcp"]
    }
  }
}
```

## 도구

도구 스키마가 인자와 반환 형식의 기준이다.

- `log_workout`: 운동 기록 저장
- `get_workout_history`: 기간별 기록·진행 신호 조회
- `log_body_metrics`: 신체 측정 기록
- `get_body_metrics`: 최근 측정 요약
- `estimate_1rm`: 1RM 추정
- `calculate_macros`: 단백질·칼로리 범위 계산
- `undo_last_entry`: 최근 또는 지정 기록 삭제
- `get_training_context`: 최근 훈련 맥락 조회
- `export_data`: JSON 또는 Markdown 내보내기

## 저장

- 서버는 기록을 SQLite에 저장하며 외부 네트워크로 전송하지 않는다.
- MCP 클라이언트가 도구 결과를 외부 LLM에 보내는 것은 클라이언트 책임 범위다.
- DB 파일은 저장소에 두지 않는다. `*.db`, `*.db-wal`, `*.db-shm`은 버전 관리에서 제외한다.
- `export_data`는 DB 디렉터리의 `exports/` 아래에만 쓴다.

## 온톨로지

`pyrewire` Datalog 규칙이 운동 ID를 주 표적 근육과 보조 근육으로 연결한다. `log_workout`과 `get_workout_history`의 부위별 직접 세트 집계가 이 관계를 쓴다.

```prolog
direct_muscle(E, M) :- requested_exercise(E), primary_muscle(E, M).
indirect_muscle(E, M) :- requested_exercise(E), secondary_muscle(E, M).
```

## 검증

```sh
uv run test
uv run lint
```

`test`는 계산·SQLite 서비스·pyrewire 근육 매핑을 검증하고, stdio MCP 클라이언트로 전체 도구 흐름을 호출한다.

## 데이터

- `data/exercise-catalog.json`에 분류·샤드 목록·순위 프로필을, `data/exercises/`에 주 표적 근육별 샤드로 운동 1,324개를 둔다.
- 식별자와 표시명을 분리한다. `id`는 불변 키, `labels`는 표시명(`ko`/`en`), `input_aliases`는 표시명 외에 추가로 인정하는 입력·검색 별칭이다. 운동 한국어 표시명은 `exercise-labels.ko.json`, 한국어 입력 별칭은 `exercise-aliases.ko.json`에 둔다.
- 근비대 처방 근거: `data/hypertrophy-prescription.json`.
- 원본: [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset) @ `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`, MIT (고지: `data/EXERCISES-DATA-LICENSE`). 이미지/GIF 미디어는 포함하지 않는다.
- 순위 메타데이터: ExerciseAPI v1.1.0 (CC BY 4.0, 표시: “Exercise data by ExerciseAPI (https://exercise-api.com), licensed under CC BY 4.0.”). 초보 적합성: [Kompf et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC11873903/), doi:10.1177/15598276221115662. 안전 안내: [NHS 허리 통증](https://www.nhs.uk/conditions/back-pain/), [NHS 꼬리뼈 통증](https://www.nhs.uk/conditions/tailbone-coccyx-pain/).
