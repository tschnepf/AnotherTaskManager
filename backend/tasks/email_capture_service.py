from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.db.models import Max
from django.utils.text import get_valid_filename

from core.models import Organization, User
from tasks.email_ingest import (
    clean_email_body_text,
    extract_force_directives,
    extract_email_attachments,
    extract_sender,
    extract_subject,
    extract_text_body,
    loose_key,
    parse_eml,
    parse_task_metadata,
)
from tasks.models import Project, Task


class EmailIngestError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def ingest_raw_email_for_org(
    organization: Organization,
    raw_eml: bytes,
    *,
    sender_override: str = "",
):
    if not raw_eml:
        raise EmailIngestError(400, "validation_error", "an .eml payload is required")

    try:
        parsed = parse_eml(raw_eml)
    except Exception as exc:
        raise EmailIngestError(400, "validation_error", "invalid .eml payload") from exc

    sender = str(sender_override or extract_sender(parsed) or "").strip().lower()
    whitelist = {
        str(email).strip().lower() for email in (organization.inbound_email_whitelist or []) if str(email).strip()
    }
    if whitelist:
        if not sender:
            raise EmailIngestError(403, "forbidden", "sender email is required when whitelist is configured")
        if sender not in whitelist:
            raise EmailIngestError(403, "forbidden", "sender is not allowed by inbound email whitelist")

    creator = (
        User.objects.filter(organization=organization, role=User.Role.OWNER).order_by("created_at").first()
        or User.objects.filter(organization=organization, role=User.Role.ADMIN).order_by("created_at").first()
        or User.objects.filter(organization=organization).order_by("created_at").first()
    )
    if creator is None:
        raise EmailIngestError(400, "validation_error", "organization must have at least one user to create tasks")

    subject = extract_subject(parsed)
    body_text = extract_text_body(parsed)
    cleaned_body_text = clean_email_body_text(body_text)
    force_directives, metadata_body_text = extract_force_directives(cleaned_body_text, subject)
    title, project_hint, area, priority = parse_task_metadata(cleaned_body_text, subject)
    body_title, _body_project_hint, _body_area, _body_priority = parse_task_metadata(metadata_body_text, subject)

    forced_title = str(force_directives.get("task") or "").strip()
    forced_project_name = str(force_directives.get("project") or "").strip()
    if forced_project_name and not forced_title:
        title = body_title
    if forced_title:
        title = forced_title

    project_match = None
    if forced_project_name:
        normalized_hint = loose_key(forced_project_name)
        candidate_name = forced_project_name
        project_match = next(
            (
                project
                for project in Project.objects.filter(organization=organization)
                if loose_key(project.name) == normalized_hint
            ),
            None,
        )
        if project_match is None:
            try:
                project_match = Project.objects.create(
                    organization=organization,
                    name=candidate_name,
                    area=area,
                )
            except IntegrityError:
                # Handle rare races where the same project name is created concurrently.
                project_match = next(
                    (
                        project
                        for project in Project.objects.filter(organization=organization)
                        if loose_key(project.name) == normalized_hint
                    ),
                    None,
                )
    elif project_hint:
        normalized_hint = loose_key(project_hint)
        project_match = next(
            (
                project
                for project in Project.objects.filter(organization=organization)
                if loose_key(project.name) == normalized_hint
            ),
            None,
        )

    next_position = (
        Task.objects.filter(organization=organization).aggregate(max_position=Max("position"))["max_position"] or 0
    ) + 1

    task = Task.objects.create(
        organization=organization,
        created_by_user=creator,
        title=title,
        notes=metadata_body_text,
        area=area,
        priority=priority,
        project=project_match,
        source_type=Task.SourceType.EMAIL,
        source_snippet=metadata_body_text[:1000],
        position=next_position,
    )

    extracted_attachments = extract_email_attachments(parsed)
    saved_attachments = []
    for index, attachment in enumerate(extracted_attachments, start=1):
        original_name = str(attachment.get("name") or "").strip() or f"attachment-{index}"
        safe_name = get_valid_filename(original_name) or f"attachment-{index}"
        relative_path = f"tasks/{organization.id}/{task.id}/{uuid4().hex}/{safe_name}"
        saved_path = default_storage.save(relative_path, ContentFile(attachment["content"]))
        saved_attachments.append(
            {
                "name": original_name,
                "url": default_storage.url(saved_path),
            }
        )

    task.attachments = saved_attachments
    task.save(update_fields=["attachments", "updated_at"])
    return task
