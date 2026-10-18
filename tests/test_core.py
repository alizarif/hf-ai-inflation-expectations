from datetime import datetime, timezone

import pytest

from hfie.config import load_config
from hfie.parse import density_stats, parse_density, parse_point, parse_reply, split_answers
from hfie.prompts import build_messages
from hfie.schedule import current_slot, slot_from_wave_id

HOURS = [0, 4, 8, 12, 16, 20]
NY = "America/New_York"


# ---------------- schedule: NY slots across daylight-saving time
@pytest.mark.parametrize("utc, wave", [
    ("2026-10-18T08:05:00", "2026-10-18T04ET"),   # EDT: 04 NY = 08 UTC
    ("2026-10-18T09:05:00", "2026-10-18T04ET"),   # second trigger the same slot -> skip in runner
    ("2026-12-01T09:05:00", "2026-12-01T04ET"),   # EST: 04 NY = 09 UTC
    ("2026-12-01T08:05:00", "2026-12-01T00ET"),   # EST early trigger maps to previous slot
    ("2026-10-19T00:30:00", "2026-10-18T20ET"),   # 20 NY = 00 UTC next day (EDT)
])
def test_slots(utc, wave):
    now = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc)
    assert current_slot(now, NY, HOURS).wave_id == wave


def test_slot_roundtrip():
    s = slot_from_wave_id("2026-12-01T04ET", NY)
    assert s.utc.hour == 9 and s.rel_dir == "2026/12/01/2026-12-01T04ET"


# ---------------- parsing
def test_point_formats():
    assert parse_point("3.2")[0] == 3.2
    assert parse_point("[3.2 %,]")[0] == 3.2
    assert parse_point("-1.5 percent")[0] == -1.5
    assert parse_point("Over the next 12 months, I expect the rate of inflation to be 3.4 %")[0] == 3.4
    assert parse_point("3-4%")[0] is None
    assert parse_point("")[0] is None


def test_density_formats():
    good = "[0.00%,0.00%,0.00%,0.00%,2.50%,12.50%,45%,30%,7%,3%]"
    probs, why = parse_density(good, 0.1)
    assert why == "" and sum(probs) == pytest.approx(100)
    assert parse_density("[0,0,0,0,2,13,45,30,7,9]", 0.1)[0] is None          # sums to 106
    assert parse_density("[10,20,30]", 0.1)[0] is None                        # wrong length
    stats = density_stats([0, 0, 0, 0, 0, 0, 100, 0, 0, 0])
    assert stats["mean"] == 3 and stats["sd"] == 0


def test_split_handles_markdown_labels():
    text = "**Q1_I:** 3.1\n**Q2_I:** [0,0,0,0,5,15,40,30,7,3]\nQ3_I: [0,0,0,0,5,20,45,20,7,3]\nQ4: 3%\nQ5_I: 2.6%"
    seg = split_answers(text)
    assert set(seg) == {"Q1_I", "Q2_I", "Q3_I", "Q4_I", "Q5_I"}
    parsed = parse_reply(text)
    assert all(r["ok"] for r in parsed.values())
    assert parsed["Q4_I"]["value"] == 3 and parsed["Q5_I"]["value"] == 2.6


# ---------------- prompts
def test_prompts():
    cfg = load_config()
    slot = slot_from_wave_id("2026-10-18T04ET", NY)
    snap = {"text": "[1] Headline (example.com)\nExcerpt", "collected_at_utc": "2026-10-18T08:01:00+00:00"}
    sys_msg, user = build_messages(cfg, "generic", snap, slot)
    assert "Today is Sunday, October 18, 2026, 08:00 UTC." in sys_msg["content"]
    assert "  " not in sys_msg["content"]                          # empty persona leaves no gap
    assert user["content"].index("Headline") < user["content"].index("Q1_I:") < user["content"].index("Q5_I:")
    _, user_none = build_messages(cfg, "firm", {"text": ""}, slot)
    assert "news" not in user_none["content"].split("Q1_I")[0].lower()
    sys_firm, _ = build_messages(cfg, "firm", {"text": ""}, slot)
    assert "Act as the CEO of a US firm." in sys_firm["content"]


# ---------------- credentials never reach output files
def test_scrub_and_key_strip(monkeypatch):
    from hfie.openrouter import OpenRouterClient, scrub
    fake = "sk-or-v1-" + "a1b2c3" * 8
    assert fake not in scrub(f"Invalid header value: 'Bearer {fake}\\n'")
    monkeypatch.setenv("OPENROUTER_API_KEY", fake + "\n")
    assert OpenRouterClient().api_key == fake
