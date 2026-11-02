from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from yee_doowang_api.api.chat import router as chat_router
from yee_doowang_api.application.chat import ChatCompletion, ChatService
from yee_doowang_api.infrastructure.openrouter import OpenRouterChatCompletion
from yee_doowang_api.settings import Settings, get_settings


class HealthResponse(BaseModel):
    status: Literal["ok"]


def create_app(
    settings: Settings | None = None,
    completion: ChatCompletion | None = None,
) -> FastAPI:
    config = settings or get_settings()
    managed_completion: OpenRouterChatCompletion | None = None

    if completion is None and config.openrouter_api_key and config.openrouter_model:
        managed_completion = OpenRouterChatCompletion(
            api_key=config.openrouter_api_key,
            model=config.openrouter_model,
            base_url=config.openrouter_base_url,
        )
        completion = managed_completion

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if managed_completion is not None:
                await managed_completion.aclose()

    app = FastAPI(title=config.app_name, lifespan=lifespan)
    app.state.chat_service = ChatService(completion) if completion is not None else None
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
