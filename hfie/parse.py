"""Parse and validate free-text answers. Never repairs an answer: it either
reads it unambiguously or marks it invalid with a reason."""
from __future__ import annotations

import math
import re

from .questions import BIN_MIDPOINTS, DENSITY_QUESTIONS, POINT_QUESTIONS, QUESTIONS

LABEL = re.compile(r"(?<![A-Za-z0-9])[*_#\s]*(Q[1-5])(?:_I)?[*_\s]*[:：][*_]*", re.IGNORECASE)
NUM = re.compile(r"(?<![\d.])([-−]?\d+(?:\.\d+)?)\s*(%|percent)?", re.IGNORECASE)
RANGE = re.compile(r"\d\s*(?:–|—|-|to)\s*\d")
BRACKET = re.compile(r"\[([^\[\]]*)\]")


def split_answers(text: str) -> dict[str, str]:
    """{'Q1_I': '<raw answer segment>', ...} using the first occurrence of each label."""
    matches = list(LABEL.finditer(text or ""))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        qid = m.group(1).upper() + "_I"
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if qid in QUESTIONS and qid not in out:
            out[qid] = text[m.end():end].strip()
    return out


def _numbers(segment: str) -> list[tuple[float, bool]]:
    return [(float(m.group(1).replace("−", "-")), bool(m.group(2))) for m in NUM.finditer(segment)]


def parse_point(segment: str) -> tuple[float | None, str]:
    if not segment:
        return None, "no answer found"
    if RANGE.search(segment.replace("12 months", "").replace("48 months", "").replace("60 months", "")):
        return None, "gave a range instead of one number"
    nums = _numbers(segment)
    pct = [v for v, has_pct in nums if has_pct]
    if len(pct) == 1:
        value = pct[0]
    elif len(nums) == 1:
        value = nums[0][0]
    else:
        return None, f"expected one number, found {len(nums)}"
    if not math.isfinite(value) or abs(value) > 100:
        return None, f"{value} is outside -100..100"
    return value, ""


def parse_density(segment: str, tol: float) -> tuple[list[float] | None, str]:
    if not segment:
        return None, "no answer found"
    candidates = []
    br = BRACKET.search(segment)
    if br:
        candidates.append([v for v, _ in _numbers(br.group(1))])
    nums = _numbers(segment)
    candidates += [[v for v, p in nums if p], [v for v, _ in nums]]
    probs = next((c for c in candidates if len(c) == 10), None)
    if probs is None:
        return None, f"expected 10 probabilities, found {len(candidates[0]) if candidates else 0}"
    if any(p < 0 or p > 100 for p in probs):
        return None, "each probability must be between 0 and 100"
    total = sum(probs)
    if abs(total - 100) > tol:
        return None, f"the ten probabilities sum to {total:.2f}%, not 100%"
    return probs, ""


def density_stats(probs: list[float]) -> dict[str, float]:
    total = sum(probs)
    w = [p / total for p in probs]
    mean = sum(wi * m for wi, m in zip(w, BIN_MIDPOINTS))
    sd = math.sqrt(sum(wi * (m - mean) ** 2 for wi, m in zip(w, BIN_MIDPOINTS)))
    return {"mean": mean, "sd": sd, "p_deflation": sum(probs[:5]), "p_above4": sum(probs[7:])}


def parse_reply(text: str, tol: float = 0.1) -> dict[str, dict]:
    """Parse every question that appears in `text`."""
    segments = split_answers(text)
    result: dict[str, dict] = {}
    for qid in QUESTIONS:
        seg = segments.get(qid, "")
        if qid in POINT_QUESTIONS:
            value, problem = parse_point(seg)
            result[qid] = {"raw": seg, "value": value, "ok": value is not None, "problem": problem}
        else:
            probs, problem = parse_density(seg, tol)
            result[qid] = {"raw": seg, "probs": probs, "ok": probs is not None, "problem": problem}
    return result


def problems(parsed: dict[str, dict]) -> dict[str, str]:
    return {q: r["problem"] for q, r in parsed.items() if not r["ok"]}


__all__ = ["split_answers", "parse_point", "parse_density", "density_stats", "parse_reply",
           "problems", "DENSITY_QUESTIONS", "POINT_QUESTIONS"]
