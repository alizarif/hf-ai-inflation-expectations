"""Rebuild the panel and every chart from all saved waves.

    python -m hfie.charts                 # data/ -> charts/
    python -m hfie.charts --data data_dryrun --charts charts_dryrun
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .config import ROOT  # noqa: E402
from .panel import build  # noqa: E402

# Control arm in neutral ink (dashed); treatment arms take categorical slots 1-4 in fixed order.
ARM_STYLE = {
    "none":          {"color": "#52514e", "ls": "--", "label": "No news"},
    "general":       {"color": "#2a78d6", "ls": "-", "label": "General news"},
    "economy":       {"color": "#eb6834", "ls": "-", "label": "Economy news"},
    "politics":      {"color": "#1baf7a", "ls": "-", "label": "Politics news"},
    "entertainment": {"color": "#eda100", "ls": "-", "label": "Entertainment (placebo)"},
}
PERSONA_LABEL = {"generic": "Generic agent", "household": "Household head", "firm": "Firm CEO",
                 "forecaster": "Professional forecaster"}
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.axisbelow": True, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 11,
    "axes.titleweight": "bold", "legend.frameon": False,
})


def _time_axis(ax, times=None):
    if times is not None and len(times):
        lo, hi = pd.Timestamp(min(times)), pd.Timestamp(max(times))
        pad = max(pd.Timedelta(hours=3), (hi - lo) * 0.04)
        ax.set_xlim(lo - pad, hi + pad)
    loc = mdates.AutoDateLocator(minticks=3, maxticks=7)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))


def _arm_lines(ax, df: pd.DataFrame, var: str):
    for arm, st in ARM_STYLE.items():
        s = df[df.arm == arm].groupby("t")[var].mean().dropna()
        if s.empty:
            continue
        ax.plot(s.index, s.values, color=st["color"], ls=st["ls"], lw=2, marker="o", ms=4, label=st["label"])
    _time_axis(ax, df.t.unique())


def by_persona(panel, var, title, ylabel, path):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True, sharey=True)
    for ax, (p, label) in zip(axes.flat, PERSONA_LABEL.items()):
        _arm_lines(ax, panel[panel.persona == p], var)
        ax.set_title(label, loc="left")
        ax.set_ylabel(ylabel)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 0.94))
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.01, 0.005, "Mean across models and trials per wave (New York time). Each model weighted equally.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.02, 1, 0.9))
    fig.savefig(path, dpi=130)
    plt.close(fig)


def arm_gaps(panel, path):
    base = panel[panel.arm == "none"].groupby(["t", "model", "persona"])["q4"].mean().rename("base")
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.axhline(0, color=MUTED, lw=1)
    for arm, st in ARM_STYLE.items():
        if arm == "none":
            continue
        d = panel[panel.arm == arm].groupby(["t", "model", "persona"])["q4"].mean().rename("v")
        gap = pd.concat([d, base], axis=1).dropna()
        if gap.empty:
            continue
        s = (gap.v - gap.base).groupby(level="t").mean()
        ax.plot(s.index, s.values, color=st["color"], lw=2, marker="o", ms=4, label=st["label"])
    _time_axis(ax, panel.t.unique())
    ax.set_ylabel("percentage points")
    ax.set_title("1-year expected inflation (Q4): each news arm minus the no-news arm", loc="left")
    ax.legend(loc="upper left", ncol=4)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def latest_by_model(panel, path):
    last = panel[panel.t == panel.t.max()]
    tab = last.groupby(["model", "arm"])["q4"].mean().unstack()
    models = sorted(tab.index, key=lambda m: tab.loc[m].mean())
    fig, ax = plt.subplots(figsize=(10, 0.55 * len(models) + 1.8))
    offsets = {a: (i - 2) * 0.12 for i, a in enumerate(ARM_STYLE)}
    for arm, st in ARM_STYLE.items():
        if arm not in tab:
            continue
        ys = [i + offsets[arm] for i in range(len(models))]
        ax.scatter(tab.loc[models, arm], ys, color=st["color"], s=44, label=st["label"],
                   marker="D" if arm == "none" else "o", edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.set_yticks(range(len(models)), [m.split("/", 1)[1] for m in models])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("expected inflation over next 12 months (%)")
    ax.set_title(f"Latest wave ({last.wave_id.iloc[0]}): 1-year expectation by model and news arm", loc="left")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12 - 0.3 / len(models)), ncol=5)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def quality(index, path):
    idx = index.copy()
    idx["t"] = pd.to_datetime(idx.slot_utc, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.6))
    a1.plot(idx.t, 100 * idx.n_ok / idx.n_trials, color="#2a78d6", lw=2, marker="o", ms=4)
    a1.set_ylim(0, 102)
    a1.set_title("Trials with all five answers valid (%)", loc="left")
    a2.bar(idx.t, idx.cost_usd, width=0.12, color="#2a78d6")
    a2.set_title("API cost per wave (USD)", loc="left")
    for ax in (a1, a2):
        _time_axis(ax, idx.t.tolist())
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def update_readme(index: pd.DataFrame, panel: pd.DataFrame, readme: Path):
    if not readme.exists() or index.empty:
        return
    last = index.iloc[-1]
    block = (f"<!-- STATUS:START -->\n**Latest wave:** `{last.wave_id}` · {int(last.n_trials)} trials · "
             f"{int(last.n_ok)} fully valid · {int(last.n_rescaled)} had a probability list rescaled to 100 · "
             f"cost ${last.cost_usd:.3f}  \n**Waves so far:** {len(index)} · **rows in panel:** {len(panel)} · "
             f"**total cost:** ${index.cost_usd.sum():.2f}\n<!-- STATUS:END -->")
    text = readme.read_text(encoding="utf-8")
    readme.write_text(re.sub(r"<!-- STATUS:START -->.*?<!-- STATUS:END -->", block, text, flags=re.S),
                      encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--charts", default="charts")
    ap.add_argument("--no-readme", action="store_true")
    a = ap.parse_args(argv)
    data_dir, out = ROOT / a.data, ROOT / a.charts
    panel, index = build(data_dir)
    if panel.empty:
        print("No waves yet; nothing to chart.")
        return
    out.mkdir(parents=True, exist_ok=True)
    panel["t"] = pd.to_datetime(panel.slot_utc, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    by_persona(panel, "q4", "Expected inflation, next 12 months (Q4)", "%", out / "q4_expected_1y.png")
    by_persona(panel, "q5", "Expected inflation, 12 months starting 4 years ahead (Q5)", "%", out / "q5_expected_5y.png")
    by_persona(panel, "q1", "Perceived inflation, last 12 months (Q1)", "%", out / "q1_perceived.png")
    by_persona(panel, "q2_mean", "Mean of 1-year probability distribution (Q2, bin midpoints)", "%",
               out / "q2_density_mean_1y.png")
    by_persona(panel, "q3_mean", "Mean of 5-year probability distribution (Q3, bin midpoints)", "%",
               out / "q3_density_mean_5y.png")
    by_persona(panel, "q2_sd", "Uncertainty of 1-year distribution (Q2 standard deviation)", "pp",
               out / "q2_density_sd_1y.png")
    arm_gaps(panel, out / "arm_gaps_q4.png")
    latest_by_model(panel, out / "latest_by_model_q4.png")
    quality(index, out / "data_quality.png")
    if not a.no_readme:
        update_readme(index, panel, ROOT / "README.md")
    print(f"Charts written to {out} ({len(index)} waves, {len(panel)} rows)")


if __name__ == "__main__":
    main()
