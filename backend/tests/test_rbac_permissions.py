import pytest

from core.models import Organization, User
from core.rbac import can_assign_to_user, can_manage_org_resources


@pytest.mark.django_db
def test_rbac_owner_admin_manage_resources():
    org = Organization.objects.create(name="Org")
    owner = User.objects.create_user(email="owner@x.com", password="StrongPass123!", role=User.Role.OWNER, organization=org)
    admin = User.objects.create_user(email="admin@x.com", password="StrongPass123!", role=User.Role.ADMIN, organization=org)
    member = User.objects.create_user(email="member@x.com", password="StrongPass123!", role=User.Role.MEMBER, organization=org)

    assert can_manage_org_resources(owner) is True
    assert can_manage_org_resources(admin) is True
    assert can_manage_org_resources(member) is False


@pytest.mark.django_db
def test_rbac_assignment_rules():
    org1 = Organization.objects.create(name="Org1")
    org2 = Organization.objects.create(name="Org2")

    owner = User.objects.create_user(email="owner@x.com", password="StrongPass123!", role=User.Role.OWNER, organization=org1)
    member_same_org = User.objects.create_user(email="member@x.com", password="StrongPass123!", role=User.Role.MEMBER, organization=org1)
    member_other_org = User.objects.create_user(email="other@x.com", password="StrongPass123!", role=User.Role.MEMBER, organization=org2)

    assert can_assign_to_user(owner, member_same_org) is True
    assert can_assign_to_user(member_same_org, member_same_org) is True
    assert can_assign_to_user(member_same_org, owner) is False
    assert can_assign_to_user(owner, member_other_org) is False
