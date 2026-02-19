from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone

from core.models import Organization, User
from tasks.models import Task


@pytest.mark.django_db
def test_tasks_crud_and_filters_and_semantic_contract():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="u@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "Task A", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    list_res = client.get("/tasks/?page=1&page_size=25&sort=created_at&order=desc")
    assert list_res.status_code == 200
    assert list_res.data["semantic_requested"] is False
    assert list_res.data["semantic_used"] is False

    semantic_bad = client.get("/tasks/?semantic=true")
    assert semantic_bad.status_code == 400

    detail_res = client.get(f"/tasks/{task_id}/")
    assert detail_res.status_code == 200

    patch_res = client.patch(f"/tasks/{task_id}/", {"status": "done"}, format="json")
    assert patch_res.status_code == 200

    invalid_transition = client.patch(f"/tasks/{task_id}/", {"status": "inbox"}, format="json")
    assert invalid_transition.status_code == 409


@pytest.mark.django_db
def test_tasks_cross_tenant_returns_404():
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

    res = client.get(f"/tasks/{task_b.id}/")
    assert res.status_code == 404


@pytest.mark.django_db
def test_tasks_list_hides_done_items_older_than_24_hours():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="u2@example.com", password="StrongPass123!", organization=org)

    old_done = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Old done",
        area=Task.Area.WORK,
        status=Task.Status.DONE,
        completed_at=timezone.now() - timedelta(days=2),
    )
    recent_done = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Recent done",
        area=Task.Area.WORK,
        status=Task.Status.DONE,
        completed_at=timezone.now() - timedelta(hours=2),
    )
    open_task = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Open",
        area=Task.Area.WORK,
        status=Task.Status.INBOX,
    )
    archived_task = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Archived",
        area=Task.Area.WORK,
        status=Task.Status.ARCHIVED,
    )

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    res = client.get("/tasks/?page=1&page_size=50&sort=created_at&order=desc")
    assert res.status_code == 200
    returned_ids = {item["id"] for item in res.data["results"]}
    assert str(old_done.id) not in returned_ids
    assert str(recent_done.id) in returned_ids
    assert str(open_task.id) in returned_ids
    assert str(archived_task.id) not in returned_ids

    history_res = client.get("/tasks/?page=1&page_size=50&sort=created_at&order=desc&include_history=true")
    assert history_res.status_code == 200
    history_ids = {item["id"] for item in history_res.data["results"]}
    assert str(old_done.id) in history_ids
    assert str(archived_task.id) in history_ids


@pytest.mark.django_db
def test_tasks_reorder_is_persisted_on_backend():
    org = Organization.objects.create(name="Org Reorder")
    user = User.objects.create_user(email="reorder@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    t1 = client.post("/tasks/", {"title": "Task 1", "area": "work"}, format="json")
    t2 = client.post("/tasks/", {"title": "Task 2", "area": "work"}, format="json")
    t3 = client.post("/tasks/", {"title": "Task 3", "area": "work"}, format="json")
    assert t1.status_code == 201
    assert t2.status_code == 201
    assert t3.status_code == 201

    t1_id = t1.data["id"]
    t2_id = t2.data["id"]
    t3_id = t3.data["id"]

    reorder = client.post(
        f"/tasks/{t3_id}/reorder/",
        {"target_task_id": t1_id, "placement": "before"},
        format="json",
    )
    assert reorder.status_code == 200

    listed = client.get("/tasks/?page=1&page_size=50&sort=position&order=asc")
    assert listed.status_code == 200
    ordered_ids = [item["id"] for item in listed.data["results"]]
    assert ordered_ids[:3] == [t3_id, t1_id, t2_id]


@pytest.mark.django_db
def test_tasks_changes_cursor_detects_create_update_and_delete():
    org = Organization.objects.create(name="Org Live")
    user = User.objects.create_user(email="live@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    baseline = client.get("/tasks/changes/")
    assert baseline.status_code == 200
    assert baseline.data["changed"] is False
    baseline_cursor = baseline.data["cursor"]

    create_res = client.post("/tasks/", {"title": "Live create", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    after_create = client.get("/tasks/changes/", {"cursor": baseline_cursor, "timeout_seconds": 0})
    assert after_create.status_code == 200
    assert after_create.data["changed"] is True
    create_cursor = after_create.data["cursor"]
    assert create_cursor != baseline_cursor

    patch_res = client.patch(f"/tasks/{task_id}/", {"priority": 3}, format="json")
    assert patch_res.status_code == 200

    after_patch = client.get("/tasks/changes/", {"cursor": create_cursor, "timeout_seconds": 0})
    assert after_patch.status_code == 200
    assert after_patch.data["changed"] is True
    patch_cursor = after_patch.data["cursor"]
    assert patch_cursor != create_cursor

    delete_res = client.delete(f"/tasks/{task_id}/")
    assert delete_res.status_code == 204

    after_delete = client.get("/tasks/changes/", {"cursor": patch_cursor, "timeout_seconds": 0})
    assert after_delete.status_code == 200
    assert after_delete.data["changed"] is True
    delete_cursor = after_delete.data["cursor"]
    assert delete_cursor != patch_cursor

    no_change = client.get("/tasks/changes/", {"cursor": delete_cursor, "timeout_seconds": 0})
    assert no_change.status_code == 200
    assert no_change.data["changed"] is False
    assert no_change.data["cursor"] == delete_cursor


@pytest.mark.django_db
def test_tasks_changes_cursor_detects_reorder_updates():
    org = Organization.objects.create(name="Org Live Reorder")
    user = User.objects.create_user(
        email="live-reorder@example.com", password="StrongPass123!", organization=org
    )

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    first = client.post("/tasks/", {"title": "First", "area": "work"}, format="json")
    second = client.post("/tasks/", {"title": "Second", "area": "work"}, format="json")
    assert first.status_code == 201
    assert second.status_code == 201

    cursor_before_reorder = client.get("/tasks/changes/").data["cursor"]

    reorder = client.post(
        f"/tasks/{second.data['id']}/reorder/",
        {"target_task_id": first.data["id"], "placement": "before"},
        format="json",
    )
    assert reorder.status_code == 200

    after_reorder = client.get(
        "/tasks/changes/",
        {"cursor": cursor_before_reorder, "timeout_seconds": 0},
    )
    assert after_reorder.status_code == 200
    assert after_reorder.data["changed"] is True


@pytest.mark.django_db
def test_task_priority_is_optional_and_updatable():
    org = Organization.objects.create(name="Priority Org")
    user = User.objects.create_user(email="priority@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "Priority Task", "area": "work", "priority": 5}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]
    assert create_res.data["priority"] == 5

    update_res = client.patch(f"/tasks/{task_id}/", {"priority": 1}, format="json")
    assert update_res.status_code == 200
    assert update_res.data["priority"] == 1

    clear_res = client.patch(f"/tasks/{task_id}/", {"priority": None}, format="json")
    assert clear_res.status_code == 200
    assert clear_res.data["priority"] is None


@pytest.mark.django_db
def test_tasks_can_be_grouped_by_priority_then_manual_order():
    org = Organization.objects.create(name="Priority Group Org")
    user = User.objects.create_user(email="priority-group@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    t1 = client.post("/tasks/", {"title": "Low", "area": "work", "priority": 1}, format="json")
    t2 = client.post("/tasks/", {"title": "High A", "area": "work", "priority": 5}, format="json")
    t3 = client.post("/tasks/", {"title": "Medium", "area": "work", "priority": 3}, format="json")
    t4 = client.post("/tasks/", {"title": "High B", "area": "work", "priority": 5}, format="json")
    assert t1.status_code == 201
    assert t2.status_code == 201
    assert t3.status_code == 201
    assert t4.status_code == 201

    reorder = client.post(
        f"/tasks/{t4.data['id']}/reorder/",
        {"target_task_id": t2.data["id"], "placement": "before"},
        format="json",
    )
    assert reorder.status_code == 200

    manual_list = client.get("/tasks/?page=1&page_size=50&sort=position&order=asc")
    assert manual_list.status_code == 200
    manual_ids = [item["id"] for item in manual_list.data["results"]]
    assert manual_ids[:4] == [t1.data["id"], t4.data["id"], t2.data["id"], t3.data["id"]]

    grouped_list = client.get("/tasks/?page=1&page_size=50&sort_mode=priority_manual")
    assert grouped_list.status_code == 200
    grouped_ids = [item["id"] for item in grouped_list.data["results"]]
    assert grouped_ids[:4] == [t4.data["id"], t2.data["id"], t3.data["id"], t1.data["id"]]


@pytest.mark.django_db
def test_task_details_notes_and_org_scoped_attachments_can_be_saved_and_read():
    org = Organization.objects.create(name="Details Org")
    user = User.objects.create_user(email="details@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "With details", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    uploaded = SimpleUploadedFile("details.txt", b"details attachment", content_type="text/plain")
    upload_res = client.post(
        f"/tasks/{task_id}/attachments/upload/",
        {"file": uploaded},
        format="multipart",
    )
    assert upload_res.status_code == 201
    assert len(upload_res.data["attachments"]) == 1

    payload = {
        "notes": "Email thread context and follow-up notes.",
        "attachments": upload_res.data["attachments"],
    }
    patch_res = client.patch(f"/tasks/{task_id}/", payload, format="json")
    assert patch_res.status_code == 200
    assert patch_res.data["notes"] == payload["notes"]
    assert patch_res.data["attachments"][0]["name"] == "details.txt"
    assert patch_res.data["attachments"][0]["path"].startswith(f"tasks/{org.id}/{task_id}/")

    detail_res = client.get(f"/tasks/{task_id}/")
    assert detail_res.status_code == 200
    assert detail_res.data["notes"] == payload["notes"]
    assert detail_res.data["attachments"][0]["path"] == patch_res.data["attachments"][0]["path"]


@pytest.mark.django_db
def test_task_details_reject_external_attachment_urls():
    org = Organization.objects.create(name="Details Org")
    user = User.objects.create_user(email="details@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "With details", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    patch_res = client.patch(
        f"/tasks/{task_id}/",
        {
            "attachments": [{"name": "malicious", "url": "https://evil.example/payload.html"}],
        },
        format="json",
    )
    assert patch_res.status_code == 400


@pytest.mark.django_db
def test_task_attachment_file_upload_endpoint_appends_attachment():
    org = Organization.objects.create(name="Upload Org")
    user = User.objects.create_user(email="upload@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "Upload task", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    uploaded = SimpleUploadedFile("note.txt", b"hello task attachment", content_type="text/plain")
    upload_res = client.post(
        f"/tasks/{task_id}/attachments/upload/",
        {"file": uploaded},
        format="multipart",
    )
    assert upload_res.status_code == 201
    assert len(upload_res.data["attachments"]) == 1
    assert upload_res.data["attachments"][0]["name"] == "note.txt"
    assert upload_res.data["attachments"][0]["path"].startswith(f"tasks/{org.id}/{task_id}/")
    assert upload_res.data["attachments"][0]["url"].startswith("/tasks/attachments/file?token=")

    detail_res = client.get(f"/tasks/{task_id}/")
    assert detail_res.status_code == 200
    assert len(detail_res.data["attachments"]) == 1

    attachment_url = upload_res.data["attachments"][0]["url"]
    download_res = client.get(attachment_url)
    assert download_res.status_code == 200
    assert b"hello task attachment" in b"".join(download_res.streaming_content)


@pytest.mark.django_db
def test_task_attachment_file_requires_authenticated_user():
    org = Organization.objects.create(name="Upload Org")
    user = User.objects.create_user(email="upload-auth@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "Upload task", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    uploaded = SimpleUploadedFile("note.txt", b"hello task attachment", content_type="text/plain")
    upload_res = client.post(
        f"/tasks/{task_id}/attachments/upload/",
        {"file": uploaded},
        format="multipart",
    )
    assert upload_res.status_code == 201
    attachment_url = upload_res.data["attachments"][0]["url"]

    anonymous_client = APIClient()
    download_res = anonymous_client.get(attachment_url)
    assert download_res.status_code == 401


@pytest.mark.django_db
def test_task_attachment_file_denies_cross_org_access():
    org_a = Organization.objects.create(name="Upload Org A")
    user_a = User.objects.create_user(email="upload-org-a@example.com", password="StrongPass123!", organization=org_a)
    org_b = Organization.objects.create(name="Upload Org B")
    user_b = User.objects.create_user(email="upload-org-b@example.com", password="StrongPass123!", organization=org_b)

    token_a = RefreshToken.for_user(user_a)
    token_b = RefreshToken.for_user(user_b)

    client_a = APIClient()
    client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {token_a.access_token}")
    client_b = APIClient()
    client_b.credentials(HTTP_AUTHORIZATION=f"Bearer {token_b.access_token}")

    create_res = client_a.post("/tasks/", {"title": "Upload task", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    uploaded = SimpleUploadedFile("note.txt", b"hello task attachment", content_type="text/plain")
    upload_res = client_a.post(
        f"/tasks/{task_id}/attachments/upload/",
        {"file": uploaded},
        format="multipart",
    )
    assert upload_res.status_code == 201
    attachment_url = upload_res.data["attachments"][0]["url"]

    cross_org_download = client_b.get(attachment_url)
    assert cross_org_download.status_code == 404


@pytest.mark.django_db
def test_task_attachment_upload_rejects_active_content_extensions():
    org = Organization.objects.create(name="Upload Org")
    user = User.objects.create_user(email="upload@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create_res = client.post("/tasks/", {"title": "Upload task", "area": "work"}, format="json")
    assert create_res.status_code == 201
    task_id = create_res.data["id"]

    uploaded = SimpleUploadedFile("payload.html", b"<script>alert(1)</script>", content_type="text/html")
    upload_res = client.post(
        f"/tasks/{task_id}/attachments/upload/",
        {"file": uploaded},
        format="multipart",
    )
    assert upload_res.status_code == 400
