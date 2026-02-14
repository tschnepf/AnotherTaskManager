from base64 import urlsafe_b64encode
from email.message import EmailMessage
from urllib.parse import parse_qs, urlparse

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.email_oauth_views import (
    GMAIL_MESSAGES_URL,
    GOOGLE_OAUTH_TOKEN_URL,
    GOOGLE_USERINFO_URL,
)
from core.models import Organization, User
from tasks.models import Task


class _MockResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


@pytest.mark.django_db
def test_gmail_oauth_initiate_returns_auth_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/settings")

    org = Organization.objects.create(name="Org")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    response = client.post("/settings/email-capture/oauth/google/initiate", {}, format="json")
    assert response.status_code == 200
    auth_url = response.data["auth_url"]
    assert "accounts.google.com" in auth_url
    assert "state=" in auth_url


@pytest.mark.django_db
def test_gmail_oauth_exchange_connects_org(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/settings")

    org = Organization.objects.create(name="Org")
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    initiate = client.post("/settings/email-capture/oauth/google/initiate", {}, format="json")
    state = parse_qs(urlparse(initiate.data["auth_url"]).query)["state"][0]

    def fake_post(url, data=None, timeout=0, **kwargs):
        assert url == GOOGLE_OAUTH_TOKEN_URL
        assert data["code"] == "oauth-code"
        return _MockResponse(200, {"access_token": "access-token", "refresh_token": "refresh-token"})

    def fake_get(url, headers=None, timeout=0, **kwargs):
        assert url == GOOGLE_USERINFO_URL
        return _MockResponse(200, {"email": "gmail-user@example.com"})

    monkeypatch.setattr("core.email_oauth_views.requests.post", fake_post)
    monkeypatch.setattr("core.email_oauth_views.requests.get", fake_get)

    response = client.post(
        "/settings/email-capture/oauth/google/exchange",
        {"code": "oauth-code", "state": state},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["inbound_email_provider"] == "gmail_oauth"
    assert response.data["gmail_oauth_connected"] is True
    assert response.data["gmail_oauth_email"] == "gmail-user@example.com"

    org.refresh_from_db()
    assert org.gmail_oauth_email == "gmail-user@example.com"
    assert org.gmail_oauth_refresh_token == "refresh-token"


@pytest.mark.django_db
def test_gmail_oauth_sync_imports_message(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/settings")

    org = Organization.objects.create(
        name="Org",
        inbound_email_provider=Organization.InboundEmailProvider.GMAIL_OAUTH,
        inbound_email_address="gmail-user@example.com",
        gmail_oauth_email="gmail-user@example.com",
        gmail_oauth_refresh_token="refresh-token",
    )
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    message = EmailMessage()
    message["From"] = "allowed@example.com"
    message["To"] = "gmail-user@example.com"
    message["Subject"] = "OAuth Task"
    message.set_content("Task from oauth sync\nProject X\nwork\nhigh")
    raw_b64 = urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")

    def fake_post(url, data=None, json=None, timeout=0, **kwargs):
        if url == GOOGLE_OAUTH_TOKEN_URL:
            return _MockResponse(200, {"access_token": "access-token"})
        if url == f"{GMAIL_MESSAGES_URL}/m1/modify":
            return _MockResponse(200, {})
        raise AssertionError(f"unexpected POST url: {url}")

    def fake_get(url, headers=None, params=None, timeout=0, **kwargs):
        if url == GMAIL_MESSAGES_URL:
            return _MockResponse(200, {"messages": [{"id": "m1"}]})
        if url == f"{GMAIL_MESSAGES_URL}/m1":
            return _MockResponse(200, {"raw": raw_b64})
        raise AssertionError(f"unexpected GET url: {url}")

    monkeypatch.setattr("core.email_oauth_views.requests.post", fake_post)
    monkeypatch.setattr("core.email_oauth_views.requests.get", fake_get)

    response = client.post("/settings/email-capture/oauth/google/sync", {"max_messages": 5}, format="json")
    assert response.status_code == 200
    assert response.data["processed"] == 1
    assert response.data["created"] == 1
    assert response.data["failed"] == []
    assert Task.objects.filter(organization=org, title="Task from oauth sync").exists()


@pytest.mark.django_db
def test_gmail_oauth_sync_respects_whitelist(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/settings")

    org = Organization.objects.create(
        name="Org",
        inbound_email_provider=Organization.InboundEmailProvider.GMAIL_OAUTH,
        inbound_email_address="gmail-user@example.com",
        inbound_email_whitelist=["allowed@example.com"],
        gmail_oauth_email="gmail-user@example.com",
        gmail_oauth_refresh_token="refresh-token",
    )
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )
    client = _auth_client(owner)

    message = EmailMessage()
    message["From"] = "blocked@example.com"
    message["To"] = "gmail-user@example.com"
    message["Subject"] = "Blocked Task"
    message.set_content("Blocked task\nProject X\nwork\nhigh")
    raw_b64 = urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")

    def fake_post(url, data=None, json=None, timeout=0, **kwargs):
        if url == GOOGLE_OAUTH_TOKEN_URL:
            return _MockResponse(200, {"access_token": "access-token"})
        if url == f"{GMAIL_MESSAGES_URL}/m1/modify":
            return _MockResponse(200, {})
        raise AssertionError(f"unexpected POST url: {url}")

    def fake_get(url, headers=None, params=None, timeout=0, **kwargs):
        if url == GMAIL_MESSAGES_URL:
            return _MockResponse(200, {"messages": [{"id": "m1"}]})
        if url == f"{GMAIL_MESSAGES_URL}/m1":
            return _MockResponse(200, {"raw": raw_b64})
        raise AssertionError(f"unexpected GET url: {url}")

    monkeypatch.setattr("core.email_oauth_views.requests.post", fake_post)
    monkeypatch.setattr("core.email_oauth_views.requests.get", fake_get)

    response = client.post("/settings/email-capture/oauth/google/sync", {"max_messages": 5}, format="json")
    assert response.status_code == 200
    assert response.data["processed"] == 1
    assert response.data["created"] == 0
    assert len(response.data["failed"]) == 1
