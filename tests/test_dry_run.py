"""End-to-end wave with simulated model answers (no network)."""
import gzip
import json

import pandas as pd

from hfie import run_wave
from hfie.charts import main as charts_main
from hfie.fake import FakeClient


def test_full_dry_wave(tmp_path, monkeypatch):
    out = tmp_path / "data"
    path = run_wave.run("dry-run", wave_id="2026-10-18T04ET", out=str(out), client=FakeClient(seed=1))
    df = pd.read_csv(path / "responses.csv")
    cfg_models, personas, arms, trials = 7, 4, 5, 3
    assert len(df) == cfg_models * personas * arms * trials
    assert (df.status == "ok").all()                    # broken densities fixed by the correction turn
    assert df.corrected.any() and (df.n_calls[df.corrected] == 2).all()
    news = json.loads((path / "news.json").read_text())
    assert news["none"]["text"] == "" and news["economy"]["n_items"] == 8
    with gzip.open(path / "raw.jsonl.gz", "rt") as fh:
        raw = [json.loads(line) for line in fh]
    assert sum(r["kind"] == "search" for r in raw) == 4 and sum(r["kind"] == "trial" for r in raw) == len(df)
    # second run of the same slot is skipped
    assert run_wave.run("dry-run", wave_id="2026-10-18T04ET", out=str(out), client=FakeClient()) is None
    # second wave + charts
    run_wave.run("dry-run", wave_id="2026-10-18T08ET", out=str(out), client=FakeClient(seed=2))
    monkeypatch.setattr("hfie.charts.ROOT", tmp_path)
    charts_main(["--data", "data", "--charts", "charts", "--no-readme"])
    assert len(list((tmp_path / "charts").glob("*.png"))) == 9
    assert len(pd.read_csv(out / "panel" / "panel_2026-10.csv")) == 2 * len(df)
