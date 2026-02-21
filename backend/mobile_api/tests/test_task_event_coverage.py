import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Task, TaskChangeEvent


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_task_reorder_emits_change_events():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="events@example.com", password="StrongPass123!", organization=org)

    task_a = Task.objects.create(organization=org, created_by_user=user, title="A", area=Task.Area.WORK, position=1)
    task_b = Task.objects.create(organization=org, created_by_user=user, title="B", area=Task.Area.WORK, position=2)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    before = TaskChangeEvent.objects.count()
    res = client.post(f"/tasks/{task_b.id}/reorder/", {"target_task_id": str(task_a.id), "placement": "before"})
    assert res.status_code == 200

    after = TaskChangeEvent.objects.count()
    assert after > before
    assert TaskChangeEvent.objects.filter(payload_summary__reordered=True).exists()
