import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Project, Task


@pytest.mark.django_db
def test_projects_tags_views_crud():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="u@example.com", password="StrongPass123!", organization=org)

    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    project_res = client.post(
        "/projects/",
        {"name": "Project A", "area": "work", "is_active": True, "is_shared": False},
        format="json",
    )
    assert project_res.status_code == 201

    tag_res = client.post("/tags/", {"name": "urgent", "color": "red"}, format="json")
    assert tag_res.status_code == 201

    view_res = client.post(
        "/views/",
        {
            "name": "Inbox View",
            "filter_json": {"status": "inbox"},
            "sort_field": "created_at",
            "sort_order": "desc",
            "is_shared": False,
        },
        format="json",
    )
    assert view_res.status_code == 201

    get_views = client.get("/views/")
    assert get_views.status_code == 200
    assert len(get_views.data) == 1

    delete_res = client.delete(f"/views/{view_res.data['id']}/")
    assert delete_res.status_code == 204


@pytest.mark.django_db
def test_projects_list_supports_area_q_limit_filters():
    org = Organization.objects.create(name="Org Filter")
    user = User.objects.create_user(email="filters@example.com", password="StrongPass123!", organization=org)
    other_org = Organization.objects.create(name="Other Org")
    User.objects.create_user(email="other@example.com", password="StrongPass123!", organization=other_org)

    Project.objects.create(organization=org, name="Alpha Work", area="work")
    Project.objects.create(organization=org, name="Beta Work", area="work")
    Project.objects.create(organization=org, name="Gamma Personal", area="personal")
    Project.objects.create(organization=other_org, name="Alpha External", area="work")

    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    filtered = client.get("/projects/?area=work&q=alpha&limit=1")
    assert filtered.status_code == 200
    assert len(filtered.data) == 1
    assert filtered.data[0]["name"] == "Alpha Work"

    work_only = client.get("/projects/?area=work")
    assert work_only.status_code == 200
    returned_names = {item["name"] for item in work_only.data}
    assert returned_names == {"Alpha Work", "Beta Work"}


@pytest.mark.django_db
def test_projects_list_can_filter_to_only_projects_with_tasks():
    org = Organization.objects.create(name="Org Has Tasks")
    user = User.objects.create_user(email="has-tasks@example.com", password="StrongPass123!", organization=org)

    project_with_task = Project.objects.create(organization=org, name="Has Task", area="work")
    Project.objects.create(organization=org, name="No Task", area="work")
    Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Linked task",
        area=Task.Area.WORK,
        project=project_with_task,
    )

    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    filtered = client.get("/projects/?has_tasks=true")
    assert filtered.status_code == 200
    assert [item["name"] for item in filtered.data] == ["Has Task"]
