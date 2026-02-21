import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Task


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_mobile_task_crud_and_cross_tenant_404():
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    user_a = User.objects.create_user(email="a-mobile@example.com", password="StrongPass123!", organization=org_a)
    user_b = User.objects.create_user(email="b-mobile@example.com", password="StrongPass123!", organization=org_b)

    token = RefreshToken.for_user(user_a)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task 1", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="crud-key-1",
    )
    assert create.status_code == 201
    task_id = create.data["id"]

    detail = client.get(f"/api/mobile/v1/tasks/{task_id}")
    assert detail.status_code == 200

    patch = client.patch(f"/api/mobile/v1/tasks/{task_id}", {"title": "Task 1 updated"}, format="json")
    assert patch.status_code == 200
    assert patch.data["title"] == "Task 1 updated"

    tenant_b_task = Task.objects.create(
        organization=org_b,
        created_by_user=user_b,
        title="Tenant B",
        area=Task.Area.WORK,
    )
    cross_tenant = client.get(f"/api/mobile/v1/tasks/{tenant_b_task.id}")
    assert cross_tenant.status_code == 404

    delete = client.delete(f"/api/mobile/v1/tasks/{task_id}")
    assert delete.status_code == 204
