from openai import APIError, AsyncOpenAI
from pydantic import SecretStr

from yee_doowang_api.application.chat import ChatCompletionError


class OpenRouterChatCompletion:
    def __init__(self, api_key: SecretStr, model: str, base_url: str) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            base_url=base_url,
        )
        self._model = model

    async def complete(self, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
            )
        except APIError as error:
            raise ChatCompletionError("OpenRouter request failed.") from error

        if not response.choices:
            raise ChatCompletionError("OpenRouter returned no completion.")

        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ChatCompletionError("OpenRouter returned an empty completion.")

        return content.strip()

    async def aclose(self) -> None:
        await self._client.close()
