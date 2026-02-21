import jwt
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from core.models import Organization, User
from mobile_api.models import OIDCIdentity


def _patch_jwt_happy_path(monkeypatch, payload):
    from mobile_api import authentication as auth_mod

    monkeypatch.setattr(auth_mod.jwt, "get_unverified_header", lambda _token: {"alg": "RS256", "kid": "kid1"})
    monkeypatch.setattr(auth_mod, "_get_jwks", lambda issuer, force_refresh=False: {"kid1": {"kid": "kid1"}})
    monkeypatch.setattr(auth_mod.jwt.algorithms.RSAAlgorithm, "from_jwk", lambda _value: "fake-key")
    monkeypatch.setattr(auth_mod.jwt, "decode", lambda *args, **kwargs: payload)


@override_settings(
    KEYCLOAK_BASE_URL="http://keycloak:8080/idp",
    KEYCLOAK_REALM="taskhub",
)
def test_jwks_url_uses_internal_keycloak_base_url():
    from mobile_api.authentication import _jwks_url

    assert (
        _jwks_url("https://tasks.example.com/idp/realms/taskhub")
        == "http://keycloak:8080/idp/realms/taskhub/protocol/openid-connect/certs"
    )


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    KEYCLOAK_REQUIRED_AUDIENCE="taskhub-api",
)
def test_keycloak_jwt_success(monkeypatch):
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="oidc@example.com", password="StrongPass123!", organization=org)
    OIDCIdentity.objects.create(
        issuer="https://tasks.example.com/idp/realms/taskhub",
        subject="sub-1",
        user=user,
    )
    _patch_jwt_happy_path(monkeypatch, {"sub": "sub-1", "scope": "mobile.read mobile.sync"})

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer fake-token")
    res = client.get("/api/mobile/v1/session")
    assert res.status_code == 200
    assert res.data["organization_id"] == str(org.id)


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    KEYCLOAK_REQUIRED_AUDIENCE="taskhub-api",
)
def test_invalid_audience_is_reported(monkeypatch):
    from mobile_api import authentication as auth_mod

    monkeypatch.setattr(auth_mod.jwt, "get_unverified_header", lambda _token: {"alg": "RS256", "kid": "kid1"})
    monkeypatch.setattr(auth_mod, "_get_jwks", lambda issuer, force_refresh=False: {"kid1": {"kid": "kid1"}})
    monkeypatch.setattr(auth_mod.jwt.algorithms.RSAAlgorithm, "from_jwk", lambda _value: "fake-key")

    def _raise_invalid_aud(*args, **kwargs):
        raise jwt.InvalidAudienceError("bad audience")

    monkeypatch.setattr(auth_mod.jwt, "decode", _raise_invalid_aud)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer bad-token")
    res = client.get("/api/mobile/v1/session")
    assert res.status_code == 401
    assert res.data["error"]["code"] == "invalid_audience"


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    KEYCLOAK_REQUIRED_AUDIENCE="taskhub-api",
)
def test_onboarding_required_when_identity_missing(monkeypatch):
    _patch_jwt_happy_path(monkeypatch, {"sub": "missing-sub", "scope": "mobile.read"})
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer fake-token")
    res = client.get("/api/mobile/v1/session")
    assert res.status_code == 403
    assert res.data["error"]["code"] == "onboarding_required"
