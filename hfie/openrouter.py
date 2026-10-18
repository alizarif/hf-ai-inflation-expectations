"""Minimal OpenRouter chat-completions client with retries and full capture."""
from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_\-]{6,}")


def scrub(text: str) -> str:
    """Remove anything that looks like an OpenRouter key (error messages can echo headers)."""
    return KEY_RE.sub("[REDACTED-KEY]", text) if isinstance(text, str) else text


RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, timeout: int = 180, max_retries: int = 4):
        self.api_key = (api_key or os.environ.get("OPENROUTER_API_KEY", "")).strip()
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        self.timeout, self.max_retries = timeout, max_retries
        self.session = requests.Session()

    def chat(self, model: str, messages: list[dict], **extra: Any) -> dict[str, Any]:
        """One completion. Never raises for API errors: returns a record with status."""
        payload: dict[str, Any] = {"model": model, "messages": messages, "usage": {"include": True}, **extra}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "HF AI Inflation Expectations",
        }
        started = time.monotonic()
        error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.post(URL, headers=headers, json=payload, timeout=self.timeout)
                if r.status_code in RETRYABLE:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                if r.status_code >= 400:   # bad request / auth / unknown model: do not retry
                    return _result("failed", payload, None, attempt, started, f"HTTP {r.status_code}: {r.text[:500]}")
                body = r.json()
                if body.get("error"):
                    raise RuntimeError(f"API error: {str(body['error'])[:300]}")
                if not body.get("choices"):
                    raise RuntimeError("response has no choices")
                return _result("ok", payload, body, attempt, started, "")
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(min(60, 2 ** attempt + random.random() * 2))
        return _result("failed", payload, None, self.max_retries, started, error)


def _result(status: str, payload: dict, body: dict | None, attempt: int, started: float, error: str) -> dict[str, Any]:
    message = (body or {}).get("choices", [{}])[0].get("message", {}) if body else {}
    usage = (body or {}).get("usage") or {}
    return {
        "status": status,
        "error": scrub(error),
        "request": payload,
        "response": body,
        "content": message.get("content") or "",
        "annotations": message.get("annotations") or [],
        "returned_model": (body or {}).get("model", ""),
        "provider": (body or {}).get("provider", ""),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cost_usd": usage.get("cost"),
        "attempts": attempt,
        "latency_s": round(time.monotonic() - started, 2),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
