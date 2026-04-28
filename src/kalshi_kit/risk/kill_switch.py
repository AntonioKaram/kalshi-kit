from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class KillSwitchState:
    active: bool = False
    reason: str = ""
    triggered_at: datetime | None = None


class KillSwitch:
    def __init__(self) -> None:
        self.state = KillSwitchState()

    def trip(self, *, reason: str, ts: datetime) -> bool:
        if self.state.active:
            return False
        self.state = KillSwitchState(active=True, reason=reason, triggered_at=ts)
        return True

    def clear(self) -> None:
        self.state = KillSwitchState()
