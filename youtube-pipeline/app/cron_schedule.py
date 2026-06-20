from __future__ import annotations

from datetime import datetime, timedelta


RANGES = [
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 6),
]


def next_cron_time(expression: str, after: datetime) -> datetime:
    fields = parse_cron(expression)
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = candidate + timedelta(days=366)
    while candidate <= deadline:
        values = [candidate.minute, candidate.hour, candidate.day, candidate.month, candidate.weekday()]
        if all(value in allowed for value, allowed in zip(values, fields, strict=True)):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"Cron expression did not match within one year: {expression}")


def seconds_until_next_cron(expression: str, now: datetime | None = None) -> float:
    current = now or datetime.now()
    return max(0.0, (next_cron_time(expression, current) - current).total_seconds())


def parse_cron(expression: str) -> list[set[int]]:
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must contain 5 fields: minute hour day month weekday")
    return [_parse_field(part, low, high) for part, (low, high) in zip(parts, RANGES, strict=True)]


def _parse_field(raw: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        item = part.strip()
        if not item:
            raise ValueError(f"Invalid cron field: {raw}")
        if "/" in item:
            base, step_raw = item.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                raise ValueError(f"Invalid cron step: {item}")
        else:
            base = item
            step = 1
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_raw, end_raw = base.split("-", 1)
            start, end = int(start_raw), int(end_raw)
        else:
            start = end = int(base)
        if start < low or end > high or start > end:
            raise ValueError(f"Cron value out of range: {item}")
        values.update(range(start, end + 1, step))
    return values
