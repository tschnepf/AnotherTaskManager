from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Organization, User
from tasks.models import Task
from tasks.tasks import archive_completed_tasks


@pytest.mark.django_db
def test_archive_completed_job_archives_old_done_tasks(monkeypatch):
    org = Organization.objects.create(name="Archive Org")
    user = User.objects.create_user(email="archive@example.com", password="StrongPass123!", organization=org)

    old_done = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Old done",
        area=Task.Area.WORK,
        status=Task.Status.DONE,
        completed_at=timezone.now() - timedelta(days=14),
    )
    recent_done = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Recent done",
        area=Task.Area.WORK,
        status=Task.Status.DONE,
        completed_at=timezone.now() - timedelta(days=2),
    )

    monkeypatch.setenv("TASK_ARCHIVE_AFTER_DAYS", "7")
    result = archive_completed_tasks()

    old_done.refresh_from_db()
    recent_done.refresh_from_db()

    assert result["status"] == "ok"
    assert result["archived_count"] == 1
    assert old_done.status == Task.Status.ARCHIVED
    assert recent_done.status == Task.Status.DONE
