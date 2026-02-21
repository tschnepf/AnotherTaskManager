from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from mobile_api.apns import APNSConfigError, is_dead_token_failure, send_push_notification
from mobile_api.models import MobileDevice, NotificationDelivery, NotificationPreference


def _max_attempts() -> int:
    return max(1, int(getattr(settings, "MOBILE_NOTIFICATION_MAX_ATTEMPTS", 5)))


def _lease_seconds() -> int:
    return max(15, int(getattr(settings, "MOBILE_NOTIFICATION_LEASE_SECONDS", 60)))


def _retry_base_seconds() -> int:
    return max(5, int(getattr(settings, "MOBILE_NOTIFICATION_RETRY_BASE_SECONDS", 30)))


def _retry_delay_seconds(attempts: int) -> int:
    # Exponential backoff with a bounded upper limit.
    return min(60 * 30, _retry_base_seconds() * (2 ** max(0, attempts - 1)))


def _reminder_offset_minutes(pref: NotificationPreference | None) -> int:
    if pref is None:
        return 30
    return max(1, min(int(pref.due_soon_offset_minutes), 24 * 60))


def _task_reminder_prefix(task_id: str) -> str:
    return f"task-reminder:{task_id}:"


def enqueue_notification(
    *,
    device: MobileDevice,
    dedupe_key: str,
    payload: dict,
    available_at=None,
) -> NotificationDelivery:
    delivery, _ = NotificationDelivery.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "organization": device.organization,
            "user": device.user,
            "device": device,
            "payload": payload,
            "available_at": available_at or timezone.now(),
        },
    )
    return delivery


def cancel_notifications_for_task(task_id: str) -> int:
    prefix = _task_reminder_prefix(str(task_id))
    updated = NotificationDelivery.objects.filter(
        dedupe_key__startswith=prefix,
        state__in=[
            NotificationDelivery.State.PENDING,
            NotificationDelivery.State.SENDING,
            NotificationDelivery.State.FAILED,
        ],
    ).update(
        state=NotificationDelivery.State.CANCELED,
        locked_until=None,
        locked_by="",
        updated_at=timezone.now(),
    )
    return int(updated)


def refresh_task_due_notifications(task) -> int:
    """
    Cancel stale reminders and enqueue new due reminders for the effective owner.
    """

    task_id = str(task.id)
    cancel_notifications_for_task(task_id)

    if task.due_at is None:
        return 0
    if task.status in {task.Status.DONE, task.Status.ARCHIVED}:
        return 0

    target_user = task.assigned_to_user or task.created_by_user
    if target_user is None:
        return 0

    pref = NotificationPreference.objects.filter(user=target_user, organization=task.organization).first()
    offset_minutes = _reminder_offset_minutes(pref)
    available_at = task.due_at - timedelta(minutes=offset_minutes)
    now = timezone.now()
    if available_at < now:
        available_at = now

    devices = MobileDevice.objects.filter(user=target_user, organization=task.organization)
    count = 0
    for device in devices:
        dedupe_key = f"{_task_reminder_prefix(task_id)}{device.id}"
        payload = {
            "type": "task_due_reminder",
            "task_id": task_id,
            "title": task.title,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        }
        enqueue_notification(
            device=device,
            dedupe_key=dedupe_key,
            payload=payload,
            available_at=available_at,
        )
        count += 1
    return count


@dataclass
class DeliveryBatch:
    worker_id: str
    delivery_ids: list[str]


def claim_pending_deliveries(*, worker_id: str, batch_size: int = 100) -> DeliveryBatch:
    now = timezone.now()
    lease_until = now + timedelta(seconds=_lease_seconds())
    claimed: list[str] = []

    with transaction.atomic():
        queryset = (
            NotificationDelivery.objects.select_for_update(skip_locked=True)
            .filter(
                state__in=[NotificationDelivery.State.PENDING, NotificationDelivery.State.FAILED],
                available_at__lte=now,
            )
            .filter(Q(locked_until__isnull=True) | Q(locked_until__lt=now))
            .order_by("available_at", "created_at")[: max(1, batch_size)]
        )
        deliveries = list(queryset)
        for delivery in deliveries:
            delivery.state = NotificationDelivery.State.SENDING
            delivery.locked_by = worker_id
            delivery.locked_until = lease_until
            delivery.attempts = int(delivery.attempts) + 1
            delivery.save(update_fields=["state", "locked_by", "locked_until", "attempts", "updated_at"])
            claimed.append(str(delivery.id))

    return DeliveryBatch(worker_id=worker_id, delivery_ids=claimed)


def _finalize_delivery(
    delivery: NotificationDelivery,
    *,
    state: str,
    provider_response: dict,
    available_at=None,
    delete_dead_token: bool = False,
) -> None:
    delivery.state = state
    delivery.provider_response = provider_response
    delivery.locked_until = None
    delivery.locked_by = ""
    if available_at is not None:
        delivery.available_at = available_at
    if state == NotificationDelivery.State.SENT:
        delivery.sent_at = timezone.now()
    delivery.save(
        update_fields=[
            "state",
            "provider_response",
            "locked_until",
            "locked_by",
            "available_at",
            "sent_at",
            "updated_at",
        ]
    )
    if delete_dead_token and delivery.device_id:
        MobileDevice.objects.filter(id=delivery.device_id).delete()


def dispatch_claimed_deliveries(batch: DeliveryBatch) -> dict:
    sent = 0
    retried = 0
    failed = 0
    canceled = 0
    skipped = 0

    for delivery in (
        NotificationDelivery.objects.select_related("device")
        .filter(id__in=batch.delivery_ids, locked_by=batch.worker_id)
        .order_by("created_at")
    ):
        if delivery.device is None:
            _finalize_delivery(
                delivery,
                state=NotificationDelivery.State.CANCELED,
                provider_response={"reason": "missing_device"},
            )
            canceled += 1
            continue

        try:
            token = delivery.device.get_apns_token()
            result = send_push_notification(device_token=token, payload=delivery.payload or {})
        except APNSConfigError as exc:
            next_at = timezone.now() + timedelta(seconds=_retry_delay_seconds(int(delivery.attempts)))
            _finalize_delivery(
                delivery,
                state=NotificationDelivery.State.FAILED,
                provider_response={"error": str(exc), "retryable": True},
                available_at=next_at,
            )
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001
            if int(delivery.attempts) >= _max_attempts():
                _finalize_delivery(
                    delivery,
                    state=NotificationDelivery.State.FAILED,
                    provider_response={"error": str(exc), "retryable": False},
                )
                failed += 1
            else:
                next_at = timezone.now() + timedelta(seconds=_retry_delay_seconds(int(delivery.attempts)))
                _finalize_delivery(
                    delivery,
                    state=NotificationDelivery.State.FAILED,
                    provider_response={"error": str(exc), "retryable": True},
                    available_at=next_at,
                )
                retried += 1
            continue

        if result.ok:
            _finalize_delivery(
                delivery,
                state=NotificationDelivery.State.SENT,
                provider_response=result.as_dict(),
            )
            sent += 1
            continue

        if is_dead_token_failure(result):
            _finalize_delivery(
                delivery,
                state=NotificationDelivery.State.CANCELED,
                provider_response=result.as_dict(),
                delete_dead_token=True,
            )
            canceled += 1
            continue

        if int(delivery.attempts) >= _max_attempts():
            _finalize_delivery(
                delivery,
                state=NotificationDelivery.State.FAILED,
                provider_response=result.as_dict(),
            )
            failed += 1
            continue

        next_at = timezone.now() + timedelta(seconds=_retry_delay_seconds(int(delivery.attempts)))
        _finalize_delivery(
            delivery,
            state=NotificationDelivery.State.FAILED,
            provider_response=result.as_dict(),
            available_at=next_at,
        )
        retried += 1

    for stale in NotificationDelivery.objects.filter(id__in=batch.delivery_ids, locked_by=batch.worker_id):
        # Safety release for any rows not finalized in the delivery loop.
        stale.locked_by = ""
        stale.locked_until = None
        stale.save(update_fields=["locked_by", "locked_until", "updated_at"])
        skipped += 1

    return {
        "worker_id": batch.worker_id,
        "claimed": len(batch.delivery_ids),
        "sent": sent,
        "retried": retried,
        "failed": failed,
        "canceled": canceled,
        "skipped": skipped,
    }
