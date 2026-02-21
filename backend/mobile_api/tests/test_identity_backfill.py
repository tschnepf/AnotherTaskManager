import pytest

from core.models import Organization, User
from mobile_api.backfill import backfill_oidc_identities, load_identity_mapping_csv
from mobile_api.models import OIDCIdentity


@pytest.mark.django_db
def test_identity_backfill_dry_run_and_apply(tmp_path):
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="map@example.com", password="StrongPass123!", organization=org)

    csv_path = tmp_path / "identity-map.csv"
    csv_path.write_text(
        "email,subject,issuer\n"
        "map@example.com,sub-1,https://tasks.example.com/idp/realms/taskhub\n"
        "missing@example.com,sub-2,https://tasks.example.com/idp/realms/taskhub\n",
        encoding="utf-8",
    )

    rows = load_identity_mapping_csv(csv_path, default_issuer="https://tasks.example.com/idp/realms/taskhub")
    report_dry = backfill_oidc_identities(rows, dry_run=True)
    assert report_dry["created"] == 1
    assert len(report_dry["missing_users"]) == 1
    assert OIDCIdentity.objects.count() == 0

    report_apply = backfill_oidc_identities(rows, dry_run=False)
    assert report_apply["created"] == 1
    identity = OIDCIdentity.objects.get(issuer="https://tasks.example.com/idp/realms/taskhub", subject="sub-1")
    assert identity.user_id == user.id
