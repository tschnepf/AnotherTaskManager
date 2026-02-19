import pytest
from django.conf import settings
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
    assert login_res.data["user_id"]
    assert login_res.data["organization_id"]
    assert settings.AUTH_COOKIE_ACCESS_NAME in login_res.cookies
    assert settings.AUTH_COOKIE_REFRESH_NAME in login_res.cookies

    session_res = client.get("/auth/session")
    assert session_res.status_code == 200
    assert session_res.data["organization_id"] == login_res.data["organization_id"]

    refresh_res = client.post("/auth/refresh", {}, format="json")
    assert refresh_res.status_code == 200
    assert refresh_res.data["status"] == "refreshed"
    assert settings.AUTH_COOKIE_ACCESS_NAME in refresh_res.cookies

    logout_res = client.post("/auth/logout", {}, format="json")
    assert logout_res.status_code == 200

    session_after_logout = client.get("/auth/session")
    assert session_after_logout.status_code == 401


@pytest.mark.django_db
def test_auth_register_and_login_require_csrf_when_csrf_checks_enabled():
    email = "csrf-owner@example.com"
    password = "StrongPass123!"

    client = APIClient(enforce_csrf_checks=True)

    register_without_csrf = client.post(
        "/auth/register",
        {
            "email": email,
            "password": password,
            "display_name": "Owner",
            "organization_name": "Org A",
        },
        format="json",
    )
    assert register_without_csrf.status_code == 403

    csrf_res = client.get("/auth/csrf")
    assert csrf_res.status_code == 200
    csrf_token = client.cookies["csrftoken"].value

    register_with_csrf = client.post(
        "/auth/register",
        {
            "email": email,
            "password": password,
            "display_name": "Owner",
            "organization_name": "Org A",
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert register_with_csrf.status_code == 201

    login_without_csrf = client.post(
        "/auth/login",
        {"email": email, "password": password},
        format="json",
    )
    assert login_without_csrf.status_code == 403

    login_with_csrf = client.post(
        "/auth/login",
        {"email": email, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_with_csrf.status_code == 200


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

    allowed = client_a.get(f"/auth/tenant-check/{org_a}")
    denied = client_a.get(f"/auth/tenant-check/{org_b}")

    assert allowed.status_code == 200
    assert denied.status_code == 404
