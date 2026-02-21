from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from mobile_api.models import IdempotencyRecord, NotificationDelivery
from tasks.models import TaskChangeEvent


@shared_task(name="mobile_api.purge_task_change_events")
def purge_task_change_events() -> dict:
    retention_days = int(getattr(settings, "MOBILE_EVENT_RETENTION_DAYS", 30))
    cutoff = timezone.now() - timedelta(days=max(1, retention_days))
    deleted, _ = TaskChangeEvent.objects.filter(occurred_at__lt=cutoff).delete()
    return {"deleted": deleted, "retention_days": retention_days}


@shared_task(name="mobile_api.purge_idempotency_records")
def purge_idempotency_records() -> dict:
    deleted, _ = IdempotencyRecord.objects.filter(expires_at__lt=timezone.now()).delete()
    return {"deleted": deleted}


@shared_task(name="mobile_api.purge_notification_deliveries")
def purge_notification_deliveries() -> dict:
    retention_days = int(getattr(settings, "MOBILE_NOTIFICATION_DELIVERY_RETENTION_DAYS", 30))
    cutoff = timezone.now() - timedelta(days=max(1, retention_days))
    deleted, _ = NotificationDelivery.objects.filter(
        updated_at__lt=cutoff,
        state__in=[
            NotificationDelivery.State.SENT,
            NotificationDelivery.State.FAILED,
            NotificationDelivery.State.CANCELED,
        ],
    ).delete()
    return {"deleted": deleted, "retention_days": retention_days}
