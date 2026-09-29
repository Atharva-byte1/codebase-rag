import json
import logging
import urllib.error
import urllib.request

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    pass


class OpenRouterService:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.model = model or settings.llm_model

    def complete(self, prompt: str) -> str:
        if not self.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not configured")

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Codebase RAG",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            logger.error(
                "OpenRouter request failed with HTTP %s: %s",
                exc.code,
                response_body,
            )
            raise OpenRouterError("OpenRouter request failed") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OpenRouterError("OpenRouter request failed") from exc
        return self._parse_response(body)

    @staticmethod
    def _parse_response(body: object) -> str:
        if not isinstance(body, dict):
            raise OpenRouterError("OpenRouter returned an invalid response")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenRouterError("OpenRouter response contained no choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise OpenRouterError("OpenRouter returned an invalid choice")
        message = first_choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OpenRouterError("OpenRouter response contained no answer")
        answer = message["content"].strip()
        if not answer:
            raise OpenRouterError("OpenRouter response contained an empty answer")
        return answer