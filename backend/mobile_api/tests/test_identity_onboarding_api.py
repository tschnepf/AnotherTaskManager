import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from mobile_api.models import OIDCIdentity


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_admin_can_link_and_unlink_identity():
    org = Organization.objects.create(name="Org")
    admin = User.objects.create_user(
        email="owner@example.com", password="StrongPass123!", organization=org, role=User.Role.OWNER
    )
    target = User.objects.create_user(email="target@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(admin)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create = client.post(
        "/api/mobile/v1/admin/identity-links",
        {"issuer": "https://tasks.example.com/idp/realms/taskhub", "subject": "abc", "user": target.id},
        format="json",
    )
    assert create.status_code in {200, 201}
    identity_id = create.data["id"]
    assert OIDCIdentity.objects.filter(id=identity_id).exists()

    delete = client.delete(f"/api/mobile/v1/admin/identity-links/{identity_id}")
    assert delete.status_code == 204
    assert not OIDCIdentity.objects.filter(id=identity_id).exists()


@pytest.mark.django_db
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_member_cannot_link_identity():
    org = Organization.objects.create(name="Org")
    member = User.objects.create_user(
        email="member@example.com", password="StrongPass123!", organization=org, role=User.Role.MEMBER
    )
    target = User.objects.create_user(email="target2@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(member)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    create = client.post(
        "/api/mobile/v1/admin/identity-links",
        {"issuer": "https://tasks.example.com/idp/realms/taskhub", "subject": "abc", "user": target.id},
        format="json",
    )
    assert create.status_code == 404
