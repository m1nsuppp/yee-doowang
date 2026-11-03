from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from yee_doowang_api.application.chat import (
    ChatCompletionError,
    ChatReply,
    ChatService,
    ConversationMessage,
)

router = APIRouter()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ConversationMessage] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def require_user_message_last(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("The last conversation message must be from the user")
        return self


@router.post("/api/chat", response_model=ChatReply, tags=["chat"])
async def chat(body: ChatRequest, request: Request) -> ChatReply:
    service: ChatService | None = request.app.state.chat_service
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "OpenRouter is not configured. Set OPENROUTER_API_KEY and "
                "OPENROUTER_MODEL in the backend environment."
            ),
        )

    try:
        return await service.reply(body.messages)
    except ChatCompletionError as error:
        raise HTTPException(
            status_code=502,
            detail="The LLM provider request failed.",
        ) from error
