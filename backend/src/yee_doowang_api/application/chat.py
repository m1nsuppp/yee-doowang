from typing import Protocol


class ChatCompletionError(Exception):
    """A safe, provider-independent chat completion failure."""


class ChatCompletion(Protocol):
    async def complete(self, prompt: str) -> str: ...


class ChatService:
    def __init__(self, completion: ChatCompletion) -> None:
        self._completion = completion

    async def reply(self, prompt: str) -> str:
        return await self._completion.complete(prompt)
