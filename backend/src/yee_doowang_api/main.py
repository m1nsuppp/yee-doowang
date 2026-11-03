from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from yee_doowang_api.api.chat import router as chat_router
from yee_doowang_api.application.chat import ChatService, CoachModel
from yee_doowang_api.infrastructure.exercise_catalog_file import load_exercise_catalog
from yee_doowang_api.infrastructure.openrouter import OpenRouterCoachModel
from yee_doowang_api.infrastructure.pyrewire_exercise_reasoner import (
    PyreWireExerciseReasoner,
)
from yee_doowang_api.settings import Settings, get_settings


class HealthResponse(BaseModel):
    status: Literal["ok"]


def create_app(
    settings: Settings | None = None,
    coach_model: CoachModel | None = None,
) -> FastAPI:
    config = settings or get_settings()
    managed_coach: OpenRouterCoachModel | None = None
    catalog = load_exercise_catalog()
    reasoner = PyreWireExerciseReasoner(catalog)

    if coach_model is None and config.openrouter_api_key and config.openrouter_model:
        managed_coach = OpenRouterCoachModel(
            api_key=config.openrouter_api_key,
            model=config.openrouter_model,
            base_url=config.openrouter_base_url,
        )
        coach_model = managed_coach

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if managed_coach is not None:
                await managed_coach.aclose()

    app = FastAPI(title=config.app_name, lifespan=lifespan)
    app.state.chat_service = (
        ChatService(coach_model, reasoner, catalog) if coach_model is not None else None
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_origin],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(chat_router)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
