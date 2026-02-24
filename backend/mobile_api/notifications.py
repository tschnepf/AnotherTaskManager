from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from mobile_api.apns import APNSConfigError, is_dead_token_failure, send_push_notification
from mobile_api.models import MobileDevice, NotificationDelivery, NotificationPreference

logger = logging.getLogger(__name__)


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


def _task_change_push_enabled() -> bool:
    return (
        bool(getattr(settings, "MOBILE_API_ENABLED", False))
        and bool(getattr(settings, "APNS_ENABLED", False))
        and bool(getattr(settings, "MOBILE_TASK_CHANGE_PUSH_ENABLED", True))
    )


def _task_change_push_dedupe_window_seconds() -> int:
    return max(1, int(getattr(settings, "MOBILE_TASK_CHANGE_PUSH_DEDUPE_WINDOW_SECONDS", 10)))


def _task_change_push_batch_size() -> int:
    return max(1, int(getattr(settings, "MOBILE_TASK_CHANGE_PUSH_PROCESS_BATCH_SIZE", 200)))


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


def enqueue_task_change_sync_notifications(
    *,
    organization,
    event_id: int | None = None,
    event_type: str = "",
    task_id: str | None = None,
) -> int:
    if not _task_change_push_enabled():
        return 0

    org_id = str(getattr(organization, "id", organization))
    devices = MobileDevice.objects.filter(organization_id=org_id).only("id", "organization_id", "user_id")
    if not devices.exists():
        return 0

    dedupe_window_seconds = _task_change_push_dedupe_window_seconds()
    bucket = int(timezone.now().timestamp()) // dedupe_window_seconds
    created_count = 0
    for device in devices:
        dedupe_key = f"task-sync:{org_id}:{device.id}:{bucket}"
        payload = {
            "type": "task_change_sync_hint",
            "organization_id": org_id,
            "event_type": str(event_type or ""),
            "task_id": str(task_id) if task_id else None,
            "cursor_hint": str(event_id) if event_id is not None else None,
        }
        _, created = NotificationDelivery.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "organization_id": device.organization_id,
                "user_id": device.user_id,
                "device": device,
                "payload": payload,
                "available_at": timezone.now(),
            },
        )
        if created:
            created_count += 1
    return created_count


def trigger_pending_notification_processing(batch_size: int | None = None) -> bool:
    if not _task_change_push_enabled():
        return False
    if not bool(getattr(settings, "MOBILE_TASK_CHANGE_PUSH_TRIGGER_ASYNC", True)):
        return False

    effective_batch_size = max(1, int(batch_size or _task_change_push_batch_size()))

    try:
        from mobile_api.tasks import process_pending_notifications

        process_pending_notifications.apply_async(kwargs={"batch_size": effective_batch_size}, retry=False)
        return True
    except Exception:  # noqa: BLE001
        logger.warning("failed to trigger async mobile notification processing", exc_info=True)
        return False


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
