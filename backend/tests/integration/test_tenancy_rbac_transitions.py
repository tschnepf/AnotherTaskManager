import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Task


@pytest.mark.django_db
def test_integration_tenancy_boundary_and_transition_rules():
    org_a = Organization.objects.create(name="Org A")
    org_b = Organization.objects.create(name="Org B")

    owner_a = User.objects.create_user(email="owner-a@example.com", password="StrongPass123!", role=User.Role.OWNER, organization=org_a)
    member_b = User.objects.create_user(email="member-b@example.com", password="StrongPass123!", role=User.Role.MEMBER, organization=org_b)

    task_b = Task.objects.create(organization=org_b, created_by_user=member_b, title="Task B", area=Task.Area.WORK)

    client = APIClient()
    token_a = RefreshToken.for_user(owner_a)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a.access_token}")

    cross_tenant = client.get(f"/tasks/{task_b.id}/")
    assert cross_tenant.status_code == 404

    created = client.post("/tasks/", {"title": "Task A", "area": "work"}, format="json")
    assert created.status_code == 201
    task_id = created.data["id"]

    done = client.patch(f"/tasks/{task_id}/", {"status": "done"}, format="json")
    assert done.status_code == 200

    invalid_back_to_inbox = client.patch(f"/tasks/{task_id}/", {"status": "inbox"}, format="json")
    assert invalid_back_to_inbox.status_code == 409
