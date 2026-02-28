import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from core.models import Organization, User


class Project(models.Model):
    class Area(models.TextChoices):
        WORK = "work", "Work"
        PERSONAL = "personal", "Personal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=255)
    area = models.CharField(max_length=20, choices=Area.choices)
    is_active = models.BooleanField(default=True)
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "organization",
                name="project_org_lower_name_uniq",
            )
        ]


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "organization",
                name="tag_org_lower_name_uniq",
            )
        ]


class Task(models.Model):
    class Intent(models.TextChoices):
        TASK = "task", "Task"
        NOTE = "note", "Note"
        IDEA = "idea", "Idea"
        REFERENCE = "reference", "Reference"

    class Area(models.TextChoices):
        WORK = "work", "Work"
        PERSONAL = "personal", "Personal"

    class Status(models.TextChoices):
        INBOX = "inbox", "Inbox"
        NEXT = "next", "Next"
        WAITING = "waiting", "Waiting"
        SOMEDAY = "someday", "Someday"
        DONE = "done", "Done"
        ARCHIVED = "archived", "Archived"

    class Recurrence(models.TextChoices):
        NONE = "none", "None"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    class SourceType(models.TextChoices):
        EMAIL = "email", "Email"
        CONVERSATION = "conversation", "Conversation"
        SELF = "self", "Self"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tasks")
    created_by_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_tasks")
    assigned_to_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    attachments = models.JSONField(default=list, blank=True)
    intent = models.CharField(max_length=20, choices=Intent.choices, default=Intent.TASK)
    area = models.CharField(max_length=20, choices=Area.choices)
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INBOX)
    priority = models.IntegerField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    recurrence = models.CharField(max_length=20, choices=Recurrence.choices, default=Recurrence.NONE)
    completed_at = models.DateTimeField(null=True, blank=True)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.SELF)
    source_external_id = models.CharField(max_length=512, blank=True, db_index=True)
    source_link = models.TextField(blank=True)
    source_snippet = models.TextField(blank=True)
    allow_cloud_processing = models.BooleanField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tags = models.ManyToManyField(Tag, through="TaskTag", related_name="tasks")

    class Meta:
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "project"]),
            models.Index(fields=["organization", "position"], name="tasks_task_organiz_81029d_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority__isnull=True) | Q(priority__gte=1, priority__lte=5),
                name="task_priority_between_1_5",
            ),
            models.CheckConstraint(
                condition=~Q(status="done") | Q(completed_at__isnull=False),
                name="task_done_requires_completed_at",
            ),
            models.CheckConstraint(
                condition=Q(status="done") | Q(completed_at__isnull=True),
                name="task_not_done_null_completed_at",
            ),
            models.UniqueConstraint(
                fields=["organization", "source_type", "source_external_id"],
                condition=Q(source_type="email") & ~Q(source_external_id=""),
                name="task_email_source_external_id_uniq",
            ),
        ]


class TaskTag(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "tag"], name="task_tag_pk_like")
        ]


class TaskChangeEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"
        ARCHIVED = "archived", "Archived"

    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="task_change_events")
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    task_id = models.UUIDField(null=True, blank=True)
    payload_summary = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "id"]),
        ]
