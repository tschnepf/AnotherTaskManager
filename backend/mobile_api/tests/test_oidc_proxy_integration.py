import pytest
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="",
    KEYCLOAK_ALLOWED_PUBLIC_HOSTS=["tasks.example.com"],
    KEYCLOAK_REALM="taskhub",
    ALLOWED_HOSTS=["testserver", "tasks.example.com"],
)
def test_meta_uses_forwarded_public_host():
    client = APIClient()
    res = client.get("/api/mobile/v1/meta", secure=True, HTTP_HOST="tasks.example.com")
    assert res.status_code == 200
    assert res.data["oidc_discovery_url"].startswith(
        "https://tasks.example.com/idp/realms/taskhub/.well-known/openid-configuration"
    )


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="",
    KEYCLOAK_ALLOWED_PUBLIC_HOSTS=["tasks.example.com"],
    ALLOWED_HOSTS=["testserver", "tasks.example.com", "bad.example.com"],
)
def test_meta_rejects_unapproved_host():
    client = APIClient()
    res = client.get("/api/mobile/v1/meta", secure=True, HTTP_HOST="bad.example.com")
    assert res.status_code == 400
    assert res.data["error"]["code"] in {"invalid", "validation_error", "api_error"}
