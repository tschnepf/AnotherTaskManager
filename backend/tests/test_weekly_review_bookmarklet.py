from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from ai.models import ReviewSummary
from ai.tasks import weekly_review
from core.models import Organization, User
from tasks.models import Task


@pytest.mark.django_db
def test_weekly_review_job_persists_summary():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="u@example.com", password="StrongPass123!", organization=org)

    old_date = timezone.now() - timedelta(days=40)
    task = Task.objects.create(
        organization=org,
        created_by_user=user,
        title="Old next",
        area=Task.Area.WORK,
        status=Task.Status.NEXT,
    )
    Task.objects.filter(id=task.id).update(created_at=old_date)

    result = weekly_review(str(org.id))
    assert result["status"] == "ok"
    assert ReviewSummary.objects.filter(organization=org).exists()


@pytest.mark.django_db
def test_bookmarklet_capture_endpoint_creates_task():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="u@example.com", password="StrongPass123!", organization=org)

    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    response = client.post(
        "/capture/bookmarklet",
        {
            "title": "Bookmark task",
            "url": "https://example.com/page",
            "snippet": "useful excerpt",
            "area": "work",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Bookmark task"
    assert response.data["source_link"] == "https://example.com/page"
