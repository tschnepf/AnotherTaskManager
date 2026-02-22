from __future__ import annotations

from typing import Any

from django.db import transaction

from core.models import Organization, User
from mobile_api.models import OIDCIdentity, OIDCIdentityAudit


def claim(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def extract_email(payload: dict[str, Any]) -> str:
    for key in ("email", "preferred_username", "upn"):
        value = str(payload.get(key) or "").strip()
        if value and "@" in value:
            return value.lower()
    return ""


def extract_display_name(payload: dict[str, Any], email: str) -> str:
    candidate = claim(payload, "name")
    if candidate:
        return candidate
    first = claim(payload, "given_name", "first_name")
    last = claim(payload, "family_name", "last_name")
    joined = f"{first} {last}".strip()
    if joined:
        return joined
    preferred = claim(payload, "preferred_username")
    if preferred and "@" not in preferred:
        return preferred
    local = email.split("@", 1)[0] if "@" in email else ""
    return local


def default_organization_name(email: str) -> str:
    local = email.split("@", 1)[0] if "@" in email else "default"
    return f"{local} Organization"


def resolve_or_provision_identity(
    *,
    issuer: str,
    subject: str,
    claims: dict[str, Any],
    auto_provision_users: bool,
    auto_provision_organization: bool,
) -> OIDCIdentity | None:
    existing = OIDCIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
    if existing is not None:
        return existing

    if not auto_provision_users:
        return None

    email = extract_email(claims)
    if not email:
        return None

    with transaction.atomic():
        existing = OIDCIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
        if existing is not None:
            return existing

        user = User.objects.filter(email__iexact=email).first()
        user_created = False
        organization_created = False

        if user is None:
            organization = None
            if auto_provision_organization:
                organization = Organization.objects.create(name=default_organization_name(email))
                organization_created = True

            user = User.objects.create_user(
                email=email,
                password=None,
                display_name=extract_display_name(claims, email),
                first_name=claim(claims, "given_name", "first_name"),
                last_name=claim(claims, "family_name", "last_name"),
                organization=organization,
                role=User.Role.OWNER if organization is not None else User.Role.MEMBER,
            )
            user_created = True
        elif user.organization_id is None and auto_provision_organization:
            organization = Organization.objects.create(name=default_organization_name(email))
            user.organization = organization
            user.role = User.Role.OWNER
            update_fields = ["organization", "role"]
            if not user.display_name:
                display_name = extract_display_name(claims, email)
                if display_name:
                    user.display_name = display_name
                    update_fields.append("display_name")
            user.save(update_fields=update_fields)
            organization_created = True

        identity, created = OIDCIdentity.objects.get_or_create(
            issuer=issuer,
            subject=subject,
            defaults={"user": user},
        )
        if not created and identity.user_id != user.id:
            return identity

        OIDCIdentityAudit.objects.create(
            actor=None,
            action=OIDCIdentityAudit.Action.LINK,
            issuer=identity.issuer,
            subject=identity.subject,
            user=identity.user,
            metadata={
                "auto_provisioned": True,
                "user_created": user_created,
                "organization_created": organization_created,
            },
        )
        return identity
