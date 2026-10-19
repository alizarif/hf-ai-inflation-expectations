"""Run calendar for the README: one row per New York day, one column per wave slot.

Cells show the slot's time in Tehran and its status:
🟢 completed · 🔴 missed (slot window passed without a wave) · 🟡 due now · ⏳ next · ⚪ scheduled.
Rebuilt after every wave by hfie.charts.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
TEH = ZoneInfo("Asia/Tehran")
SLOTS = (0, 4, 8, 12, 16, 20)


def _slot(day, hour):
    return datetime(day.year, day.month, day.day, hour, tzinfo=NY)


def _teh(t: datetime, ny_day) -> str:
    local = t.astimezone(TEH)
    shift = (local.date() - ny_day).days
    return f"{local:%H:%M}" + (f" (+{shift}d)" if shift > 0 else "")


def render(data_dir: Path, now: datetime | None = None, max_days: int = 14) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    done = {p.name: p for p in (data_dir / "waves").glob("*/*/*/*") if (p / "responses.csv").exists()}
    if not done:
        return "_No waves yet._"
    first = min(datetime.strptime(w[:13], "%Y-%m-%dT%H").replace(tzinfo=NY) for w in done)
    upcoming = [_slot(now.date() + timedelta(days=d), h) for d in (0, 1) for h in SLOTS]
    nxt = min(t for t in upcoming if t > now)
    cur = max(t for t in [_slot(now.date(), h) for h in SLOTS] if t <= now)
    cur_due = cur.strftime("%Y-%m-%dT%HET") not in done

    days, d = [], (now + timedelta(days=1)).date()
    while d >= first.date() and len(days) < max_days:
        days.append(d)
        d -= timedelta(days=1)

    head = "| New York date | " + " | ".join(f"{h:02d}:00 ET" for h in SLOTS) + " |"
    rows = [head, "|---|" + "---|" * len(SLOTS)]
    for day in days:
        cells = []
        for h in SLOTS:
            t = _slot(day, h)
            wid = t.strftime("%Y-%m-%dT%HET")
            teh = _teh(t, day)
            if wid in done:
                icon = "🟢"
            elif t < first:
                cells.append("·")
                continue
            elif t == cur and cur_due:
                icon = "🟡"
            elif t + timedelta(hours=4) <= now:
                icon = "🔴"
            elif t == nxt:
                icon = "⏳"
            else:
                icon = "⚪"
            cells.append(f"{icon} {teh}")
        rows.append(f"| {day:%a %b} {day.day} | " + " | ".join(cells) + " |")

    def both(t):
        return (f"**{t:%a %b} {t.day}, {t:%H:%M} New York** ({t:%Z}) = "
                f"**{t.astimezone(TEH):%a %b} {t.astimezone(TEH).day}, {t.astimezone(TEH):%H:%M} Tehran**")

    n_done = len(done)
    lines = []
    if cur_due:
        lines.append(f"**Running or due now:** {both(cur)}  ")
    lines.append(f"**Next scheduled wave:** {both(nxt)}  ")
    lines.append(f"**Completed waves:** {n_done} · calendar updated {now:%b} {now.day}, {now:%H:%M} New York "
                 f"/ {now.astimezone(TEH):%H:%M} Tehran (it refreshes after every wave)")
    lines += ["", "Times in the cells are **Tehran time** for each New York slot. "
              "🟢 completed · 🔴 missed · 🟡 due now · ⏳ next · ⚪ scheduled", ""] + rows
    if len(days) == max_days:
        lines.append(f"\nOlder days: see [`data/waves_index.csv`](data/waves_index.csv).")
    return "\n".join(lines)


def update_readme(readme: Path, data_dir: Path, now: datetime | None = None) -> None:
    text = readme.read_text(encoding="utf-8")
    block = f"<!-- CALENDAR:START -->\n{render(data_dir, now)}\n<!-- CALENDAR:END -->"
    if "<!-- CALENDAR:START -->" in text:
        text = re.sub(r"<!-- CALENDAR:START -->.*?<!-- CALENDAR:END -->", lambda _: block, text, flags=re.S)
    else:   # first time: insert right under the title line
        title, rest = text.split("\n", 1)
        text = f"{title}\n\n## Run calendar\n\n{block}\n{rest}"
    readme.write_text(text, encoding="utf-8")
