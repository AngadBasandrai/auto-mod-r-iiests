"""Thin wrapper over the Groq chat API.

Adds the three things every call site here needs: retry/backoff on rate limits,
tolerant JSON parsing (models sometimes wrap JSON in prose or code fences even in
JSON mode), and a fallback from the strong model to a second one.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Iterable

from groq import Groq
from groq import APIStatusError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config

log = logging.getLogger(__name__)

_client: Groq | None = None
_client_lock = threading.Lock()

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def client() -> Groq:
    global _client
    with _client_lock:
        if _client is None:
            _client = Groq(api_key=config.settings.require_groq())
        return _client


def _model(kind: str) -> str:
    name = config.get(f"models.{kind}")
    if not name:
        raise RuntimeError(f"models.{kind} is not set in config.yaml")
    return name


@retry(
    retry=retry_if_exception_type((RateLimitError, APIStatusError)),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _create(model: str, messages: list[dict[str, str]], **kwargs: Any) -> str:
    response = client().chat.completions.create(
        model=model, messages=messages, **kwargs
    )
    return response.choices[0].message.content or ""


def chat(
    system: str,
    user: str,
    *,
    kind: str = "fast",
    temperature: float = 0.2,
    max_tokens: int = 1024,
    json_mode: bool = False,
    fallback: bool = False,
) -> str:
    """One chat turn. `kind` selects a model from config.yaml models.*."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    models: Iterable[str] = [_model(kind)]
    if fallback:
        alt = config.get("models.strong_fallback")
        if alt:
            models = [*models, alt]

    last_error: Exception | None = None
    for model in models:
        try:
            return _create(model, messages, **kwargs)
        except Exception as exc:  # noqa: BLE001 - we genuinely want to try the next model
            log.warning("Groq call failed on %s: %s", model, exc)
            last_error = exc
    raise RuntimeError(f"All Groq models failed: {last_error}") from last_error


def chat_json(
    system: str,
    user: str,
    *,
    kind: str = "fast",
    temperature: float = 0.0,
    max_tokens: int = 2048,
    default: Any = None,
) -> Any:
    """Chat turn that must return a JSON object. Returns `default` if it doesn't."""
    raw = chat(
        system,
        user,
        kind=kind,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
    )
    parsed = parse_json(raw)
    if parsed is None:
        log.warning("Could not parse JSON from model output: %.200s", raw)
        return default
    return parsed


def parse_json(raw: str) -> Any | None:
    """Best-effort JSON extraction from a model response."""
    if not raw:
        return None
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fenced = _FENCE_RE.search(raw)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Reasoning models sometimes prefix an explanation. Take the outermost
    # brace-balanced span and try that.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None
