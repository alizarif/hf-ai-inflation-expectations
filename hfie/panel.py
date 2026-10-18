"""Stack every wave into a tidy panel (one row per trial; data/panel/panel_YYYY-MM.csv)
plus a wave index (data/waves_index.csv)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def build(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    waves = sorted((data_dir / "waves").glob("*/*/*/*/responses.csv"))
    if not waves:
        return pd.DataFrame(), pd.DataFrame()
    panel = pd.concat([pd.read_csv(p) for p in waves], ignore_index=True)
    panel = panel.sort_values(["slot_utc", "model", "persona", "arm", "trial"]).reset_index(drop=True)
    index = []
    for p in waves:
        m = json.loads((p.parent / "manifest.json").read_text())
        index.append({
            "wave_id": m["wave_id"], "slot_et": m["slot_et"], "slot_utc": m["slot_utc"],
            "n_trials": m["n_trials"], "n_ok": m["status_counts"].get("ok", 0),
            "n_partial": m["status_counts"].get("partial", 0), "n_failed": m["status_counts"].get("failed", 0),
            "n_corrected": m["n_corrected"], "cost_usd": m["cost_usd"], "lateness_minutes": m["lateness_minutes"],
            "arms_dropped": ";".join(m["arms_dropped"]), "design_hash": m["design_hash"],
            **{f"news_{a}": f"{v['provider']}:{v['n_items']}" for a, v in m["news"].items() if a != "none"},
        })
    index = pd.DataFrame(index).sort_values("slot_utc").reset_index(drop=True)
    # one file per month keeps every file far below GitHub's 100 MB limit
    month = pd.to_datetime(panel.slot_et.str[:7] + "-01")
    (data_dir / "panel").mkdir(exist_ok=True)
    for m, part in panel.groupby(month.dt.strftime("%Y-%m")):
        part.to_csv(data_dir / "panel" / f"panel_{m}.csv", index=False)
    index.to_csv(data_dir / "waves_index.csv", index=False)
    return panel, index
