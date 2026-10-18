"""Load the study configuration and fingerprint it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .questions import QUESTIONS

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else ROOT / "config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert cfg["models"] and cfg["trials"] >= 1
    assert "none" in cfg["arms"], "the no-information arm 'none' is required"
    return cfg


def stable_hash(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def design_hash(cfg: dict[str, Any]) -> str:
    """Hash of everything that defines what respondents see (not runtime knobs)."""
    design = {k: v for k, v in cfg.items() if k != "runtime"}
    design["questions"] = QUESTIONS
    return stable_hash(design)[:16]
