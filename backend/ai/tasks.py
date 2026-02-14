from datetime import timedelta

from celery import shared_task

from ai.factory import get_provider
from ai.models import ReviewSummary
from django.utils import timezone
from tasks.models import Task


@shared_task(name="ai.suggest_metadata")
def suggest_metadata(task_id: str):
    provider = get_provider()
    if provider is None:
        return {"status": "skipped", "reason": "ai_off"}
    result = provider.generate_completion(prompt=f"suggest metadata for {task_id}", model="default")
    return {"status": "ok", "provider_used": result.provider_used}


@shared_task(name="ai.embed_task")
def embed_task(task_id: str):
    provider = get_provider()
    if provider is None:
        return {"status": "skipped", "reason": "ai_off"}
    result = provider.generate_embedding(text=f"task:{task_id}", model="default-embed")
    return {"status": "ok", "provider_used": result.provider_used, "dims": len(result.vector)}


@shared_task(name="ai.dedupe_check")
def dedupe_check(task_id: str):
    return {"status": "ok", "task_id": task_id}


@shared_task(name="ai.weekly_review")
def weekly_review(organization_id: str):
    now = timezone.now()
    inbox_old = Task.objects.filter(
        organization_id=organization_id,
        status=Task.Status.INBOX,
        created_at__lt=now - timedelta(days=7),
    ).count()
    waiting_old = Task.objects.filter(
        organization_id=organization_id,
        status=Task.Status.WAITING,
        created_at__lt=now - timedelta(days=14),
    ).count()
    next_old = Task.objects.filter(
        organization_id=organization_id,
        status=Task.Status.NEXT,
        created_at__lt=now - timedelta(days=30),
    ).count()

    content = (
        f"Weekly review summary\\n"
        f"- inbox older than 7 days: {inbox_old}\\n"
        f"- waiting older than 14 days: {waiting_old}\\n"
        f"- next older than 30 days: {next_old}"
    )
    ReviewSummary.objects.create(organization_id=organization_id, content=content)
    return {"status": "ok", "organization_id": organization_id}
