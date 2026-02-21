from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from core.models import User
from mobile_api.models import OIDCIdentity


@dataclass
class IdentityMappingRow:
    email: str
    subject: str
    issuer: str


def load_identity_mapping_csv(path: str | Path, *, default_issuer: str) -> list[IdentityMappingRow]:
    rows: list[IdentityMappingRow] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            email = str(row.get("email") or "").strip().lower()
            subject = str(row.get("subject") or "").strip()
            issuer = str(row.get("issuer") or default_issuer).strip()
            if not email or not subject or not issuer:
                continue
            rows.append(IdentityMappingRow(email=email, subject=subject, issuer=issuer))
    return rows


def backfill_oidc_identities(rows: list[IdentityMappingRow], *, dry_run: bool = True) -> dict:
    report = {
        "total_rows": len(rows),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "missing_users": [],
        "invalid_rows": [],
    }

    for row in rows:
        user = User.objects.filter(email__iexact=row.email).first()
        if user is None:
            report["missing_users"].append({"email": row.email, "subject": row.subject})
            continue

        existing = OIDCIdentity.objects.filter(issuer=row.issuer, subject=row.subject).first()
        if existing is not None and existing.user_id == user.id:
            report["unchanged"] += 1
            continue

        if dry_run:
            if existing is None:
                report["created"] += 1
            else:
                report["updated"] += 1
            continue

        identity, created = OIDCIdentity.objects.update_or_create(
            issuer=row.issuer,
            subject=row.subject,
            defaults={"user": user},
        )
        if created:
            report["created"] += 1
        elif identity.user_id == user.id:
            report["updated"] += 1

    return report
