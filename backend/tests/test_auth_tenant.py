import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_auth_register_login_refresh_logout_flow():
    client = APIClient()
    email = "owner@example.com"
    password = "StrongPass123!"

    register_res = client.post(
        "/auth/register",
        {
            "email": email,
            "password": password,
            "display_name": "Owner",
            "organization_name": "Org A",
        },
        format="json",
    )
    assert register_res.status_code == 201

    login_res = client.post("/auth/login", {"email": email, "password": password}, format="json")
    assert login_res.status_code == 200
    assert "access" in login_res.data
    assert "refresh" in login_res.data

    refresh_res = client.post("/auth/refresh", {"refresh": login_res.data["refresh"]}, format="json")
    assert refresh_res.status_code == 200
    assert "access" in refresh_res.data

    logout_res = client.post("/auth/logout", {"refresh": login_res.data["refresh"]}, format="json")
    assert logout_res.status_code == 200


@pytest.mark.django_db
def test_tenant_cross_org_access_returns_404():
    client_a = APIClient()
    client_b = APIClient()

    client_a.post(
        "/auth/register",
        {
            "email": "a@example.com",
            "password": "StrongPass123!",
            "organization_name": "Org A",
        },
        format="json",
    )
    client_b.post(
        "/auth/register",
        {
            "email": "b@example.com",
            "password": "StrongPass123!",
            "organization_name": "Org B",
        },
        format="json",
    )

    login_a = client_a.post("/auth/login", {"email": "a@example.com", "password": "StrongPass123!"}, format="json")
    login_b = client_b.post("/auth/login", {"email": "b@example.com", "password": "StrongPass123!"}, format="json")

    org_a = login_a.data["organization_id"]
    org_b = login_b.data["organization_id"]

    client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {login_a.data['access']}")

    allowed = client_a.get(f"/auth/tenant-check/{org_a}")
    denied = client_a.get(f"/auth/tenant-check/{org_b}")

    assert allowed.status_code == 200
    assert denied.status_code == 404
