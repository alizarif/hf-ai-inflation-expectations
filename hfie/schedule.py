"""Wave slots on the New York clock (00, 04, 08, 12, 16, 20 local time)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


@dataclass(frozen=True)
class Slot:
    local: datetime          # tz-aware, America/New_York
    utc: datetime

    @property
    def wave_id(self) -> str:
        """e.g. 2026-10-18T04ET (sortable, unique per NY slot)."""
        return self.local.strftime("%Y-%m-%dT%H") + "ET"

    @property
    def rel_dir(self) -> str:
        return self.local.strftime("%Y/%m/%d/") + self.wave_id


def current_slot(now: datetime | None, tz: str, slot_hours: list[int]) -> Slot:
    """The latest slot start at or before `now` (in the study time zone)."""
    zone = ZoneInfo(tz)
    now = (now or datetime.now(UTC)).astimezone(zone)
    hour = max(h for h in slot_hours if h <= now.hour)
    local = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return Slot(local=local, utc=local.astimezone(UTC))


def slot_from_wave_id(wave_id: str, tz: str) -> Slot:
    local = datetime.strptime(wave_id.removesuffix("ET"), "%Y-%m-%dT%H").replace(tzinfo=ZoneInfo(tz))
    return Slot(local=local, utc=local.astimezone(UTC))
