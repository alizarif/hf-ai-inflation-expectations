"""Run one survey wave.

    python -m hfie.run_wave                     # production: current NY slot, skip if already done
    python -m hfie.run_wave --mode test         # real API, 1 trial, writes to data_test/
    python -m hfie.run_wave --mode dry-run      # simulated answers, no network, writes to data_dryrun/
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import news as news_mod
from .config import ROOT, design_hash, load_config
from .parse import density_stats, parse_reply, problems
from .prompts import build_messages, correction_message
from .schedule import current_slot, slot_from_wave_id

MODE_DIRS = {"production": "data", "test": "data_test", "dry-run": "data_dryrun"}


# ---------------------------------------------------------------- one trial
def run_trial(client, cfg, job, snapshot, slot, budget) -> tuple[dict, dict]:
    """Returns (parsed row, raw record)."""
    messages = build_messages(cfg, job["persona"], snapshot, slot)
    calls = []
    if not budget.allow():
        return _row(cfg, job, slot, snapshot, None, [], "skipped_budget"), {**job, "calls": []}
    first = client.chat(job["model"], messages)
    budget.add(first.get("cost_usd"))
    calls.append(first)
    if first["status"] != "ok":
        return _row(cfg, job, slot, snapshot, None, calls, "failed"), {**job, "messages": messages, "calls": calls}

    tol = cfg["density_sum_tolerance"]
    parsed = parse_reply(first["content"], tol)
    for q in parsed:
        parsed[q]["corrected"] = False
    bad = problems(parsed)
    if bad and cfg.get("correction_turn") and budget.allow():
        follow = messages + [{"role": "assistant", "content": first["content"]},
                             {"role": "user", "content": correction_message(bad)}]
        second = client.chat(job["model"], follow)
        budget.add(second.get("cost_usd"))
        calls.append(second)
        if second["status"] == "ok":
            fixed = parse_reply(second["content"], tol)
            for q in bad:
                parsed[q]["first_problem"] = parsed[q]["problem"]
                if fixed[q]["ok"]:
                    parsed[q] = {**fixed[q], "corrected": True, "first_problem": bad[q]}
        messages = follow
    row = _row(cfg, job, slot, snapshot, parsed, calls, None)
    return row, {**job, "messages": messages, "calls": calls, "parsed": parsed}


def _row(cfg, job, slot, snapshot, parsed, calls, forced_status) -> dict:
    row = {
        "wave_id": slot.wave_id, "slot_et": slot.local.isoformat(), "slot_utc": slot.utc.isoformat(),
        "model": job["model"], "persona": job["persona"], "arm": job["arm"], "trial": job["trial"],
        "news_provider": snapshot.get("provider") or "", "news_hash": snapshot["hash"][:16],
        "design_hash": job["design_hash"],
    }
    if parsed:
        n_ok = sum(r["ok"] for r in parsed.values())
        row["status"] = "ok" if n_ok == 5 else "partial"
        row["n_valid"] = n_ok
        row["corrected"] = any(r.get("corrected") for r in parsed.values())
        for q in ("Q1_I", "Q4_I", "Q5_I"):
            row[q.lower()[:2]] = parsed[q]["value"] if parsed[q]["ok"] else None
        for q in ("Q2_I", "Q3_I"):
            key = q.lower()[:2]
            probs = parsed[q]["probs"] if parsed[q]["ok"] else None
            for i in range(10):
                row[f"{key}_p{i}"] = probs[i] if probs else None
            stats = density_stats(probs) if probs else {}
            for s in ("mean", "sd", "p_deflation", "p_above4"):
                row[f"{key}_{s}"] = round(stats[s], 4) if stats else None
        row["problems"] = json.dumps({q: r.get("first_problem") or r["problem"]
                                      for q, r in parsed.items() if r.get("first_problem") or not r["ok"]})
    else:
        row.update(status=forced_status, n_valid=0, corrected=False, problems="")
    last = calls[-1] if calls else {}
    row.update(
        n_calls=len(calls),
        returned_model=last.get("returned_model", ""),
        provider=last.get("provider", ""),
        prompt_tokens=sum(c.get("prompt_tokens") or 0 for c in calls),
        completion_tokens=sum(c.get("completion_tokens") or 0 for c in calls),
        reasoning_tokens=sum(c.get("reasoning_tokens") or 0 for c in calls),
        cost_usd=round(sum(c.get("cost_usd") or 0 for c in calls), 6),
        latency_s=round(sum(c.get("latency_s") or 0 for c in calls), 2),
        error=(last.get("error") or "")[:300],
    )
    return row


COLUMNS = (["wave_id", "slot_et", "slot_utc", "model", "persona", "arm", "trial", "status", "n_valid", "corrected",
            "q1", "q4", "q5"]
           + [f"q2_p{i}" for i in range(10)] + ["q2_mean", "q2_sd", "q2_p_deflation", "q2_p_above4"]
           + [f"q3_p{i}" for i in range(10)] + ["q3_mean", "q3_sd", "q3_p_deflation", "q3_p_above4"]
           + ["problems", "news_provider", "news_hash", "design_hash", "n_calls", "returned_model", "provider",
              "prompt_tokens", "completion_tokens", "reasoning_tokens", "cost_usd", "latency_s", "error"])


class Budget:
    def __init__(self, cap: float):
        self.cap, self.spent, self.lock = cap, 0.0, threading.Lock()

    def add(self, cost):
        with self.lock:
            self.spent += cost or 0.0

    def allow(self) -> bool:
        with self.lock:
            return self.spent < self.cap


# ---------------------------------------------------------------- one wave
def run(mode: str, force: bool = False, wave_id: str | None = None, out: str | None = None,
        models: list[str] | None = None, trials: int | None = None, client=None) -> Path | None:
    cfg = load_config()
    tz, hours = cfg["schedule"]["timezone"], cfg["schedule"]["slot_hours"]
    slot = slot_from_wave_id(wave_id, tz) if wave_id else current_slot(None, tz, hours)
    base = Path(out) if out else ROOT / MODE_DIRS[mode]
    wave_dir = base / "waves" / slot.rel_dir
    if (wave_dir / "responses.csv").exists() and not force:
        print(f"Wave {slot.wave_id} already complete in {wave_dir}; nothing to do.")
        return None
    wave_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        if mode == "dry-run":
            from .fake import FakeClient
            client = FakeClient(seed=hash(slot.wave_id) % 10_000)
        else:
            from .openrouter import OpenRouterClient
            rt = cfg["runtime"]
            client = OpenRouterClient(timeout=rt["request_timeout_s"], max_retries=rt["max_retries"])

    models = models or cfg["models"]
    trials = trials or (1 if mode == "test" else cfg["trials"])
    started = datetime.now(timezone.utc)
    dhash = design_hash(cfg)
    budget = Budget(cfg["runtime"]["max_wave_cost_usd"])

    # 1) shared news, collected once for every model
    today = f"{slot.utc:%A, %B} {slot.utc.day}, {slot.utc:%Y}"
    snapshots, search_calls = news_mod.collect(cfg, client, today)
    for c in search_calls:
        budget.add(c.get("cost_usd"))
    arms = [a for a, s in snapshots.items() if a == "none" or s["text"]]
    dropped = sorted(set(snapshots) - set(arms))

    # 2) every respondent conversation, in shuffled order
    jobs = [{"model": m, "persona": p, "arm": a, "trial": t, "design_hash": dhash}
            for m in models for p in cfg["personas"] for a in arms for t in range(1, trials + 1)]
    random.Random(slot.wave_id).shuffle(jobs)
    rows, raws = [], []
    with ThreadPoolExecutor(max_workers=cfg["runtime"]["max_workers"]) as pool:
        futures = {pool.submit(run_trial, client, cfg, j, snapshots[j["arm"]], slot, budget): j for j in jobs}
        for n, fut in enumerate(as_completed(futures), 1):
            job = futures[fut]
            try:
                row, raw = fut.result()
            except Exception as exc:   # programming errors: record, keep going
                row = _row(cfg, job, slot, snapshots[job["arm"]], None, [], "failed")
                row["error"] = f"runner error: {exc}"[:300]
                raw = {**job, "calls": [], "runner_error": str(exc)}
            rows.append(row)
            raws.append({"kind": "trial", **raw})
            if n % 25 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)} done, spent ${budget.spent:.3f}", flush=True)

    # 3) save: news, raw transcripts, parsed rows, manifest
    rows.sort(key=lambda r: (r["model"], r["persona"], r["arm"], r["trial"]))
    with (wave_dir / "news.json").open("w", encoding="utf-8") as fh:
        json.dump(snapshots, fh, ensure_ascii=False, indent=1)
    with gzip.open(wave_dir / "raw.jsonl.gz", "wt", encoding="utf-8") as fh:
        for rec in search_calls + raws:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    with (wave_dir / "responses.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    status_counts = {}
    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    manifest = {
        "wave_id": slot.wave_id, "mode": mode, "slot_et": slot.local.isoformat(), "slot_utc": slot.utc.isoformat(),
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lateness_minutes": round((started - slot.utc).total_seconds() / 60, 1),
        "design_hash": dhash, "design_version": cfg["design_version"],
        "models": models, "personas": list(cfg["personas"]), "arms_run": arms, "arms_dropped": dropped,
        "trials": trials, "n_trials": len(rows), "status_counts": status_counts,
        "n_corrected": sum(bool(r["corrected"]) for r in rows),
        "news": {a: {"provider": s.get("provider"), "n_items": s.get("n_items", 0), "hash": s["hash"][:16],
                     "notes": s.get("notes", [])} for a, s in snapshots.items()},
        "cost_usd": round(budget.spent, 4), "budget_cap_usd": budget.cap,
        "github_run": os.environ.get("GITHUB_RUN_ID", ""),
    }
    (wave_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    _summary(manifest, rows)
    return wave_dir


def _summary(manifest: dict, rows: list[dict]) -> None:
    lines = [f"### Wave {manifest['wave_id']} ({manifest['mode']})",
             f"- trials: {manifest['n_trials']}  status: {manifest['status_counts']}  corrected: {manifest['n_corrected']}",
             f"- cost: ${manifest['cost_usd']}  late by {manifest['lateness_minutes']} min",
             f"- news: " + ", ".join(f"{a}={v['provider']}:{v['n_items']}" for a, v in manifest["news"].items()),
             "", "| model | ok | partial | failed | mean q4 |", "|---|---|---|---|---|"]
    by_model: dict[str, list[dict]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r)
    for m, rs in sorted(by_model.items()):
        q4 = [r["q4"] for r in rs if r.get("q4") is not None]
        cnt = lambda s: sum(r["status"] == s for r in rs)
        lines.append(f"| {m} | {cnt('ok')} | {cnt('partial')} | {cnt('failed')} | "
                     f"{(sum(q4) / len(q4)) if q4 else float('nan'):.2f} |")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(MODE_DIRS), default="production")
    ap.add_argument("--force", action="store_true", help="rerun even if this slot is complete")
    ap.add_argument("--wave-id", help="run a specific slot, e.g. 2026-10-18T04ET")
    ap.add_argument("--out", help="output data directory")
    ap.add_argument("--models", nargs="+")
    ap.add_argument("--trials", type=int)
    a = ap.parse_args(argv)
    t0 = time.time()
    path = run(a.mode, a.force, a.wave_id, a.out, a.models, a.trials)
    print(f"Done in {time.time() - t0:.0f}s -> {path}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"ran={'true' if path else 'false'}\nwave_id={path.name if path else ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
