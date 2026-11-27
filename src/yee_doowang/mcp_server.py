from datetime import date, datetime
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from yee_doowang import calculations
from yee_doowang.calculations import (
    ActivityLevel,
    MacroCalculation,
    MacroGoal,
    OneRmEstimate,
)
from yee_doowang.catalog import Catalog, Locale
from yee_doowang.ontology import ExerciseOntology
from yee_doowang.storage import WorkoutStore
from yee_doowang.workouts import (
    BodyMetricInput,
    BodyMetricLogResult,
    BodyMetricsSummary,
    DeletedEntry,
    ExerciseInput,
    ExportResult,
    GroupBy,
    LogWorkoutRequest,
    TrainingContext,
    WorkoutHistory,
    WorkoutHistoryRequest,
    WorkoutLogResult,
    WorkoutService,
)

_catalog = Catalog.load()
_service = WorkoutService(
    WorkoutStore(),
    _catalog,
    ExerciseOntology(_catalog),
)

mcp = MCPServer(
    name="yee-doowang",
    version="0.2.0",
    instructions="운동 기록·신체 측정·계산을 처리하는 로컬 MCP 서버다.",
)


@mcp.tool()
def log_workout(
    exercises: list[ExerciseInput],
    performed_at: datetime | None = None,
    notes: str | None = None,
    client_request_id: str | None = None,
    weight_unit: Literal["kg", "lb"] = "kg",
    locale: Locale = "ko",
) -> WorkoutLogResult:
    """수행한 운동을 로컬 SQLite에 기록한다.

    운동 name은 카탈로그 표시명·한국어 별칭(예: 스쿼트) 또는 exercise_id로
    해석한다. 세트는 개별 항목으로 보내거나 sets 수로 축약한다. lb는 kg로
    변환해 저장한다. client_request_id가 이미 저장돼 있으면 중복 기록하지 않고
    같은 client_request_id의 운동 세션을 반환한다.
    """
    return _service.log_workout(
        LogWorkoutRequest(
            performed_at=performed_at,
            exercises=exercises,
            notes=notes,
            client_request_id=client_request_id,
            weight_unit=weight_unit,
        ),
        locale=locale,
    )


@mcp.tool()
def get_workout_history(
    exercise: str | None = None,
    exercise_id: Annotated[str | None, Field(pattern=r"^[0-9]{4}$")] = None,
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: GroupBy = "session",
    include_sets: bool = False,
    locale: Locale = "ko",
) -> WorkoutHistory:
    """최근 운동 기록과 진행 신호를 조회한다.

    기간을 생략하면 최근 28일이다. group_by는 session, exercise, week, muscle
    중 하나다. signals는 운동 세션별 최고 e1RM의 첫·끝 변화를 2% 기준으로
    up/flat/down/insufficient_data로 표시한다. 부위별 직접 세트는 주 표적
    근육 기준이다. 이 도구는 판단 근거만 반환하고 증량을 지시하지 않는다.
    """
    return _service.workout_history(
        WorkoutHistoryRequest(
            exercise=exercise,
            exercise_id=exercise_id,
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
            include_sets=include_sets,
        ),
        locale=locale,
    )


@mcp.tool()
def log_body_metrics(
    measured_at: datetime | None = None,
    body_weight_kg: Annotated[float | None, Field(gt=0)] = None,
    body_fat_percent: Annotated[float | None, Field(ge=0, le=70)] = None,
    sleep_hours: Annotated[float | None, Field(ge=0, le=24)] = None,
    fatigue: Annotated[int | None, Field(ge=1, le=5)] = None,
    notes: str | None = None,
) -> BodyMetricLogResult:
    """체중·체지방률·수면 시간·피로도를 기록한다.

    최소 한 항목이 필요하다. 직전 측정값과 체중 변화도 함께 반환한다.
    """
    return _service.log_body_metrics(
        BodyMetricInput(
            measured_at=measured_at,
            body_weight_kg=body_weight_kg,
            body_fat_percent=body_fat_percent,
            sleep_hours=sleep_hours,
            fatigue=fatigue,
            notes=notes,
        )
    )


@mcp.tool()
def get_body_metrics(
    days: Annotated[int, Field(ge=1, le=365)] = 28,
) -> BodyMetricsSummary:
    """최근 N일 신체 측정 기록과 평균·변화를 조회한다."""
    return _service.body_metrics(days=days)


@mcp.tool()
def estimate_1rm(
    weight_kg: Annotated[float, Field(gt=0)],
    reps: Annotated[int, Field(ge=1, le=30)],
) -> OneRmEstimate:
    """Epley·Brzycki·Lombardi 공식으로 1RM을 추정한다.

    세 공식의 값과 평균을 반환한다. 13회 이상은 신뢰도 경고를 포함한다.
    """
    return calculations.estimate_1rm(weight_kg=weight_kg, reps=reps)


@mcp.tool()
def calculate_macros(
    body_weight_kg: Annotated[float, Field(gt=0)],
    goal: MacroGoal,
    age: Annotated[int | None, Field(ge=14, le=100)] = None,
    sex: Literal["male", "female"] | None = None,
    height_cm: Annotated[float | None, Field(gt=0)] = None,
    activity_level: ActivityLevel | None = None,
) -> MacroCalculation:
    """체중 기반 단백질·칼로리 범위를 계산한다.

    나이·성별·키·활동량이 모두 있으면 Mifflin-St Jeor BMR과 활동계수를 쓰고,
    없으면 체중 기반 유지 칼로리 범위를 쓴다. 공식과 가정을 함께 반환한다.
    """
    return calculations.calculate_macros(
        body_weight_kg=body_weight_kg,
        goal=goal,
        age=age,
        sex=sex,
        height_cm=height_cm,
        activity_level=activity_level,
    )


@mcp.tool()
def undo_last_entry(
    kind: Literal["workout", "body_metrics"],
    entry_id: int | None = None,
) -> DeletedEntry:
    """최근 또는 지정한 운동·신체 측정 기록을 삭제한다."""
    return _service.undo_last_entry(kind=kind, entry_id=entry_id)


@mcp.tool()
def get_training_context(
    days: Annotated[int, Field(ge=1, le=365)] = 28,
    locale: Locale = "ko",
) -> TrainingContext:
    """최근 훈련 맥락을 한 번에 조회한다.

    최근 운동 세션 5개, 신체 측정 요약, 종목별 e1RM 진행 신호, 부위별 주간 직접
    세트, 전체 기간 개인 최고 기록을 포함한다.
    """
    return _service.training_context(days=days, locale=locale)


@mcp.tool()
def export_data(
    format: Literal["json", "markdown"] = "json",
) -> ExportResult:
    """모든 로컬 기록을 JSON 또는 Markdown으로 내보낸다.

    파일은 SQLite DB와 같은 디렉터리의 exports/ 아래에만 저장한다.
    """
    return _service.export_data(format=format)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
