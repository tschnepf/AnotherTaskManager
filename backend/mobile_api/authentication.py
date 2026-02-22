from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import jwt
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from core.authentication import CookieOrHeaderJWTAuthentication
from core.models import Organization, User
from mobile_api.exceptions import OnboardingRequired
from mobile_api.models import OIDCIdentity, OIDCIdentityAudit


@dataclass
class JWKSCacheEntry:
    keys: dict[str, Any]
    fetched_at: float


_jwks_cache: JWKSCacheEntry | None = None


def _clock_skew_seconds() -> int:
    return int(getattr(settings, "MOBILE_TOKEN_CLOCK_SKEW_SECONDS", 60))


def _build_realm_url(raw_base_url: str, realm: str) -> str:
    base = str(raw_base_url).strip().rstrip("/")
    if not base:
        return ""
    if base.endswith(f"/realms/{realm}"):
        return base
    if "/realms/" in base:
        return base
    if base.endswith("/realms"):
        return f"{base}/{realm}"
    if base.endswith("/idp"):
        return f"{base}/realms/{realm}"
    return f"{base}/idp/realms/{realm}"


def _build_issuer() -> str:
    realm = str(getattr(settings, "KEYCLOAK_REALM", "taskhub")).strip()
    base = _build_realm_url(getattr(settings, "KEYCLOAK_PUBLIC_BASE_URL", ""), realm)
    if not base:
        raise exceptions.AuthenticationFailed("KEYCLOAK_PUBLIC_BASE_URL is required when KEYCLOAK_AUTH_ENABLED")
    return base


def _jwks_url(issuer: str) -> str:
    realm = str(getattr(settings, "KEYCLOAK_REALM", "taskhub")).strip()
    internal_realm_url = _build_realm_url(getattr(settings, "KEYCLOAK_BASE_URL", ""), realm)
    if internal_realm_url:
        return f"{internal_realm_url}/protocol/openid-connect/certs"
    return f"{issuer}/protocol/openid-connect/certs"


def _allowed_algs() -> list[str]:
    raw = str(getattr(settings, "KEYCLOAK_ALLOWED_ALGS", "RS256")).strip()
    return [segment.strip() for segment in raw.split(",") if segment.strip()] or ["RS256"]


def _extract_scopes(payload: dict[str, Any]) -> set[str]:
    scopes = set()
    raw_scope = payload.get("scope")
    if isinstance(raw_scope, str):
        scopes.update(piece for piece in raw_scope.split() if piece)
    scp = payload.get("scp")
    if isinstance(scp, list):
        scopes.update(str(piece) for piece in scp if piece)
    return scopes


def _auto_provision_users_enabled() -> bool:
    return bool(getattr(settings, "KEYCLOAK_AUTO_PROVISION_USERS", False))


def _auto_provision_organization_enabled() -> bool:
    return bool(getattr(settings, "KEYCLOAK_AUTO_PROVISION_ORGANIZATION", True))


def _claim(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_email(payload: dict[str, Any]) -> str:
    for key in ("email", "preferred_username", "upn"):
        value = str(payload.get(key) or "").strip()
        if value and "@" in value:
            return value.lower()
    return ""


def _extract_display_name(payload: dict[str, Any], email: str) -> str:
    candidate = _claim(payload, "name")
    if candidate:
        return candidate
    first = _claim(payload, "given_name", "first_name")
    last = _claim(payload, "family_name", "last_name")
    joined = f"{first} {last}".strip()
    if joined:
        return joined
    preferred = _claim(payload, "preferred_username")
    if preferred and "@" not in preferred:
        return preferred
    local = email.split("@", 1)[0] if "@" in email else ""
    return local


def _default_organization_name(email: str) -> str:
    local = email.split("@", 1)[0] if "@" in email else "default"
    return f"{local} Organization"


def _provision_identity_from_claims(*, issuer: str, subject: str, payload: dict[str, Any]) -> OIDCIdentity | None:
    if not _auto_provision_users_enabled():
        return None

    email = _extract_email(payload)
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
            if _auto_provision_organization_enabled():
                organization = Organization.objects.create(name=_default_organization_name(email))
                organization_created = True

            user = User.objects.create_user(
                email=email,
                password=None,
                display_name=_extract_display_name(payload, email),
                first_name=_claim(payload, "given_name", "first_name"),
                last_name=_claim(payload, "family_name", "last_name"),
                organization=organization,
                role=User.Role.OWNER if organization is not None else User.Role.MEMBER,
            )
            user_created = True
        elif user.organization_id is None and _auto_provision_organization_enabled():
            organization = Organization.objects.create(name=_default_organization_name(email))
            user.organization = organization
            user.role = User.Role.OWNER
            update_fields = ["organization", "role"]
            if not user.display_name:
                display_name = _extract_display_name(payload, email)
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


def _get_jwks(issuer: str, force_refresh: bool = False) -> dict[str, Any]:
    global _jwks_cache

    now = time.time()
    soft_ttl = int(getattr(settings, "KEYCLOAK_JWKS_SOFT_TTL_SECONDS", 300))
    hard_ttl = int(getattr(settings, "KEYCLOAK_JWKS_HARD_TTL_SECONDS", 3600))
    timeout = int(getattr(settings, "KEYCLOAK_JWKS_FETCH_TIMEOUT_SECONDS", 3))

    if not force_refresh and _jwks_cache is not None:
        age = now - _jwks_cache.fetched_at
        if age <= soft_ttl:
            return _jwks_cache.keys

    if _jwks_cache is not None and (now - _jwks_cache.fetched_at) <= hard_ttl and not force_refresh:
        # Serve stale while refresh attempt happens.
        try:
            response = requests.get(_jwks_url(issuer), timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            keys = {key.get("kid"): key for key in payload.get("keys", []) if key.get("kid")}
            _jwks_cache = JWKSCacheEntry(keys=keys, fetched_at=now)
            return keys
        except Exception:  # noqa: BLE001
            return _jwks_cache.keys

    response = requests.get(_jwks_url(issuer), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    keys = {key.get("kid"): key for key in payload.get("keys", []) if key.get("kid")}
    _jwks_cache = JWKSCacheEntry(keys=keys, fetched_at=now)
    return keys


class MobileJWTAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        if not getattr(settings, "KEYCLOAK_AUTH_ENABLED", False):
            result = CookieOrHeaderJWTAuthentication().authenticate(request)
            if result is None:
                raise exceptions.NotAuthenticated("invalid_token")
            return result

        auth = get_authorization_header(request).split()
        if not auth:
            raise exceptions.NotAuthenticated("invalid_token")
        if auth[0].lower() != b"bearer" or len(auth) != 2:
            raise exceptions.AuthenticationFailed("Invalid authorization header")

        token = auth[1].decode("utf-8")
        issuer = _build_issuer()
        required_audience = str(getattr(settings, "KEYCLOAK_REQUIRED_AUDIENCE", "taskhub-api")).strip()

        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:  # noqa: BLE001
            raise exceptions.AuthenticationFailed("invalid_token") from exc

        algorithm = str(header.get("alg") or "")
        if algorithm not in _allowed_algs():
            raise exceptions.AuthenticationFailed("invalid_token")

        kid = str(header.get("kid") or "").strip()
        if not kid:
            raise exceptions.AuthenticationFailed("invalid_token")

        jwks = _get_jwks(issuer=issuer)
        jwk = jwks.get(kid)
        if jwk is None:
            jwks = _get_jwks(issuer=issuer, force_refresh=True)
            jwk = jwks.get(kid)
            if jwk is None:
                raise exceptions.AuthenticationFailed("invalid_token")

        key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))

        try:
            payload = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=required_audience,
                issuer=issuer,
                options={"require": ["exp", "iat", "sub", "iss"]},
                leeway=_clock_skew_seconds(),
            )
        except jwt.InvalidAudienceError as exc:
            raise exceptions.AuthenticationFailed("invalid_audience") from exc
        except Exception as exc:  # noqa: BLE001
            raise exceptions.AuthenticationFailed("invalid_token") from exc

        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise exceptions.AuthenticationFailed("invalid_token")

        try:
            identity = OIDCIdentity.objects.select_related("user").get(issuer=issuer, subject=subject)
        except OIDCIdentity.DoesNotExist as exc:
            identity = _provision_identity_from_claims(issuer=issuer, subject=subject, payload=payload)
            if identity is None:
                raise OnboardingRequired() from exc

        identity.last_seen_at = timezone.now()
        identity.save(update_fields=["last_seen_at"])

        payload_scopes = _extract_scopes(payload)
        payload["_scope_set"] = payload_scopes
        return identity.user, payload
