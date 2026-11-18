"""Lazy, explicit-opt-in provider boundary. No requests or clients on application startup."""

import os
import sys
from contextlib import suppress
from functools import cached_property
from typing import Protocol

from langchain_core.exceptions import OutputParserException
from langsmith import tracing_context
from pydantic import BaseModel, ValidationError

from app.modules.ai.errors import AIQuotaExceeded, AIUnavailable, InvalidAIOutput


class AIProvider(Protocol):
    def structured(self, prompt, payload: str, schema: type[BaseModel]) -> BaseModel: ...
    def embed(self, content: str) -> list[float]: ...


class GeminiProvider:
    def __init__(self, settings):
        self.settings = settings

    def check_allowed(self):
        if (
            self.settings.app_env == "test"
            or "pytest" in sys.modules
            or os.getenv("PYTEST_CURRENT_TEST")
        ):
            raise AIUnavailable("Real Gemini requests are prohibited in automated tests.")
        if not self.settings.ai_enabled:
            raise AIUnavailable("AI is disabled. Manual workflows remain available.")
        if not self.settings.ai_live_requests_enabled:
            raise AIUnavailable(
                "Live AI requests require explicit operator approval and enablement."
            )
        if not self.settings.gemini_api_key or not self.settings.gemini_api_key.get_secret_value():
            raise AIUnavailable("AI provider is not configured.")

    @cached_property
    def client(self):
        self.check_allowed()
        from google import genai
        from google.genai.types import HttpOptions, HttpRetryOptions

        return genai.Client(
            api_key=self.settings.gemini_api_key.get_secret_value(),
            vertexai=False,
            http_options=HttpOptions(
                timeout=self.settings.ai_request_timeout_seconds * 1000,
                retry_options=HttpRetryOptions(attempts=1),
            ),
        )

    @cached_property
    def chat(self):
        self.check_allowed()
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=self.settings.gemini_chat_model,
            google_api_key=self.settings.gemini_api_key,
            vertexai=False,
            temperature=0,
            timeout=self.settings.ai_request_timeout_seconds,
            max_retries=0,
            max_output_tokens=self.settings.ai_max_output_tokens,
            verbose=False,
            include_thoughts=False,
        )

    def close(self):
        # Close only clients already initialized. Shutdown must never initialize a client.
        with suppress(Exception):
            if "client" in self.__dict__:
                self.__dict__["client"].close()
        with suppress(Exception):
            if "chat" in self.__dict__:
                self.__dict__["chat"].client.close()

    def structured(self, prompt, payload: str, schema: type[BaseModel]) -> BaseModel:
        self.check_allowed()
        # Only malformed structured responses can be retried, and only when configured.
        # Transport/429 errors do not automatically retry or multiply SDK retries.
        for attempt in range(self.settings.ai_max_retries + 1):
            try:
                with tracing_context(enabled=False):
                    chain = prompt | self.chat.with_structured_output(schema, method="json_schema")
                    result = chain.invoke({"payload": payload}, config={"callbacks": []})
                return schema.model_validate(result)
            except (ValidationError, OutputParserException):
                if attempt == self.settings.ai_max_retries:
                    raise InvalidAIOutput() from None
            except Exception as exc:
                raise_provider_failure(exc)
        raise InvalidAIOutput()

    def embed(self, content: str) -> list[float]:
        self.check_allowed()
        from google.genai.types import EmbedContentConfig, HttpOptions, HttpRetryOptions

        try:
            result = self.client.models.embed_content(
                model=self.settings.gemini_embedding_model,
                contents=content,
                config=EmbedContentConfig(
                    task_type="SEMANTIC_SIMILARITY",
                    output_dimensionality=self.settings.ai_embedding_dimensions,
                    http_options=HttpOptions(
                        timeout=self.settings.ai_request_timeout_seconds * 1000,
                        retry_options=HttpRetryOptions(attempts=1),
                    ),
                ),
            )
            if not result.embeddings or len(result.embeddings) != 1:
                raise InvalidAIOutput()
            return list(result.embeddings[0].values or [])
        except InvalidAIOutput:
            raise
        except Exception as exc:
            raise_provider_failure(exc)


def raise_provider_failure(exc: Exception):
    # Inspect typed status codes only. Never stringify/log the exception or request.
    if getattr(exc, "code", None) == 429 or getattr(exc, "status_code", None) == 429:
        raise AIQuotaExceeded() from None
    import httpx

    if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or getattr(exc, "code", None) in (
        408,
        504,
    ):
        from fastapi import HTTPException

        raise HTTPException(
            504, "AI provider timed out. Manual workflows remain available."
        ) from None
    raise AIUnavailable() from None
