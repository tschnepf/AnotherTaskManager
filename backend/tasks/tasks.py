import os
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from tasks.models import Task


def _archive_after_days() -> int:
    raw_value = os.getenv("TASK_ARCHIVE_AFTER_DAYS", "7").strip()
    try:
        parsed = int(raw_value)
    except ValueError:
        return 7
    return max(1, parsed)


@shared_task(name="tasks.archive_completed")
def archive_completed_tasks(organization_id: str | None = None):
    archive_after_days = _archive_after_days()
    cutoff = timezone.now() - timedelta(days=archive_after_days)

    queryset = Task.objects.filter(
        status=Task.Status.DONE,
        completed_at__lt=cutoff,
    )
    if organization_id:
        queryset = queryset.filter(organization_id=organization_id)

    archived_count = queryset.update(
        status=Task.Status.ARCHIVED,
        completed_at=None,
        updated_at=timezone.now(),
    )
    return {
        "status": "ok",
        "archived_count": archived_count,
        "archive_after_days": archive_after_days,
    }
