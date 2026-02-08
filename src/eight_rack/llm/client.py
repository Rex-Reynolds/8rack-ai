"""LLM API client with structured output via instructor."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TypeVar

import anthropic
import instructor
from pydantic import BaseModel

from .cache import ResponseCache

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Model aliases for convenience
MODELS = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-6",
}


class LLMClient:
    """Anthropic API client with instructor for structured Pydantic output.

    Supports response caching, usage tracking, and model routing.
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache: ResponseCache | None = None,
        default_model: str = "sonnet",
    ):
        self._raw_client = anthropic.Anthropic(api_key=api_key)
        self._client = instructor.from_anthropic(self._raw_client)
        self._cache = cache
        self._default_model = MODELS.get(default_model, default_model)

        # Usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0
        self.cache_hits = 0

    def query(
        self,
        *,
        response_model: type[T],
        system: str = "",
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> T:
        """Send a structured query and get a typed Pydantic response.

        Args:
            response_model: Pydantic model class for the response
            system: System prompt
            messages: Chat messages [{"role": "user", "content": "..."}]
            model: Model name or alias (sonnet/haiku/opus)
            max_tokens: Max response tokens
            temperature: Sampling temperature

        Returns:
            Parsed response as an instance of response_model
        """
        resolved_model = MODELS.get(model, model) if model else self._default_model

        # Check cache
        if self._cache:
            cache_key = self._make_cache_key(
                resolved_model, system, messages, response_model.__name__
            )
            cached = self._cache.get(cache_key)
            if cached:
                self.cache_hits += 1
                logger.debug(f"Cache hit for {response_model.__name__}")
                return response_model.model_validate_json(cached)

        # Make API call
        self.total_calls += 1
        logger.debug(
            f"LLM call #{self.total_calls}: model={resolved_model}, "
            f"response_model={response_model.__name__}"
        )

        response = self._client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            system=system if system else anthropic.NOT_GIVEN,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
        )

        # Track usage (instructor wraps the response, usage may not be directly accessible)
        # We track calls instead for simplicity

        # Cache response
        if self._cache:
            self._cache.put(cache_key, response.model_dump_json())

        return response

    def query_text(
        self,
        *,
        system: str = "",
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Send a plain text query (no structured output).

        Returns the text content of the response.
        """
        resolved_model = MODELS.get(model, model) if model else self._default_model

        self.total_calls += 1
        response = self._raw_client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            system=system if system else anthropic.NOT_GIVEN,
            messages=messages,
            temperature=temperature,
        )

        # Track usage
        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens

        return response.content[0].text

    def _make_cache_key(
        self, model: str, system: str, messages: list[dict], response_model_name: str
    ) -> str:
        """Create a deterministic cache key from the request parameters."""
        payload = json.dumps(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "response_model": response_model_name,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def usage_summary(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "cache_hits": self.cache_hits,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }
