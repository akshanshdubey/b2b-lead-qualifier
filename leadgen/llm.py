"""Minimal Anthropic Messages API client built on `requests` (no SDK needed).

Handles missing keys, bad keys, rate limits, timeouts and malformed JSON with clear errors.
The API key is only ever placed in the request header; it is never logged or echoed.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import requests

from .config import Settings

log = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    """Generic LLM failure."""


class LLMConfigError(LLMError):
    """API key missing/placeholder."""


class LLMAuthError(LLMError):
    """401/403 - key rejected."""


class LLMRateLimitError(LLMError):
    """429 after all retries."""


class LLMResponseError(LLMError):
    """Reply could not be parsed as the expected JSON."""


class AnthropicClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not settings.has_api_key:
            raise LLMConfigError(
                "No API key configured. Copy .env.example to .env and set ANTHROPIC_API_KEY, "
                "or choose the 'Rules only' extractor.")
        self.settings = settings
        self.session = session or requests.Session()
        self._sleep = sleep

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        payload = {
            "model": self.settings.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.settings.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        last_error = "unknown error"
        for attempt in range(1, self.settings.llm_max_retries + 1):
            try:
                resp = self.session.post(self.settings.api_url, headers=headers, json=payload,
                                         timeout=max(self.settings.request_timeout, 30))
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"network problem ({type(exc).__name__})"
                log.warning("LLM attempt %d failed: %s", attempt, last_error)
                self._backoff(attempt, None)
                continue
            if resp.status_code == 200:
                return self._text_from(resp)
            msg = self._error_message(resp)
            if resp.status_code in (401, 403):
                raise LLMAuthError(f"API key rejected ({resp.status_code}): {msg}")
            if resp.status_code == 404:
                raise LLMError(f"Model not found - check LLM_MODEL in .env ({msg})")
            if resp.status_code == 400:
                raise LLMError(f"Bad request to LLM API: {msg}")
            if resp.status_code in RETRY_STATUS:
                last_error = f"HTTP {resp.status_code}: {msg}"
                log.warning("LLM attempt %d failed: %s", attempt, last_error)
                self._backoff(attempt, resp.headers.get("retry-after"))
                continue
            raise LLMError(f"Unexpected LLM API response {resp.status_code}: {msg}")
        if "429" in last_error:
            raise LLMRateLimitError(f"Rate limited after {self.settings.llm_max_retries} tries.")
        raise LLMError(f"LLM request failed after {self.settings.llm_max_retries} tries: {last_error}")

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict[str, Any]:
        return parse_json_object(self.complete(system, user, max_tokens))

    # ---- helpers ----------------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if attempt >= self.settings.llm_max_retries:
            return
        delay = 2 ** (attempt - 1)
        try:
            if retry_after:
                delay = max(delay, min(float(retry_after), 20.0))
        except ValueError:
            pass
        self._sleep(delay)

    @staticmethod
    def _error_message(resp: requests.Response) -> str:
        try:
            return str(resp.json().get("error", {}).get("message", ""))[:200] or resp.reason or ""
        except ValueError:
            return (resp.text or "")[:120]

    @staticmethod
    def _text_from(resp: requests.Response) -> str:
        try:
            blocks = resp.json()["content"]
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LLMResponseError("LLM API returned an unexpected response shape.") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract the first {...} JSON object from model output (tolerates ``` fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMResponseError("LLM reply did not contain a JSON object.")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"LLM reply was not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise LLMResponseError("LLM JSON was not an object.")
    return data
