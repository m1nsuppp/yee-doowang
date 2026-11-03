import json
from pathlib import Path

from yee_doowang_api.application.exercise_catalog import ExerciseCatalog


def load_exercise_catalog(path: Path | None = None) -> ExerciseCatalog:
    catalog_path = path or (
        Path(__file__).resolve().parents[3] / "data" / "exercise-catalog.json"
    )
    catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
    shard_names = catalog_data.pop("exercise_shards")
    catalog_data["exercises"] = [
        exercise
        for shard_name in shard_names
        for exercise in json.loads(
            (catalog_path.parent / shard_name).read_text(encoding="utf-8")
        )
    ]
    return ExerciseCatalog.model_validate(catalog_data)
