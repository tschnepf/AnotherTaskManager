from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from core.models import User
from mobile_api.models import OIDCIdentity


class _FakeHTTPResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def json(self):
        return self._payload


@pytest.mark.django_db
@override_settings(
    KEYCLOAK_WEB_AUTH_ENABLED=True,
    KEYCLOAK_WEB_CLIENT_ID="taskhub-web",
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    AUTH_COOKIE_SECURE=True,
)
def test_web_oidc_start_redirect_sets_signed_flow_cookie():
    client = APIClient()
    response = client.get("/auth/oidc/start?next=/tasks")
    assert response.status_code == 302
    assert "taskhub_oidc_flow" in response.cookies

    location = response["Location"]
    parsed = urlparse(location)
    assert parsed.path.endswith("/idp/realms/taskhub/protocol/openid-connect/auth")
    query = parse_qs(parsed.query)
    assert query["client_id"][0] == "taskhub-web"
    assert query["redirect_uri"][0].endswith("/auth/oidc/callback")
    assert query["code_challenge_method"][0] == "S256"


@pytest.mark.django_db
@override_settings(
    KEYCLOAK_WEB_AUTH_ENABLED=True,
    KEYCLOAK_WEB_CLIENT_ID="taskhub-web",
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    KEYCLOAK_WEB_SIGNUP_ENABLED=True,
)
def test_web_oidc_start_signup_sets_kc_action_register():
    client = APIClient()
    response = client.get("/auth/oidc/start?signup=1")
    assert response.status_code == 302
    parsed = urlparse(response["Location"])
    query = parse_qs(parsed.query)
    assert query["kc_action"][0] == "register"


@pytest.mark.django_db
@override_settings(
    KEYCLOAK_WEB_AUTH_ENABLED=True,
    KEYCLOAK_WEB_CLIENT_ID="taskhub-web",
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    KEYCLOAK_REQUIRED_AUDIENCE="taskhub-api",
    KEYCLOAK_AUTO_PROVISION_USERS=True,
    KEYCLOAK_AUTO_PROVISION_ORGANIZATION=True,
)
def test_web_oidc_callback_creates_session_and_identity(monkeypatch):
    from core import auth_views as auth_mod

    client = APIClient()
    start = client.get("/auth/oidc/start?next=/")
    parsed = urlparse(start["Location"])
    state = parse_qs(parsed.query)["state"][0]

    monkeypatch.setattr(
        auth_mod.requests,
        "post",
        lambda *args, **kwargs: _FakeHTTPResponse(200, {"access_token": "fake-access-token"}),
    )
    monkeypatch.setattr(
        auth_mod.requests,
        "get",
        lambda *args, **kwargs: _FakeHTTPResponse(
            200,
            {
                "sub": "web-sub-1",
                "email": "web-oidc@example.com",
                "given_name": "Web",
                "family_name": "User",
            },
        ),
    )

    callback = client.get(f"/auth/oidc/callback?code=fake-code&state={state}")
    assert callback.status_code == 302
    assert callback["Location"] == "/"
    assert "taskhub_access" in callback.cookies
    assert "taskhub_refresh" in callback.cookies

    user = User.objects.get(email="web-oidc@example.com")
    assert user.organization_id is not None
    identity = OIDCIdentity.objects.get(
        issuer="https://tasks.example.com/idp/realms/taskhub",
        subject="web-sub-1",
    )
    assert identity.user_id == user.id
    assert user.is_superuser is True
    assert user.is_staff is True


@pytest.mark.django_db
@override_settings(KEYCLOAK_WEB_AUTH_ENABLED=False)
def test_web_oidc_start_disabled_returns_404():
    client = APIClient()
    response = client.get("/auth/oidc/start")
    assert response.status_code == 404
