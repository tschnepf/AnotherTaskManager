import pytest
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
    KEYCLOAK_IOS_CLIENT_ID="taskhub-mobile",
    KEYCLOAK_REQUIRED_AUDIENCE="taskhub-api",
)
def test_oidc_discovery_contract():
    client = APIClient()
    res = client.get("/api/mobile/v1/meta")
    assert res.status_code == 200
    assert res.data["api_version"] == "1"
    assert res.data["oidc_discovery_url"] == (
        "https://tasks.example.com/idp/realms/taskhub/.well-known/openid-configuration"
    )
    assert res.data["oidc_client_id"] == "taskhub-mobile"
    assert "openid" in res.data["required_scopes"]
    assert "offline_access" in res.data["required_scopes"]
    assert res.data["required_audience"] == "taskhub-api"
