from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
MacroGoal = Literal["cut", "maintain", "bulk"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OneRmEstimate(_Model):
    weight_kg: float
    reps: int
    epley_kg: float
    brzycki_kg: float
    lombardi_kg: float
    average_kg: float
    reliable: bool
    note: str


def epley_1rm(weight_kg: float, reps: int) -> float:
    return weight_kg * (1 + reps / 30)


def brzycki_1rm(weight_kg: float, reps: int) -> float:
    return weight_kg * 36 / (37 - reps)


def lombardi_1rm(weight_kg: float, reps: int) -> float:
    return weight_kg * (reps**0.10)


def estimate_1rm(weight_kg: float, reps: int) -> OneRmEstimate:
    if weight_kg <= 0:
        raise ValueError("weight_kg must be positive")
    if not 1 <= reps <= 30:
        raise ValueError("reps must be between 1 and 30")
    epley = epley_1rm(weight_kg, reps)
    brzycki = brzycki_1rm(weight_kg, reps)
    lombardi = lombardi_1rm(weight_kg, reps)
    average = (epley + brzycki + lombardi) / 3
    reliable = reps <= 12
    note = (
        "1–12회 구간의 추정치다. 실제 1RM 측정을 대체하지 않는다."
        if reliable
        else "13회 이상은 추정 신뢰도가 낮다. 1–12회 기록으로 다시 계산하는 편이 좋다."
    )
    return OneRmEstimate(
        weight_kg=weight_kg,
        reps=reps,
        epley_kg=round(epley, 1),
        brzycki_kg=round(brzycki, 1),
        lombardi_kg=round(lombardi, 1),
        average_kg=round(average, 1),
        reliable=reliable,
        note=note,
    )


_ACTIVITY_FACTORS: dict[ActivityLevel, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


class MacroCalculation(_Model):
    body_weight_kg: float
    goal: MacroGoal
    protein_g_min: float
    protein_g_max: float
    calories_kcal_min: float
    calories_kcal_max: float
    bmr_kcal: float | None
    maintenance_kcal_min: float | None
    maintenance_kcal_max: float | None
    formula: str
    assumptions: list[str]
    note: str


def calculate_macros(
    body_weight_kg: float,
    goal: MacroGoal,
    *,
    age: int | None = None,
    sex: Literal["male", "female"] | None = None,
    height_cm: float | None = None,
    activity_level: ActivityLevel | None = None,
) -> MacroCalculation:
    if body_weight_kg <= 0:
        raise ValueError("body_weight_kg must be positive")
    if age is not None and not 14 <= age <= 100:
        raise ValueError("age must be between 14 and 100")
    if height_cm is not None and height_cm <= 0:
        raise ValueError("height_cm must be positive")

    protein_g_min = round(body_weight_kg * 1.6, 1)
    protein_g_max = round(body_weight_kg * 2.2, 1)
    assumptions: list[str] = [
        "단백질은 체중당 1.6–2.2g 범위의 일반 근비대 권고를 사용했다.",
    ]

    if age is not None and sex is not None and height_cm is not None and activity_level is not None:
        sex_offset = 5 if sex == "male" else -161
        bmr = 10 * body_weight_kg + 6.25 * height_cm - 5 * age + sex_offset
        maintenance = bmr * _ACTIVITY_FACTORS[activity_level]
        maintenance_min = maintenance * 0.97
        maintenance_max = maintenance * 1.03
        formula = "Mifflin-St Jeor BMR × 활동계수"
        assumptions.append(
            f"활동계수 {_ACTIVITY_FACTORS[activity_level]}을 적용했다."
        )
    else:
        bmr = None
        maintenance_min = body_weight_kg * 28
        maintenance_max = body_weight_kg * 33
        formula = "체중 기반 유지 칼로리 추정 (28–33 kcal/kg)"
        assumptions.append(
            "나이·성별·키·활동량이 모두 주어지지 않아 Mifflin-St Jeor를 적용하지 않았다."
        )

    if goal == "cut":
        calorie_min = maintenance_min * 0.80
        calorie_max = maintenance_max * 0.90
        assumptions.append("감량은 유지 칼로리의 −10~20% 범위로 계산했다.")
    elif goal == "bulk":
        calorie_min = maintenance_min * 1.05
        calorie_max = maintenance_max * 1.15
        assumptions.append("증량은 유지 칼로리의 +5~15% 범위로 계산했다.")
    else:
        calorie_min = maintenance_min
        calorie_max = maintenance_max
        assumptions.append("유지는 유지 칼로리 범위를 그대로 사용했다.")

    return MacroCalculation(
        body_weight_kg=body_weight_kg,
        goal=goal,
        protein_g_min=protein_g_min,
        protein_g_max=protein_g_max,
        calories_kcal_min=round(calorie_min / 10) * 10,
        calories_kcal_max=round(calorie_max / 10) * 10,
        bmr_kcal=round(bmr, 1) if bmr is not None else None,
        maintenance_kcal_min=round(maintenance_min / 10) * 10,
        maintenance_kcal_max=round(maintenance_max / 10) * 10,
        formula=formula,
        assumptions=assumptions,
        note="추정치이며 의료·영양 진단이 아니다. 개인 건강 상태와 목표는 별도로 확인한다.",
    )
