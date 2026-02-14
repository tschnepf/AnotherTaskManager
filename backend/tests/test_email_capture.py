from email.message import EmailMessage

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Project, Task


def _build_eml(
    subject: str,
    body: str,
    to_address: str,
    from_address: str = "sender@example.com",
    html_body: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    inline_images: list[tuple[str, bytes, str, str]] | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
        if inline_images:
            html_part = message.get_payload()[-1]
            for filename, payload, content_type, content_id in inline_images:
                maintype, subtype = content_type.split("/", 1)
                html_part.add_related(
                    payload,
                    maintype=maintype,
                    subtype=subtype,
                    filename=filename,
                    cid=f"<{content_id}>",
                    disposition="inline",
                )
    for filename, payload, content_type in attachments or []:
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


@pytest.fixture(autouse=True)
def _temporary_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_URL = "/media/"


@pytest.mark.django_db
def test_email_capture_settings_can_be_configured_by_owner():
    org = Organization.objects.create(name="Email Org")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    token = RefreshToken.for_user(owner)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    response = client.patch(
        "/settings/email-capture",
        {
            "inbound_email_address": "Tasks@Example.com",
            "inbound_email_whitelist": [" Approved@Example.com ", "approved@example.com", "other@example.com"],
            "rotate_token": True,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["inbound_email_address"] == "tasks@example.com"
    assert response.data["inbound_email_token"]
    assert response.data["inbound_email_whitelist"] == ["approved@example.com", "other@example.com"]


@pytest.mark.django_db
def test_email_capture_settings_reject_member():
    org = Organization.objects.create(name="Email Org")
    member = User.objects.create_user(
        email="member@example.com",
        password="StrongPass123!",
        role=User.Role.MEMBER,
        organization=org,
    )
    client = APIClient()
    token = RefreshToken.for_user(member)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    response = client.patch("/settings/email-capture", {"inbound_email_address": "tasks@example.com"}, format="json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_inbound_email_capture_creates_task_with_loose_project_match_and_clean_body():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    project = Project.objects.create(organization=org, name="ADC LBB", area=Project.Area.WORK)

    client = APIClient()
    raw_eml = _build_eml(
        subject="Forwarded context",
        body="Verify the lighting layout\nADCLBB\nwork\nhigh\n\nForwarded thread below.",
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Verify the lighting layout"
    assert response.data["area"] == Task.Area.WORK
    assert response.data["priority"] == 5
    assert str(response.data["project"]) == str(project.id)
    assert response.data["source_type"] == Task.SourceType.EMAIL
    assert str(response.data["created_by_user"]) == str(owner.id)
    assert response.data["notes"] == "Verify the lighting layout\nADCLBB\nwork\nhigh\n\nForwarded thread below."
    assert "Forwarded thread below." in response.data["source_snippet"]
    assert len(response.data["attachments"]) == 2
    attachment_names = {attachment["name"] for attachment in response.data["attachments"]}
    assert "email-preview.html" in attachment_names
    assert any(name.endswith(".eml") for name in attachment_names)


@pytest.mark.django_db
def test_inbound_email_capture_defaults_to_subject_work_low():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    project = Project.objects.create(organization=org, name="ADC LBB", area=Project.Area.WORK)

    client = APIClient()
    raw_eml = _build_eml(
        subject="Subject fallback title",
        body="<task title>\nadc lbb\n<work or personal>\n<priority>\n",
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Subject fallback title"
    assert response.data["area"] == Task.Area.WORK
    assert response.data["priority"] == 1
    assert str(response.data["project"]) == str(project.id)


@pytest.mark.django_db
def test_inbound_email_capture_strips_embedded_headers_and_saves_real_attachments():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )

    client = APIClient()
    raw_eml = _build_eml(
        subject="Client update",
        body=(
            "Client update\nProject A\nwork\nhigh\n\n"
            "-----Original Message-----\n"
            "From: old.sender@example.com\n"
            "Sent: Monday, January 1, 2024 8:00 AM\n"
            "To: team@example.com\n"
            "Subject: Old thread\n\n"
            "Quoted body should not be included\n"
        ),
        to_address="tasks@example.com",
        attachments=[("scope.txt", b"new attachment payload", "text/plain")],
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    assert response.data["notes"] == "Client update\nProject A\nwork\nhigh"
    assert "Original Message" not in response.data["notes"]
    assert len(response.data["attachments"]) == 3
    attachment_names = {attachment["name"] for attachment in response.data["attachments"]}
    assert "email-preview.html" in attachment_names
    assert "scope.txt" in attachment_names
    assert any(name.endswith(".eml") for name in attachment_names)

    for attachment in response.data["attachments"]:
        attachment_path = attachment["url"].replace("/media/", "", 1)
        assert default_storage.exists(attachment_path)


@pytest.mark.django_db
def test_inbound_email_capture_uses_html_body_when_plain_part_is_header_only():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    raw_eml = _build_eml(
        subject="Fwd: Site visit update",
        body=(
            "---------- Forwarded message ----------\n"
            "From: Sender Example <sender@example.com>\n"
            "Date: Tue, Jan 7, 2025 at 9:00 AM\n"
            "Subject: Site visit update\n"
            "To: Team <team@example.com>\n"
        ),
        html_body=(
            "<div>Site visit update</div>"
            "<div>Project Falcon</div>"
            "<div>work</div>"
            "<div>high</div>"
            "<p>Crane access approved.</p>"
        ),
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Site visit update"
    non_empty_lines = [line.strip() for line in response.data["notes"].splitlines() if line.strip()]
    assert non_empty_lines[:4] == ["Site visit update", "Project Falcon", "work", "high"]
    assert "From: Sender Example" not in response.data["notes"]
    assert "Crane access approved." in response.data["notes"]


@pytest.mark.django_db
def test_inbound_email_capture_saves_rendered_email_preview_with_inline_images_and_links():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    raw_eml = _build_eml(
        subject="Inline photo update",
        body="Please see inline image",
        html_body=(
            "<p>Please review this update.</p>"
            '<p><a href="https://example.com/spec-review">Spec review link</a></p>'
            '<img src="cid:photo-1" alt="Inline photo" />'
        ),
        to_address="tasks@example.com",
        inline_images=[("photo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png", "photo-1")],
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    attachments = response.data["attachments"]
    attachment_names = {attachment["name"] for attachment in attachments}
    assert "email-preview.html" in attachment_names
    assert "photo.png" in attachment_names
    assert any(name.endswith(".eml") for name in attachment_names)

    preview_attachment = next(attachment for attachment in attachments if attachment["name"] == "email-preview.html")
    inline_image_attachment = next(attachment for attachment in attachments if attachment["name"] == "photo.png")
    preview_path = preview_attachment["url"].replace("/media/", "", 1)
    with default_storage.open(preview_path, mode="rb") as preview_file:
        preview_html = preview_file.read().decode("utf-8")

    assert "https://example.com/spec-review" in preview_html
    assert inline_image_attachment["url"] in preview_html


@pytest.mark.django_db
def test_inbound_email_capture_supports_force_project_and_creates_when_missing():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )

    client = APIClient()
    raw_eml = _build_eml(
        subject="Lighting coordination",
        body=(
            "Project: ADC LBB\n"
            "Please review latest reflected ceiling plans.\n"
        ),
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    project = Project.objects.get(organization=org, name="ADC LBB")
    assert str(response.data["project"]) == str(project.id)
    assert response.data["title"] == "Please review latest reflected ceiling plans."
    assert response.data["notes"] == "Please review latest reflected ceiling plans."


@pytest.mark.django_db
def test_inbound_email_capture_supports_force_task_subject_and_force_project():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    Project.objects.create(organization=org, name="ADC LBB", area=Project.Area.WORK)

    client = APIClient()
    raw_eml = _build_eml(
        subject="Subject to force",
        body=(
            "Task: Subject\n"
            "Project: ADC LBB\n"
            "Work\n"
            "High\n"
            "Body context line\n"
        ),
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Subject to force"
    assert response.data["notes"] == "Work\nHigh\nBody context line"
    assert response.data["area"] == Task.Area.WORK
    assert response.data["priority"] == 5
    assert response.data["project"] is not None


@pytest.mark.django_db
def test_inbound_email_capture_supports_priority_before_area_with_force_directives():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )

    client = APIClient()
    raw_eml = _build_eml(
        subject="Fw: CMH - G&W Programming Spec Review",
        body=(
            "Task: Subject\n"
            "Project: ADC CMH02\n"
            "High\n"
            "Work\n"
        ),
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201
    assert response.data["title"] == "Fw: CMH - G&W Programming Spec Review"
    assert response.data["area"] == Task.Area.WORK
    assert response.data["priority"] == 5
    assert response.data["project"] is not None


@pytest.mark.django_db
def test_inbound_email_capture_rejects_invalid_token():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    raw_eml = _build_eml(
        subject="Task",
        body="Title only",
        to_address="tasks@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="wrong-token",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_inbound_email_capture_rejects_sender_not_in_whitelist():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
        inbound_email_whitelist=["approved@example.com"],
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    raw_eml = _build_eml(
        subject="Task",
        body="Title only",
        to_address="tasks@example.com",
        from_address="blocked@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_inbound_email_capture_allows_sender_in_whitelist():
    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        inbound_email_token="token-123",
        inbound_email_whitelist=["approved@example.com"],
    )
    User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    raw_eml = _build_eml(
        subject="Task",
        body="Title only",
        to_address="tasks@example.com",
        from_address="approved@example.com",
    )
    uploaded = SimpleUploadedFile("forwarded.eml", raw_eml, content_type="message/rfc822")

    response = client.post(
        "/capture/email/inbound",
        {"recipient": "tasks@example.com", "email": uploaded},
        format="multipart",
        HTTP_X_TASKHUB_INGEST_TOKEN="token-123",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_email_capture_settings_can_store_imap_fields_without_returning_password():
    org = Organization.objects.create(name="Email Org")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    token = RefreshToken.for_user(owner)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    response = client.patch(
        "/settings/email-capture",
        {
            "imap_username": "imap-user@example.com",
            "imap_password": "secret-password",
            "imap_host": "",
            "imap_provider": "gmail",
            "imap_port": 993,
            "imap_use_ssl": True,
            "imap_folder": "INBOX",
            "imap_search_criteria": "UNSEEN",
            "imap_mark_seen_on_success": True,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["imap_username"] == "imap-user@example.com"
    assert response.data["imap_password_configured"] is True
    assert "imap_password" not in response.data

    org.refresh_from_db()
    assert org.imap_username == "imap-user@example.com"
    assert org.imap_password == "secret-password"


@pytest.mark.django_db
def test_email_capture_settings_can_clear_imap_password():
    org = Organization.objects.create(name="Email Org", imap_username="imap-user@example.com", imap_password="secret")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = APIClient()
    token = RefreshToken.for_user(owner)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    response = client.patch(
        "/settings/email-capture",
        {"imap_clear_password": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["imap_password_configured"] is False
    org.refresh_from_db()
    assert org.imap_password == ""
