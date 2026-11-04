import json
from pathlib import Path

from yee_doowang_api.application.hypertrophy_prescription import HypertrophyGuidelines


def load_hypertrophy_guidelines(path: Path | None = None) -> HypertrophyGuidelines:
    guidelines_path = path or (
        Path(__file__).resolve().parents[3] / "data" / "hypertrophy-prescription.json"
    )
    return HypertrophyGuidelines.model_validate(
        json.loads(guidelines_path.read_text(encoding="utf-8"))
    )
