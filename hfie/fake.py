"""Offline stand-in for OpenRouter, used by --mode dry-run and the tests.
Produces plausible answers (and occasionally broken ones, to exercise the
correction turn). No network access."""
from __future__ import annotations

import random
import time
import threading
from datetime import datetime, timezone

from .openrouter import _result


class FakeClient:
    def __init__(self, seed: int = 0, broken_rate: float = 0.15):
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.broken_rate = broken_rate

    def chat(self, model, messages, **extra):
        with self.lock:
            r = self.rng.random()
            shift = self.rng.gauss(0, 0.4)
        if "tools" in extra:   # shared news search
            body = {"model": model, "choices": [{"message": {"content": "results", "annotations": [
                {"type": "url_citation", "url_citation": {
                    "url": f"https://example.com/story-{i}", "title": f"Example headline {i}",
                    "content": f"Example excerpt for story {i} about {messages[0]['content'][:40]}"}}
                for i in range(1, 9)]}}], "usage": {"prompt_tokens": 300, "completion_tokens": 200, "cost": 0.008}}
            return _result("ok", {"model": model, "messages": messages, **extra}, body, 1, time.monotonic(), "")
        news = "news articles" in messages[-1]["content"] or "news articles" in messages[1]["content"]
        econ = "inflation prices news" in messages[1]["content"] or "economy" in messages[1]["content"][:2000]
        base = 3.0 + shift + (0.3 if news and econ else 0)
        is_correction = len(messages) > 2
        probs = [0, 0, 0, 0, 2, 13, 45, 30, 7, 3]
        if r < self.broken_rate and not is_correction:
            probs = [0, 0, 0, 0, 2, 13, 45, 30, 7, 9]          # sums to 106 -> triggers correction
        lst = "[" + ",".join(f"{p:.2f}%" for p in probs) + "]"
        text = (f"Q1_I: {base + 0.3:.1f}\nQ2_I: {lst}\nQ3_I: {lst}\nQ4_I: {base:.1f} %\nQ5_I: {base - 0.5:.1f} %"
                if not is_correction else f"Q2_I: [0,0,0,0,2,13,45,30,7,3]\nQ3_I: [0,0,0,0,2,13,45,30,7,3]")
        body = {"model": model, "provider": "Fake", "choices": [{"message": {"content": text}}],
                "usage": {"prompt_tokens": 1800, "completion_tokens": 120, "cost": 0.0004}}
        res = _result("ok", {"model": model, "messages": messages}, body, 1, time.monotonic(), "")
        res["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        return res
