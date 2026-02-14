import os

import pytest

from ai.factory import get_provider
from ai.privacy import cloud_allowed
from ai.semantic import dedupe_candidates, semantic_search_with_fallback
from ai.tasks import embed_task, suggest_metadata
from core.models import Organization, User
from tasks.models import Task


def test_privacy_cloud_gate_logic():
    assert cloud_allowed(True, None) is True
    assert cloud_allowed(False, None) is False
    assert cloud_allowed(False, True) is True
    assert cloud_allowed(True, False) is False


def test_provider_factory_modes():
    assert get_provider("off") is None
    assert get_provider("local").provider_name == "local"
    assert get_provider("cloud", org_allow_cloud_ai=False) is None
    assert get_provider("cloud", org_allow_cloud_ai=True).provider_name == "cloud"


@pytest.mark.django_db
def test_semantic_fallback_and_dedupe_candidates():
    os.environ["AI_MODE"] = "off"
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="u@example.com", password="StrongPass123!", organization=org)

    t1 = Task.objects.create(organization=org, created_by_user=user, title="Review submittal package", area=Task.Area.WORK)
    t2 = Task.objects.create(organization=org, created_by_user=user, title="Review submittal pkg", area=Task.Area.WORK)

    queryset, semantic_used, fallback_reason = semantic_search_with_fallback(Task.objects.filter(organization=org), "review", True)
    assert semantic_used is False
    assert fallback_reason == "ai_mode_off"
    assert queryset.count() >= 1

    candidates = dedupe_candidates(t1.title, [t2], threshold=0.6)
    assert len(candidates) == 1


def test_celery_ai_tasks_skip_when_ai_off(monkeypatch):
    monkeypatch.setenv("AI_MODE", "off")
    suggest = suggest_metadata("task-1")
    embed = embed_task("task-1")
    assert suggest["status"] == "skipped"
    assert embed["status"] == "skipped"
