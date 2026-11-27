# 이두왕(Yee DooWang)

이 프로젝트의 이름이자 헬스트레이너 AI 에이전트의 이름이다. 피트니스, 운동 루틴, 근성장, 다이어트 코칭을 제공한다.

## 운동 데이터

- `backend/data/exercise-catalog.json`에 분류·샤드 목록·순위 프로필을, `backend/data/exercises/`에 주 표적 근육별 샤드로 운동 1,324개를 둔다. 시작 시 로더가 합치며 DB에 저장하지 않는다.
- 근비대 처방 근거: `backend/data/hypertrophy-prescription.json`.
- 원본: [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset) @ `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`, MIT (고지: `backend/data/EXERCISES-DATA-LICENSE`). 이미지/GIF 미디어는 포함하지 않는다.
- 순위 메타데이터: ExerciseAPI v1.1.0 (CC BY 4.0, 표시: “Exercise data by ExerciseAPI (https://exercise-api.com), licensed under CC BY 4.0.”). 초보 적합성: [Kompf et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC11873903/), doi:10.1177/15598276221115662. 안전 안내: [NHS 허리 통증](https://www.nhs.uk/conditions/back-pain/), [NHS 꼬리뼈 통증](https://www.nhs.uk/conditions/tailbone-coccyx-pain/).

## 접속

- 웹 앱: <http://localhost:3000>
- API 상태: <http://localhost:8000/health>
- API 문서: <http://localhost:8000/docs>
