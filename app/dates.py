"""Turn the many ways job sites write a posting date into YYYY-MM-DD.

  2026-04-27T00:00:00.000Z  -> 2026-04-27   (Notion / CSV exports, JSON-LD)
  2026-04-27                -> 2026-04-27
  27 Apr 2026, Apr 27 2026  -> 2026-04-27
  27/04/2026                -> 2026-04-27   (day first, as in Singapore)
  3 days ago, 2 weeks ago   -> counted back from `ref` (when it was saved)
  today, just now, 5 hours ago -> ref's date

Anything it can't read is kept as written, so nothing is lost.
"""
from __future__ import annotations

import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def _ok(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def normalize(value: str | None, ref: dt.date | dt.datetime | None = None) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    ref_d = (ref.date() if isinstance(ref, dt.datetime) else ref) or dt.date.today()
    low = s.lower()

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)  # ISO date or datetime
    if m:
        return _ok(int(m[1]), int(m[2]), int(m[3])) or s

    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", s)  # 27/04/2026 (day first)
    if m:
        return _ok(int(m[3]), int(m[2]), int(m[1])) or _ok(int(m[3]), int(m[1]), int(m[2])) or s

    m = re.match(r"^(\d{1,2})\s+([a-z]{3,9})\.?,?\s+(\d{4})$", low)  # 27 Apr 2026
    if m and m[2][:3] in MONTHS:
        return _ok(int(m[3]), MONTHS[m[2][:3]], int(m[1])) or s
    m = re.match(r"^([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$", low)  # Apr 27, 2026
    if m and m[1][:3] in MONTHS:
        return _ok(int(m[3]), MONTHS[m[1][:3]], int(m[2])) or s

    if re.search(r"\b(today|just now|moments? ago|now)\b", low) or re.search(r"\b(second|minute|hour)s?\b", low):
        return ref_d.isoformat()
    if "yesterday" in low:
        return (ref_d - dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+|an?|one)\+?\s*(day|week|month|year)s?\s*ago", low)
    if m:
        n = 1 if m[1] in ("a", "an", "one") else int(m[1])
        return (ref_d - dt.timedelta(days=n * UNIT_DAYS[m[2]])).isoformat()
    return s[:50]


def is_iso(value: str | None) -> bool:
    return bool(value) and bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
