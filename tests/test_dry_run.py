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
    assert (df.status == "ok").all() and (df.n_calls == 1).all()   # one call per trial, never a follow-up
    assert df.rescaled.any()
    r = df[df.rescaled].iloc[0]
    assert r.q2_sum_raw == 106 and abs(sum(r[f"q2_p{i}"] for i in range(10)) - 100) < 1e-6
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


def test_failed_wave_is_not_marked_complete(tmp_path, monkeypatch):
    import pytest

    def no_network(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr("hfie.news.search_rss", no_network)

    class Down:
        def chat(self, model, messages, **extra):
            from hfie.openrouter import _result
            return _result("failed", {}, None, 1, 0.0, "HTTP 401: invalid key")

    with pytest.raises(run_wave.WaveFailed):
        run_wave.run("dry-run", wave_id="2026-10-18T04ET", out=str(tmp_path), client=Down(), models=["x/y"])
    assert not list(tmp_path.rglob("responses.csv"))


def test_site_build(tmp_path):
    from hfie import site
    out = tmp_path / "data"
    for w in ("2026-10-18T04ET", "2026-10-18T08ET"):
        run_wave.run("dry-run", wave_id=w, out=str(out), client=FakeClient(seed=3))
    idx = site.build(out, tmp_path / "_site")
    assert [w["id"] for w in idx["waves"]] == ["2026-10-18T04ET", "2026-10-18T08ET"]
    assert idx["waves"][0]["label"] == "Sun Oct 18, 04:00 ET"
    assert (tmp_path / "_site" / "index.html").exists() and (tmp_path / "_site" / "app.js").exists()
    series = json.loads((tmp_path / "_site" / "data" / "series_2026-10.json").read_text())["rows"]
    assert len({r[0] for r in series}) == 2
    detail = json.loads((tmp_path / "_site" / "data" / "waves" / "2026-10-18T08ET.json").read_text())
    assert detail["summary"]["flag"] == "rescaled" and len(detail["bins"]) == 2 * 8
