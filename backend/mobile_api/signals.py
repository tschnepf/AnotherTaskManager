from __future__ import annotations

from datetime import timezone as dt_timezone

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from mobile_api.notifications import cancel_notifications_for_task, refresh_task_due_notifications
from tasks.models import Task, TaskChangeEvent


def _mobile_datetime(value):
    if value is None:
        return None
    dt = value
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    dt = dt.astimezone(dt_timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def _summary_from_task(task: Task) -> dict:
    return {
        "title": task.title,
        "is_completed": task.status in {Task.Status.DONE, Task.Status.ARCHIVED},
        "status": task.status,
        "priority": task.priority,
        "due_at": _mobile_datetime(task.due_at),
        "updated_at": _mobile_datetime(task.updated_at),
    }


@receiver(post_save, sender=Task)
def task_saved_emit_event(sender, instance: Task, created: bool, **kwargs):
    event_type = TaskChangeEvent.EventType.CREATED if created else TaskChangeEvent.EventType.UPDATED

    def _create_event():
        TaskChangeEvent.objects.create(
            organization=instance.organization,
            event_type=event_type,
            task_id=instance.id,
            payload_summary=_summary_from_task(instance),
        )

    transaction.on_commit(_create_event)
    transaction.on_commit(lambda: refresh_task_due_notifications(instance))


@receiver(post_delete, sender=Task)
def task_deleted_emit_event(sender, instance: Task, **kwargs):
    deleted_task_id = instance.id
    organization = instance.organization

    def _create_event():
        TaskChangeEvent.objects.create(
            organization=organization,
            event_type=TaskChangeEvent.EventType.DELETED,
            task_id=deleted_task_id,
            payload_summary=_summary_from_task(instance),
        )

    transaction.on_commit(_create_event)
    transaction.on_commit(lambda: cancel_notifications_for_task(str(deleted_task_id)))
