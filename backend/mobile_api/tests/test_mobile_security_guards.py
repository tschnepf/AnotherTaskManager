import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Task


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_mobile_cross_tenant_task_access_returns_404():
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")
    user_a = User.objects.create_user(email="a@example.com", password="StrongPass123!", organization=org_a)
    user_b = User.objects.create_user(email="b@example.com", password="StrongPass123!", organization=org_b)

    task_b = Task.objects.create(
        organization=org_b,
        created_by_user=user_b,
        title="Tenant B Task",
        area=Task.Area.WORK,
    )

    token = RefreshToken.for_user(user_a)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    res = client.get(f"/api/mobile/v1/tasks/{task_b.id}")
    assert res.status_code == 404
