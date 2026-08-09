"""Thin wrapper over the Groq chat API.

Adds the four things every call site here needs: a tokens-per-minute pacer,
retry/backoff on rate limits, tolerant JSON parsing (models sometimes wrap JSON
in prose or code fences even in JSON mode), and a fallback from the strong model
to a second one.

On the free tier the binding limit is tokens per minute, not requests — 6,000
TPM against 14,400 requests per day. Firing eight workers at that and letting
each one back off for 20 seconds wastes most of the wall clock on retries, so
requests wait for budget here instead of being rejected there. The limit is
learned from the response headers rather than hardcoded, so a paid tier speeds
up on its own.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
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

# Groq charges a fraction of max_tokens against the TPM budget up front, whether
# or not the model generates that much. Measured at roughly 22% on
# llama-3.1-8b-instant; the pacer self-corrects from the response headers, so
# this only has to be close enough for the first few calls.
_OUTPUT_RESERVE_RATIO = 0.25
_CHARS_PER_TOKEN = 4


class _TpmLimiter:
    """Rolling-window pacer for tokens per minute, shared by every worker.

    Deliberately simple: a 60-second deque of (timestamp, tokens). A request
    blocks until its estimate fits under the limit. Estimates are corrected
    against `x-ratelimit-remaining-tokens` after each response, so a bad guess
    costs one slow minute rather than a run of 429s.
    """

    WINDOW = 60.0

    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._limit: int | None = None
        self._spent: deque[tuple[float, int]] = deque()
        # Requests that have been admitted but whose headers have not come back
        # yet. Kept apart from the ledger because observe() overwrites the
        # ledger with the server's count, and that count cannot yet include
        # anything still in flight — folding the two together lets concurrent
        # workers each believe there is budget for them.
        self._inflight = 0

    def _prune(self, now: float) -> None:
        while self._spent and now - self._spent[0][0] > self.WINDOW:
            self._spent.popleft()

    def _used(self, now: float) -> int:
        self._prune(now)
        return sum(tokens for _, tokens in self._spent) + self._inflight

    def acquire(self, estimate: int) -> None:
        """Block until `estimate` tokens fit in the current window."""
        with self._lock:
            while True:
                limit = self._limit
                if limit is None:
                    # Nothing learned yet. One request goes through unpaced so
                    # the headers can teach us the limit; the rest wait for it.
                    if self._inflight == 0:
                        self._inflight += estimate
                        return
                    self._lock.wait(timeout=5.0)
                    continue
                now = time.monotonic()
                used = self._used(now)
                if used + estimate <= limit:
                    self._inflight += estimate
                    return
                if not self._spent and self._inflight == 0:
                    # A single request larger than the whole limit. Let it
                    # through rather than deadlock; the API will judge it.
                    self._inflight += estimate
                    return
                wait = (
                    self.WINDOW - (now - self._spent[0][0]) + 0.05
                    if self._spent
                    else 1.0
                )
                log.debug("TPM pacer: %d/%d used, sleeping %.1fs", used, limit, wait)
                self._lock.wait(timeout=max(0.05, min(wait, 5.0)))

    def release(self, estimate: int) -> None:
        """Drop an in-flight reservation once the request has settled."""
        with self._lock:
            self._inflight = max(0, self._inflight - estimate)
            self._lock.notify_all()

    def observe(self, headers: Any) -> None:
        """Learn the real limit and true usage from a response's headers."""
        if not headers:
            return
        try:
            limit = int(headers.get("x-ratelimit-limit-tokens") or 0)
            remaining = int(headers.get("x-ratelimit-remaining-tokens") or 0)
        except (TypeError, ValueError):
            return
        if limit <= 0:
            return
        with self._lock:
            if self._limit != limit:
                log.info("Groq token limit: %d tokens/minute", limit)
                self._limit = limit
            # Replace the estimate-based ledger with what the server actually
            # counted. One entry timestamped now is close enough — the window is
            # rolling either way, and in-flight requests are tracked separately.
            self._spent.clear()
            self._spent.append((time.monotonic(), max(0, limit - remaining)))
            self._lock.notify_all()


_limiter = _TpmLimiter()


def _estimate_tokens(messages: list[dict[str, str]], max_tokens: int) -> int:
    prompt_chars = sum(len(m.get("content", "")) for m in messages)
    return prompt_chars // _CHARS_PER_TOKEN + int(max_tokens * _OUTPUT_RESERVE_RATIO)


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
    estimate = _estimate_tokens(messages, int(kwargs.get("max_tokens", 1024)))
    _limiter.acquire(estimate)
    try:
        raw = client().chat.completions.with_raw_response.create(
            model=model, messages=messages, **kwargs
        )
    except (RateLimitError, APIStatusError) as exc:
        # A 429 means our ledger was optimistic. Resync from the headers so the
        # retry waits for real budget instead of a fixed backoff.
        _limiter.observe(getattr(getattr(exc, "response", None), "headers", None))
        raise
    else:
        _limiter.observe(raw.headers)
        return raw.parse().choices[0].message.content or ""
    finally:
        _limiter.release(estimate)


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
