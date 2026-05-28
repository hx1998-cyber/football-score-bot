from __future__ import annotations

from datetime import datetime


def now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")
