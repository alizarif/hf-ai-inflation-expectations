"""Build the exact messages each respondent sees."""
from __future__ import annotations

import re

from .questions import QUESTIONS
from .schedule import Slot

SPACES = re.compile(r"[ \t]+")


def system_message(cfg: dict, persona: str, slot: Slot) -> str:
    text = cfg["system_prompt"].format(
        date=f"{slot.utc:%A, %B} {slot.utc.day}, {slot.utc:%Y}",
        hour=f"{slot.utc:%H}",
        persona=cfg["personas"][persona],
    )
    return SPACES.sub(" ", text).strip()


def user_message(cfg: dict, snapshot: dict) -> str:
    parts = []
    if snapshot.get("text"):
        collected = snapshot["collected_at_utc"].replace("T", " ").replace("+00:00", " UTC")
        parts.append(cfg["news_intro"].format(collected=collected).strip()
                     + "\n\n" + snapshot["text"] + "\n\n---")
    parts.append("Please answer the following five questions in order.")
    for qid, text in QUESTIONS.items():
        parts.append(f"{qid}: {text}")
    parts.append(cfg["answer_instruction"].strip())
    return "\n\n".join(parts)


def build_messages(cfg: dict, persona: str, snapshot: dict, slot: Slot) -> list[dict]:
    return [
        {"role": "system", "content": system_message(cfg, persona, slot)},
        {"role": "user", "content": user_message(cfg, snapshot)},
    ]


def correction_message(problems: dict[str, str]) -> str:
    lines = [f"- {qid}: {why}" for qid, why in problems.items()]
    labels = ", ".join(problems)
    return ("Some of your answers could not be recorded:\n" + "\n".join(lines) +
            f"\n\nPlease answer {labels} again, each on its own line starting with its label, "
            "in exactly the format the question asks for. Probability lists must have ten numbers that total 100.")
