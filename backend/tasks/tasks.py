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


@shared_task(name="tasks.sync_inbound_imap")
def sync_inbound_imap_task(max_messages: int = 25):
    from core.email_mode import INBOUND_EMAIL_MODE_IMAP, get_inbound_email_mode
    from core.models import Organization
    from tasks.email_imap_service import sync_inbound_imap

    if get_inbound_email_mode() != INBOUND_EMAIL_MODE_IMAP:
        return {"status": "skipped", "reason": "inbound email mode is not imap"}

    processed_orgs = 0
    total_processed = 0
    total_created = 0
    failed = []

    organizations = Organization.objects.exclude(imap_username="").exclude(imap_password="")
    for organization in organizations:
        processed_orgs += 1
        try:
            result = sync_inbound_imap(organization, max_messages=max_messages)
            total_processed += int(result.get("processed", 0))
            total_created += int(result.get("created", 0))
            for failure in result.get("failed", []):
                failed.append({"organization_id": str(organization.id), **failure})
        except ValueError as exc:
            failed.append({"organization_id": str(organization.id), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            failed.append({"organization_id": str(organization.id), "message": str(exc)})

    return {
        "status": "ok",
        "organizations": processed_orgs,
        "processed": total_processed,
        "created": total_created,
        "failed": failed,
    }
