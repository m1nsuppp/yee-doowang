from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from yee_doowang_api.application.chat import ChatCompletionError, ChatService

router = APIRouter()


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be blank")
        return prompt


class ChatResponse(BaseModel):
    reply: str


@router.post("/api/chat", response_model=ChatResponse, tags=["chat"])
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    service: ChatService | None = request.app.state.chat_service
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "OpenRouter is not configured. Set OPENROUTER_API_KEY and "
                "OPENROUTER_MODEL in backend/.env."
            ),
        )

    try:
        reply = await service.reply(body.prompt)
    except ChatCompletionError as error:
        raise HTTPException(
            status_code=502,
            detail="The LLM provider request failed.",
        ) from error

    return ChatResponse(reply=reply)
