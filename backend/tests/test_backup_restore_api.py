import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core.models import Organization, User


@pytest.mark.django_db
def test_database_backup_requires_owner_or_admin():
    org = Organization.objects.create(name="Org A")
    member = User.objects.create_user(
        email="member@example.com",
        password="StrongPass123!",
        role=User.Role.MEMBER,
        organization=org,
    )

    client = APIClient()
    client.force_authenticate(user=member)
    response = client.get("/ops/database/backup")

    assert response.status_code == 403


@pytest.mark.django_db
def test_database_backup_returns_fixture_file_for_owner():
    org = Organization.objects.create(
        name="Org A",
        inbound_email_token="plain-token",
        gmail_oauth_refresh_token="oauth-refresh",
        imap_password="imap-password",
    )
    owner = User.objects.create_user(
        email="owner@example.com",
        password="StrongPass123!",
        role=User.Role.OWNER,
        organization=org,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get("/ops/database/backup")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert "attachment; filename=" in response["Content-Disposition"]
    payload = json.loads(response.content.decode("utf-8"))
    assert isinstance(payload, list)
    assert any(item.get("model") == "core.organization" for item in payload)
    org_fixture = next(item for item in payload if item.get("model") == "core.organization")
    assert org_fixture["fields"]["inbound_email_token"] == ""
    assert org_fixture["fields"]["gmail_oauth_refresh_token"] == ""
    assert org_fixture["fields"]["imap_password"] == ""


@pytest.mark.django_db
def test_database_restore_validates_inputs_and_permissions():
    org = Organization.objects.create(name="Org A")
    admin = User.objects.create_user(
        email="admin@example.com",
        password="StrongPass123!",
        role=User.Role.ADMIN,
        organization=org,
    )
    member = User.objects.create_user(
        email="member@example.com",
        password="StrongPass123!",
        role=User.Role.MEMBER,
        organization=org,
    )

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)

    missing_file = admin_client.post("/ops/database/restore", {"confirm": "RESTORE"}, format="multipart")
    assert missing_file.status_code == 400
    assert missing_file.data["error_code"] == "validation_error"

    bad_confirm = admin_client.post(
        "/ops/database/restore",
        {
            "confirm": "WRONG",
            "backup_file": SimpleUploadedFile(
                "backup.json",
                b"[]",
                content_type="application/json",
            ),
        },
        format="multipart",
    )
    assert bad_confirm.status_code == 400
    assert bad_confirm.data["error_code"] == "validation_error"

    bad_json = admin_client.post(
        "/ops/database/restore",
        {
            "confirm": "RESTORE",
            "backup_file": SimpleUploadedFile(
                "backup.json",
                b"not-json",
                content_type="application/json",
            ),
        },
        format="multipart",
    )
    assert bad_json.status_code == 400
    assert bad_json.data["error_code"] == "validation_error"

    member_client = APIClient()
    member_client.force_authenticate(user=member)
    denied = member_client.post(
        "/ops/database/restore",
        {
            "confirm": "RESTORE",
            "backup_file": SimpleUploadedFile(
                "backup.json",
                b"[]",
                content_type="application/json",
            ),
        },
        format="multipart",
    )
    assert denied.status_code == 403
