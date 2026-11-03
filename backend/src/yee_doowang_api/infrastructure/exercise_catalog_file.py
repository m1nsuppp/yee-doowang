from pathlib import Path

from yee_doowang_api.application.exercise_catalog import ExerciseCatalog


def load_exercise_catalog(path: Path | None = None) -> ExerciseCatalog:
    catalog_path = path or (
        Path(__file__).resolve().parents[3] / "data" / "pushday-exercises.json"
    )
    return ExerciseCatalog.model_validate_json(catalog_path.read_text(encoding="utf-8"))
