from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Organization, User
from mobile_api.cleanup_tasks import (
    purge_idempotency_records,
    purge_notification_deliveries,
    purge_task_change_events,
)
from mobile_api.models import IdempotencyRecord, MobileDevice, NotificationDelivery
from tasks.models import TaskChangeEvent


@pytest.mark.django_db
def test_cleanup_tasks_purge_expired_rows():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="cleanup@example.com", password="StrongPass123!", organization=org)

    event = TaskChangeEvent.objects.create(
        organization=org,
        event_type=TaskChangeEvent.EventType.CREATED,
        task_id=None,
        payload_summary={},
    )
    TaskChangeEvent.objects.filter(id=event.id).update(occurred_at=timezone.now() - timedelta(days=90))
    IdempotencyRecord.objects.create(
        user=user,
        endpoint="POST:/api/mobile/v1/tasks",
        idempotency_key="old",
        request_hash="abc",
        response_status=201,
        response_body={},
        expires_at=timezone.now() - timedelta(hours=1),
    )
    device = MobileDevice.objects.create(
        user=user,
        organization=org,
        apns_token_hash="hash",
        apns_environment=MobileDevice.APNsEnvironment.SANDBOX,
    )
    delivery = NotificationDelivery.objects.create(
        organization=org,
        user=user,
        device=device,
        dedupe_key="old-delivery",
        state=NotificationDelivery.State.SENT,
    )
    NotificationDelivery.objects.filter(id=delivery.id).update(updated_at=timezone.now() - timedelta(days=90))

    purge_task_change_events()
    purge_idempotency_records()
    purge_notification_deliveries()

    assert TaskChangeEvent.objects.count() == 0
    assert IdempotencyRecord.objects.count() == 0
    assert NotificationDelivery.objects.count() == 0
