import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Project, Task


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


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_mobile_tasks_accept_project_name_match_or_create():
    org = Organization.objects.create(name="Org Project")
    user = User.objects.create_user(email="mobile-project@example.com", password="StrongPass123!", organization=org)
    existing_project = Project.objects.create(organization=org, name="Client Alpha", area=Project.Area.WORK)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    matched = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task with existing project", "area": "work", "project": "client alpha"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="mobile-project-name-1",
    )
    assert matched.status_code == 201
    matched_task = Task.objects.get(id=matched.data["id"])
    assert matched_task.project_id == existing_project.id

    created = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task with new project", "area": "personal", "project": "Household"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="mobile-project-name-2",
    )
    assert created.status_code == 201
    created_task = Task.objects.get(id=created.data["id"])
    assert created_task.project is not None
    assert created_task.project.name == "Household"
    assert created_task.project.area == Project.Area.PERSONAL
