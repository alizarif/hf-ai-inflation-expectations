"""Build the public website: copy web/ and write compact JSON summaries of every wave.

    python -m hfie.site                    # data/ -> _site/
    python -m hfie.site --data data_dryrun --out _site_dry

Output (all read by web/app.js):
    data/index.json            study design, labels, one entry per wave
    data/series_YYYY-MM.json   mean answers per wave x model x persona x arm (incl. "all")
    data/waves_YYYY-MM.json    per-wave detail, one object per wave of that month:
                               distributions, consistency, quality, Q1 anchor, news
With --artifact it also writes artifact.html, the page body without <html>/<head>/<body>,
for publishing as a claude.ai page (the data files are published beside it).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from .config import ROOT
from .questions import QUESTIONS

QCOLS = ["q1", "q4", "q5", "q2_mean", "q3_mean", "q2_sd", "q3_sd"]
ARMS = ["none", "general", "economy", "politics", "entertainment"]
PERSONAS = ["generic", "household", "firm", "forecaster"]
BIN_LABELS = ["Deflation ≥12%", "Deflation 8–12%", "Deflation 4–8%", "Deflation 2–4%", "Deflation 0–2%",
              "Inflation 0–2%", "Inflation 2–4%", "Inflation 4–8%", "Inflation 8–12%", "Inflation ≥12%"]
REPO = "https://github.com/alizarif/hf-ai-inflation-expectations"


def r(x, nd=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def short(model: str) -> str:
    return model.split("/", 1)[-1]


def label_et(slot_et: str) -> str:
    t = datetime.fromisoformat(slot_et)
    return f"{t:%a %b} {t.day}, {t:%H}:00 ET"


def wave_detail(df: pd.DataFrame, manifest: dict, news: dict) -> dict:
    models = sorted(df.model.unique())
    flag = "rescaled" if "rescaled" in df else ("corrected" if "corrected" in df else None)
    bins = []
    for m in ["All models"] + models:
        sub = df if m == "All models" else df[df.model == m]
        for q in ("q2", "q3"):
            ok = sub[sub[f"{q}_mean"].notna()]
            bins.append({"model": m, "q": q, "p": [r(ok[f"{q}_p{i}"].mean(), 2) for i in range(10)]})
    cons, qual, anchor = [], [], []
    total_cost = df.cost_usd.sum()
    for m in models:
        s = df[df.model == m]
        cons.append({"model": m, "q4": r(s.q4.mean()), "q2_mean": r(s.q2_mean.mean()), "gap_1y": r((s.q4 - s.q2_mean).mean()),
                     "q5": r(s.q5.mean()), "q3_mean": r(s.q3_mean.mean()), "gap_5y": r((s.q5 - s.q3_mean).mean()),
                     "p_deflation": r(s.q2_p_deflation.mean(), 2)})
        cell_sd = s.groupby(["persona", "arm"]).q4.std().mean()
        qual.append({"model": m, "share_ok": r((s.status == "ok").mean()), "valid_q2": r(s.q2_mean.notna().mean()),
                     "valid_q3": r(s.q3_mean.notna().mean()), "flagged": int(s[flag].astype(bool).sum()) if flag else 0,
                     "trial_sd_q4": r(cell_sd), "reasoning_tokens": r(s.reasoning_tokens.mean(), 0),
                     "latency_s": r(s.latency_s.mean(), 1), "cost_usd": r(s.cost_usd.sum(), 4),
                     "cost_share": r(s.cost_usd.sum() / total_cost if total_cost else None)})
        e, n = s[s.arm == "economy"].q1.dropna(), s[s.arm == "none"].q1.dropna()
        anchor.append({"model": m, "none_q1": r(n.mean()), "econ_q1": r(e.mean()), "econ_sd": r(e.std()),
                       "econ_min": r(e.min()), "econ_max": r(e.max())})
    sd_qs = ["q1", "q4", "q5", "q2_mean", "q3_mean"]
    trial_sd = []
    for m in ["All models"] + models:
        s = df if m == "All models" else df[df.model == m]
        cells = s.groupby(["model", "persona", "arm"])
        row = {"model": m, **{q: r(cells[q].std().mean()) for q in sd_qs}}
        row["identical_q4"] = r((cells.q4.std() == 0).mean())
        trial_sd.append(row)
    pooled = df.groupby("arm").q4.mean()
    summary = {"n_trials": len(df), "share_ok": r((df.status == "ok").mean()), "flag": flag,
               "n_flagged": int(df[flag].astype(bool).sum()) if flag else 0, "cost_usd": r(manifest.get("cost_usd"), 4),
               "none_q4": r(pooled.get("none")), "none_q5": r(df[df.arm == "none"].q5.mean()),
               **{f"{a}_q4": r(pooled.get(a) - pooled.get("none")) for a in ARMS[1:] if a in pooled}}
    news_out = {a: [{"title": it["title"], "source": it.get("source", ""), "url": it.get("url", "")} for it in s.get("items", [])]
                for a, s in news.items() if a != "none"}
    providers = {a: v.get("provider") for a, v in manifest.get("news", {}).items() if a != "none"}
    return {"wave_id": manifest["wave_id"], "label": label_et(manifest["slot_et"]), "summary": summary, "bins": bins,
            "bin_labels": BIN_LABELS, "consistency": cons, "trial_sd": trial_sd, "quality": qual, "anchor": anchor, "news": news_out,
            "news_providers": providers, "models": models,
            "manifest": {k: manifest.get(k) for k in ("design_version", "design_hash", "slot_et", "slot_utc", "started_utc",
                                                      "finished_utc", "lateness_minutes", "trials", "cost_usd")}}


def series_rows(df: pd.DataFrame, wave_idx: int, models: list[str]) -> list[list]:
    """[wave, model|-1, persona|-1, arm|-1, n, q1, q4, q5, q2_mean, q3_mean, q2_sd, q3_sd] for every combination."""
    rows = []
    mi = {m: i for i, m in enumerate(models)}
    for m in [None] + sorted(df.model.unique()):
        dm = df if m is None else df[df.model == m]
        for p in [None] + PERSONAS:
            dp = dm if p is None else dm[dm.persona == p]
            for a in [None] + ARMS:
                d = dp if a is None else dp[dp.arm == a]
                if d.empty:
                    continue
                rows.append([wave_idx, -1 if m is None else mi[m], -1 if p is None else PERSONAS.index(p),
                             -1 if a is None else ARMS.index(a), len(d)] + [r(d[c].mean()) for c in QCOLS])
    return rows


def build(data_dir: Path, out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    (out / "data").mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    files = sorted((data_dir / "waves").glob("*/*/*/*/responses.csv"))
    loaded = []
    for f in files:
        man = json.loads((f.parent / "manifest.json").read_text())
        df = pd.read_csv(f)
        df["model"] = df.model.map(short)
        news = json.loads((f.parent / "news.json").read_text())
        loaded.append((man, df, news, f.parent))
    loaded.sort(key=lambda x: x[0]["slot_utc"])
    models = sorted({m for _, df, _, _ in loaded for m in df.model.unique()})
    waves, months, details = [], {}, {}
    for i, (man, df, news, wdir) in enumerate(loaded):
        det = wave_detail(df, man, news)
        details.setdefault(man["slot_et"][:7], {})[man["wave_id"]] = det
        waves.append({"id": man["wave_id"], "label": det["label"], "slot_utc": man["slot_utc"], "slot_et": man["slot_et"],
                      "design": man.get("design_version", ""), "models": det["models"],
                      "trial_sd": {t["model"]: [t[q] for q in ("q1", "q4", "q5", "q2_mean", "q3_mean")] for t in det["trial_sd"]}, "path": str(wdir.relative_to(data_dir.parent)),
                      **{k: det["summary"][k] for k in ("n_trials", "share_ok", "n_flagged", "flag", "cost_usd", "none_q4",
                                                        "none_q5", "economy_q4", "politics_q4", "general_q4", "entertainment_q4")
                         if k in det["summary"]}})
        months.setdefault(man["slot_et"][:7], []).extend(series_rows(df, i, models))
    for month, rows in months.items():
        (out / "data" / f"series_{month}.json").write_text(json.dumps({"rows": rows}, separators=(",", ":")))
    for month, d in details.items():
        (out / "data" / f"waves_{month}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    index = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": REPO, "models": models, "personas": PERSONAS, "arms": ARMS, "qcols": QCOLS,
        "series_files": [f"series_{m}.json" for m in sorted(months)],
        "wave_files": {m: f"waves_{m}.json" for m in sorted(details)}, "series_fields": ["wave", "model", "persona", "arm", "n"] + QCOLS,
        "waves": waves,
        "design": {"models": cfg["models"], "personas": cfg["personas"], "arms": {a: v.get("query") for a, v in cfg["arms"].items()},
                   "trials": cfg["trials"], "system_prompt": " ".join(cfg["system_prompt"].split()),
                   "answer_instruction": cfg["answer_instruction"], "questions": QUESTIONS,
                   "schedule": cfg["schedule"], "design_version": cfg["design_version"]},
    }
    (out / "data" / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    return index


def artifact_page(out: Path) -> Path:
    """claude.ai pages get their own <html>/<head>/<body> skeleton: keep only the title,
    font/style links and the body content."""
    html = (out / "index.html").read_text(encoding="utf-8")
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    keep = [m.group(0) for m in re.finditer(r"<title>.*?</title>|<link [^>]*>", head)]
    page = "\n".join(keep[:1] + ['<meta name="claude:viewport-fit-sides" content="cover">'] + keep[1:]) + "\n" + body.strip() + "\n"
    path = out / "artifact.html"
    path.write_text(page, encoding="utf-8")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="_site")
    ap.add_argument("--artifact", action="store_true", help="also write artifact.html for a claude.ai page")
    a = ap.parse_args(argv)
    idx = build(ROOT / a.data, ROOT / a.out)
    if a.artifact:
        artifact_page(ROOT / a.out)
    print(f"Site written to {a.out}: {len(idx['waves'])} waves, {len(idx['series_files'])} series file(s)")


if __name__ == "__main__":
    main()
