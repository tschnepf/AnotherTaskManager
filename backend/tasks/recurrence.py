from __future__ import annotations

from calendar import monthrange
from datetime import timedelta

from tasks.models import Task


def _add_months(value, months: int):
    month_index = value.month - 1 + months
    year = value.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def add_recurrence_interval(value, recurrence: str):
    if recurrence == Task.Recurrence.DAILY:
        return value + timedelta(days=1)
    if recurrence == Task.Recurrence.WEEKLY:
        return value + timedelta(weeks=1)
    if recurrence == Task.Recurrence.MONTHLY:
        return _add_months(value, 1)
    if recurrence == Task.Recurrence.YEARLY:
        return _add_months(value, 12)
    return None


def next_due_at_for_completion(reference_due_at, recurrence: str, completed_at):
    if reference_due_at is None or recurrence == Task.Recurrence.NONE:
        return None

    next_due_at = add_recurrence_interval(reference_due_at, recurrence)
    if next_due_at is None:
        return None

    for _ in range(240):
        if next_due_at > completed_at:
            return next_due_at
        next_due_at = add_recurrence_interval(next_due_at, recurrence)
        if next_due_at is None:
            return None

    return next_due_at
