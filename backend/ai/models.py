import uuid

from django.db import models
from django.db.models import Q
from pgvector.django import VectorField

from core.models import Organization
from tasks.models import Task


class AIJob(models.Model):
    class JobType(models.TextChoices):
        SUGGEST_METADATA = "suggest_metadata", "Suggest Metadata"
        EMBED_TASK = "embed_task", "Embed Task"
        WEEKLY_REVIEW = "weekly_review", "Weekly Review"
        DEDUPE_CHECK = "dedupe_check", "Dedupe Check"

    class JobStatus(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    class Provider(models.TextChoices):
        LOCAL = "local", "Local"
        CLOUD = "cloud", "Cloud"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="ai_jobs")
    type = models.CharField(max_length=32, choices=JobType.choices)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.CASCADE, related_name="ai_jobs")
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.QUEUED)
    provider_used = models.CharField(max_length=16, choices=Provider.choices)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TaskAISuggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="ai_suggestions")
    suggestion_json = models.JSONField(default=dict)
    confidence_score = models.FloatField()
    provider_used = models.CharField(max_length=16)
    model_name = models.CharField(max_length=255)
    model_version = models.CharField(max_length=255, blank=True)
    input_hash = models.CharField(max_length=255)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TaskEmbedding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="embeddings")
    embedding = VectorField(dimensions=1536)
    provider_used = models.CharField(max_length=16)
    model_name = models.CharField(max_length=255)
    model_version = models.CharField(max_length=255, blank=True)
    embedding_dimensions = models.IntegerField()
    input_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "model_name", "input_hash"],
                name="task_embedding_task_model_input_hash_uniq",
            ),
            models.UniqueConstraint(
                fields=["task", "model_name"],
                condition=Q(is_active=True),
                name="task_embedding_one_active_per_task_model",
            ),
        ]


class ReviewSummary(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="review_summaries")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
