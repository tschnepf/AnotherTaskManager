import re
from html import escape
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
    extract_html_body,
    extract_sender,
    extract_subject,
    extract_text_body,
    loose_key,
    parse_eml,
    parse_task_metadata,
)
from tasks.models import Project, Task

SCRIPT_TAG_RE = re.compile(r"(?is)<script\b[^>]*>.*?</script>")
EVENT_HANDLER_ATTR_RE = re.compile(r"""(?is)\s+on[a-z0-9_-]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""")
JAVASCRIPT_URL_ATTR_RE = re.compile(r"""(?is)\s+(src|href)\s*=\s*(['"])\s*javascript:[^'"]*\2""")
CID_REFERENCE_RE = re.compile(
    r"""(?is)\b(?P<attr>src|href)\s*=\s*(?P<quote>['"]?)cid:(?P<cid>[^'">\s]+)(?P=quote)"""
)


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
    html_body = extract_html_body(parsed)
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
    original_email_name = _original_email_attachment_name(subject)
    original_email_attachment = _save_task_attachment(
        organization_id=str(organization.id),
        task_id=str(task.id),
        attachment_name=original_email_name,
        content=raw_eml,
    )

    extracted_saved_attachments = []
    cid_to_url = {}
    for index, attachment in enumerate(extracted_attachments, start=1):
        original_name = str(attachment.get("name") or "").strip() or f"attachment-{index}"
        saved_attachment = _save_task_attachment(
            organization_id=str(organization.id),
            task_id=str(task.id),
            attachment_name=original_name,
            content=bytes(attachment["content"]),
        )
        extracted_saved_attachments.append(saved_attachment)

        content_id = str(attachment.get("content_id") or "").strip().lower()
        if content_id and content_id not in cid_to_url:
            cid_to_url[content_id] = saved_attachment["url"]

    rendered_preview = _render_email_preview_html(
        subject=subject,
        sender=sender,
        html_body=html_body,
        plain_body=cleaned_body_text,
        cid_to_url=cid_to_url,
        listed_attachments=[original_email_attachment, *extracted_saved_attachments],
    )
    preview_attachment = _save_task_attachment(
        organization_id=str(organization.id),
        task_id=str(task.id),
        attachment_name="email-preview.html",
        content=rendered_preview.encode("utf-8"),
    )

    task.attachments = [preview_attachment, original_email_attachment, *extracted_saved_attachments]
    task.save(update_fields=["attachments", "updated_at"])
    return task


def _save_task_attachment(*, organization_id: str, task_id: str, attachment_name: str, content: bytes) -> dict:
    safe_name = get_valid_filename(str(attachment_name or "").strip()) or "attachment"
    relative_path = f"tasks/{organization_id}/{task_id}/{uuid4().hex}/{safe_name}"
    saved_path = default_storage.save(relative_path, ContentFile(content))
    return {
        "name": str(attachment_name or "").strip() or safe_name,
        "url": default_storage.url(saved_path),
    }


def _original_email_attachment_name(subject: str) -> str:
    normalized_subject = " ".join(str(subject or "").split()).strip()
    if not normalized_subject:
        return "original-email.eml"
    truncated = normalized_subject[:96].strip().rstrip(".")
    if not truncated:
        return "original-email.eml"
    return f"{truncated}.eml"


def _render_email_preview_html(
    *,
    subject: str,
    sender: str,
    html_body: str,
    plain_body: str,
    cid_to_url: dict[str, str],
    listed_attachments: list[dict],
) -> str:
    sanitized_html = _sanitize_email_html(html_body)
    if sanitized_html:
        body_markup = _replace_cid_references(sanitized_html, cid_to_url)
    else:
        fallback_text = escape(str(plain_body or "").strip() or "(No email body detected.)")
        body_markup = f"<pre>{fallback_text}</pre>"

    attachment_items = "".join(
        (
            f'<li><a href="{escape(str(item.get("url") or ""), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{escape(str(item.get("name") or "Attachment"))}</a></li>'
        )
        for item in listed_attachments
        if str(item.get("url") or "").strip()
    )
    attachments_markup = (
        f"<section><h2>Attachments</h2><ul>{attachment_items}</ul></section>"
        if attachment_items
        else ""
    )

    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        f"<title>{escape(subject or 'Email preview')}</title>"
        "<style>"
        ":root{color-scheme:dark;}"
        "body{margin:0;padding:16px;font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "background:#0b1016;color:#dce6f2;}"
        ".email-wrap{max-width:960px;margin:0 auto;background:#111a24;border:1px solid #273544;border-radius:10px;"
        "overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.35);}"
        ".email-meta{padding:14px 16px;border-bottom:1px solid #2b3a4a;background:#0f1720;}"
        ".email-meta h1{margin:0;font-size:18px;line-height:1.3;color:#f1f7ff;}"
        ".email-meta p{margin:6px 0 0;color:#98aabd;font-size:13px;}"
        ".email-body{padding:16px;overflow-wrap:anywhere;color:#dce6f2;}"
        ".email-body img{max-width:100%;height:auto;}"
        ".email-body table{max-width:100%;border-collapse:collapse;}"
        ".email-body a{color:#8db8ff;text-decoration:underline;word-break:break-word;}"
        ".email-body pre{white-space:pre-wrap;background:#0c141d;border:1px solid #2e3d4f;padding:12px;"
        "border-radius:8px;}"
        "section{padding:0 16px 16px;}"
        "section h2{margin:0 0 8px;font-size:14px;color:#9fb2c7;}"
        "section ul{margin:0;padding-left:18px;}"
        "section li{margin:4px 0;}"
        "section a{color:#8db8ff;}"
        "</style></head><body>"
        "<div class='email-wrap'>"
        "<header class='email-meta'>"
        f"<h1>{escape(subject or '(No Subject)')}</h1>"
        f"<p>From: {escape(sender or 'Unknown sender')}</p>"
        "</header>"
        f"<main class='email-body'>{body_markup}</main>"
        f"{attachments_markup}"
        "</div></body></html>"
    )


def _sanitize_email_html(raw_html: str) -> str:
    value = str(raw_html or "").strip()
    if not value:
        return ""
    value = SCRIPT_TAG_RE.sub("", value)
    value = EVENT_HANDLER_ATTR_RE.sub("", value)
    value = JAVASCRIPT_URL_ATTR_RE.sub(" ", value)
    return value


def _replace_cid_references(html: str, cid_to_url: dict[str, str]) -> str:
    if not cid_to_url:
        return html

    def _replace(match: re.Match) -> str:
        attribute = match.group("attr")
        quote = match.group("quote") or '"'
        cid_value = str(match.group("cid") or "").strip().strip("<>").lower()
        resolved_url = cid_to_url.get(cid_value)
        if not resolved_url:
            return match.group(0)
        return f'{attribute}={quote}{escape(resolved_url, quote=True)}{quote}'

    return CID_REFERENCE_RE.sub(_replace, html)
