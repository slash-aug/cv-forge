"""Engineering experience counted from the master profile."""

from datetime import date


def _month_index(value: str) -> int:
    year, month = value.split("-")
    return int(year) * 12 + int(month) - 1


def engineering_months(master: dict, today: date) -> int:
    """Months of engineering work, with overlapping positions merged.

    A position covers [start month, end month + 1); an open end stops at
    today's month (exclusive). Entries without x-category count as engineering.
    """
    now = today.year * 12 + today.month - 1
    intervals = []
    for job in master.get("work", []):
        if job.get("x-category", "engineering") != "engineering":
            continue
        for pos in job.get("positions", []):
            start = _month_index(pos["startDate"])
            end = _month_index(pos["endDate"]) + 1 if pos.get("endDate") else now
            if end > start:
                intervals.append((start, end))
    total = 0
    cur_start = cur_end = None
    for start, end in sorted(intervals):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def years_limit(months: int) -> int:
    """floor(2 * months / 12 + 0.5), rounding half up."""
    return (months + 3) // 6
