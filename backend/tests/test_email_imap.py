from email.message import EmailMessage

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from tasks.models import Task


class _FakeMailbox:
    def __init__(self, raw_message: bytes):
        self._raw_message = raw_message
        self.store_calls = []

    def login(self, username, password):
        return "OK", []

    def select(self, folder, readonly=False):
        return "OK", [b"1"]

    def search(self, charset, criteria):
        return "OK", [b"1"]

    def fetch(self, message_id, _parts):
        return "OK", [(b"1 (RFC822)", self._raw_message)]

    def store(self, message_id, operation, flags):
        self.store_calls.append((message_id, operation, flags))
        return "OK", []

    def logout(self):
        return "BYE", [b"logged out"]


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


def _build_eml(subject: str, body: str, to_address: str, from_address: str = "sender@example.com") -> bytes:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


@pytest.fixture(autouse=True)
def _temporary_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_URL = "/media/"


@pytest.mark.django_db
def test_imap_sync_endpoint_creates_task(monkeypatch):
    monkeypatch.setenv("INBOUND_EMAIL_MODE", "imap")

    org = Organization.objects.create(
        name="Email Org",
        inbound_email_address="tasks@example.com",
        imap_username="tasks@example.com",
        imap_password="app-password",
        imap_provider="auto",
        imap_port=993,
        imap_use_ssl=True,
        imap_folder="INBOX",
        imap_search_criteria="UNSEEN",
        imap_mark_seen_on_success=True,
    )
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    raw_eml = _build_eml(
        subject="Subject fallback title",
        body="<task title>\nProject Z\n<work or personal>\n<priority>\n",
        to_address="tasks@example.com",
    )
    fake_mailbox = _FakeMailbox(raw_eml)
    seen_host = {"value": ""}

    def fake_ssl(host, port):
        seen_host["value"] = host
        return fake_mailbox

    monkeypatch.setattr("tasks.email_imap_service.imaplib.IMAP4_SSL", fake_ssl)

    response = client.post("/settings/email-capture/imap/sync", {"max_messages": 10}, format="json")

    assert response.status_code == 200
    assert response.data["processed"] == 1
    assert response.data["created"] == 1
    assert response.data["failed"] == []
    assert Task.objects.filter(organization=org, title="Subject fallback title").exists()
    assert fake_mailbox.store_calls
    assert seen_host["value"] == "imap.example.com"


@pytest.mark.django_db
def test_imap_sync_endpoint_rejects_when_mode_is_not_imap(monkeypatch):
    monkeypatch.setenv("INBOUND_EMAIL_MODE", "webhook")

    org = Organization.objects.create(name="Email Org")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    response = client.post("/settings/email-capture/imap/sync", {"max_messages": 10}, format="json")

    assert response.status_code == 400
    assert response.data["error_code"] == "validation_error"


@pytest.mark.django_db
def test_imap_sync_endpoint_requires_imap_configuration(monkeypatch):
    monkeypatch.setenv("INBOUND_EMAIL_MODE", "imap")

    org = Organization.objects.create(name="Email Org")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    response = client.post("/settings/email-capture/imap/sync", {"max_messages": 10}, format="json")

    assert response.status_code == 400
    assert response.data["error_code"] == "validation_error"
