# app/core/pipelines/cron.py
"""
Bounded Context:  BC6 — Observability & Storage / ops (schedules)
Responsibility:   Minimal 5-field cron expressions (no croniter dependency).
Owns:             CronError, CronExpr, parse_cron(), next_fire().
Public Surface:   parse_cron(expr) -> CronExpr; next_fire(expr, after) -> datetime (UTC).
Must NOT:         Import app.api / app.domain; add third-party dependencies.
Dependencies:     stdlib (datetime, re).
Reason To Change: Supported cron syntax changes.

Syntax: ``minute hour day-of-month month day-of-week`` evaluated in UTC.
Each field accepts ``*``, ``N``, ``A-B``, ``*/S``, ``A-B/S``, ``N/S`` and
comma lists; month and weekday accept names (``jan``…``dec``, ``sun``…``sat``);
weekday 0 and 7 are Sunday. Macros: ``@hourly``, ``@daily``/``@midnight``,
``@weekly``, ``@monthly``, ``@yearly``/``@annually``. As in Vixie cron, when
both day-of-month and day-of-week are restricted a day matches if EITHER does.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DAYS = {d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}
_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


class CronError(ValueError):
    """Invalid cron expression."""


@dataclass(frozen=True)
class CronExpr:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    doms: frozenset[int]
    months: frozenset[int]
    dows: frozenset[int]
    dom_star: bool
    dow_star: bool

    def day_matches(self, dt: datetime) -> bool:
        dom_ok = dt.day in self.doms
        dow_ok = ((dt.weekday() + 1) % 7) in self.dows  # Monday=0 → cron Monday=1
        if self.dom_star and self.dow_star:
            return True
        if self.dom_star:
            return dow_ok
        if self.dow_star:
            return dom_ok
        return dom_ok or dow_ok


def _value(token: str, lo: int, hi: int, names: dict[str, int] | None) -> int:
    t = token.strip().lower()
    if names and t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(f"invalid value {token!r}")
    v = int(t)
    if not lo <= v <= hi:
        raise CronError(f"value {v} out of range {lo}-{hi}")
    return v


def _field(text: str, lo: int, hi: int, names: dict[str, int] | None = None) -> tuple[frozenset[int], bool]:
    out: set[int] = set()
    star = text.strip() == "*"
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError("empty list element")
        step = 1
        if "/" in part:
            base, _, step_s = part.partition("/")
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"invalid step in {part!r}")
            step = int(step_s)
        else:
            base = part
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a, _, b = base.partition("-")
            start, end = _value(a, lo, hi, names), _value(b, lo, hi, names)
            if start > end:
                raise CronError(f"range {part!r} is reversed")
        else:
            start = _value(base, lo, hi, names)
            end = hi if "/" in part else start
        out.update(range(start, end + 1, step))
    return frozenset(out), star


def parse_cron(expr: str) -> CronExpr:
    """Parse a 5-field cron expression (or macro). Raises CronError."""
    raw = (expr or "").strip()
    text = _MACROS.get(raw.lower(), raw)
    parts = text.split()
    if len(parts) != 5:
        raise CronError(f"cron must have 5 fields (minute hour day month weekday), got {len(parts)}")
    try:
        minutes, _ = _field(parts[0], 0, 59)
        hours, _ = _field(parts[1], 0, 23)
        doms, dom_star = _field(parts[2], 1, 31)
        months, _ = _field(parts[3], 1, 12, _MONTHS)
        dows_raw, dow_star = _field(parts[4], 0, 7, _DAYS)
    except CronError as exc:
        raise CronError(f"invalid cron {expr!r}: {exc}") from exc
    dows = frozenset(0 if d == 7 else d for d in dows_raw)
    return CronExpr(raw, minutes, hours, doms, months, dows, dom_star, dow_star)


def next_fire(expr: str | CronExpr, after: datetime) -> datetime:
    """First matching minute strictly after ``after`` (UTC, second=0)."""
    cron = expr if isinstance(expr, CronExpr) else parse_cron(expr)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    t = after.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = t + timedelta(days=366 * 5)
    while t <= limit:
        if t.month not in cron.months:
            year, month = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
            t = t.replace(year=year, month=month, day=1, hour=0, minute=0)
            continue
        if not cron.day_matches(t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in cron.hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute not in cron.minutes:
            t += timedelta(minutes=1)
            continue
        return t
    raise CronError(f"cron {cron.expr!r} never fires")
