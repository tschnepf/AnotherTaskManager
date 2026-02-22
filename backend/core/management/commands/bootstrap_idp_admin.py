from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Organization, User
from core.oidc_identity import resolve_or_provision_identity
from core.oidc_urls import build_realm_url


@dataclass
class KeycloakAdminClient:
    base_url: str
    realm: str
    admin_realm: str
    admin_user: str
    admin_password: str

    def _token_url(self) -> str:
        return f"{self.base_url}/realms/{self.admin_realm}/protocol/openid-connect/token"

    def _admin_url(self, path: str) -> str:
        clean = path.lstrip("/")
        return f"{self.base_url}/admin/realms/{self.realm}/{clean}"

    def _access_token(self) -> str:
        response = requests.post(
            self._token_url(),
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.admin_user,
                "password": self.admin_password,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise CommandError("Keycloak admin login succeeded but no access_token returned")
        return token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_user_by_email(self, token: str, email: str) -> dict[str, Any] | None:
        response = requests.get(
            self._admin_url("users"),
            params={"email": email, "exact": "true"},
            headers=self._headers(token),
            timeout=10,
        )
        response.raise_for_status()
        users = response.json() if isinstance(response.json(), list) else []
        needle = email.strip().lower()
        for user in users:
            candidate = str(user.get("email") or user.get("username") or "").strip().lower()
            if candidate == needle:
                return user
        return None

    def create_user(
        self,
        token: str,
        *,
        email: str,
        first_name: str,
        last_name: str,
        enabled: bool,
    ) -> str:
        payload = {
            "username": email,
            "email": email,
            "enabled": enabled,
            "emailVerified": True,
            "firstName": first_name,
            "lastName": last_name,
        }
        response = requests.post(
            self._admin_url("users"),
            headers=self._headers(token),
            data=json.dumps(payload),
            timeout=10,
        )
        if response.status_code not in {201, 204}:
            raise CommandError(f"Failed creating Keycloak user: {response.status_code} {response.text}")
        user = self.get_user_by_email(token, email)
        if not user or not user.get("id"):
            raise CommandError("Created Keycloak user but could not resolve generated user id")
        return str(user["id"])

    def set_password(self, token: str, user_id: str, password: str, *, temporary: bool) -> None:
        payload = {
            "type": "password",
            "value": password,
            "temporary": temporary,
        }
        response = requests.put(
            self._admin_url(f"users/{user_id}/reset-password"),
            headers=self._headers(token),
            data=json.dumps(payload),
            timeout=10,
        )
        if response.status_code not in {204}:
            raise CommandError(f"Failed setting Keycloak password: {response.status_code} {response.text}")


class Command(BaseCommand):
    help = "Create first admin in both Django and Keycloak, then link issuer/subject identity."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Admin email (used for Django + Keycloak)")
        parser.add_argument("--password", required=True, help="Initial Keycloak password")
        parser.add_argument("--first-name", default="", help="First name")
        parser.add_argument("--last-name", default="", help="Last name")
        parser.add_argument("--display-name", default="", help="Display name override")
        parser.add_argument("--organization-name", default="", help="Organization name for first admin user")
        parser.add_argument(
            "--role",
            default=User.Role.OWNER,
            choices=[User.Role.OWNER, User.Role.ADMIN, User.Role.MEMBER],
            help="Django app role",
        )
        parser.add_argument("--realm", default=getattr(settings, "KEYCLOAK_REALM", "taskhub"))
        parser.add_argument("--admin-realm", default="master")
        parser.add_argument("--temporary-password", action="store_true", help="Require password update on first login")
        parser.add_argument("--disable-user", action="store_true", help="Create as disabled in Keycloak")
        parser.add_argument("--keycloak-admin-user", default=str(getattr(settings, "KEYCLOAK_ADMIN_USER", "admin")))
        parser.add_argument(
            "--keycloak-admin-password",
            default=str(getattr(settings, "KEYCLOAK_ADMIN_PASSWORD", "admin")),
        )

    def handle(self, *args, **options):
        email = str(options["email"]).strip().lower()
        if "@" not in email:
            raise CommandError("email must be a valid email address")

        keycloak_base = str(getattr(settings, "KEYCLOAK_BASE_URL", "")).strip().rstrip("/")
        if not keycloak_base:
            raise CommandError("KEYCLOAK_BASE_URL is required")
        if keycloak_base.endswith("/realms"):
            keycloak_base = keycloak_base.rsplit("/realms", 1)[0]
        elif keycloak_base.endswith("/idp"):
            keycloak_base = keycloak_base
        else:
            keycloak_base = f"{keycloak_base}/idp"

        keycloak = KeycloakAdminClient(
            base_url=keycloak_base,
            realm=str(options["realm"]).strip(),
            admin_realm=str(options["admin_realm"]).strip(),
            admin_user=str(options["keycloak_admin_user"]).strip(),
            admin_password=str(options["keycloak_admin_password"]).strip(),
        )

        token = keycloak._access_token()
        existing_kc_user = keycloak.get_user_by_email(token, email)
        if existing_kc_user and existing_kc_user.get("id"):
            keycloak_user_id = str(existing_kc_user["id"])
            self.stdout.write(self.style.WARNING(f"Keycloak user already exists: {email} ({keycloak_user_id})"))
        else:
            keycloak_user_id = keycloak.create_user(
                token,
                email=email,
                first_name=str(options["first_name"]).strip(),
                last_name=str(options["last_name"]).strip(),
                enabled=not bool(options["disable_user"]),
            )
            self.stdout.write(self.style.SUCCESS(f"Created Keycloak user: {email} ({keycloak_user_id})"))

        keycloak.set_password(
            token,
            keycloak_user_id,
            str(options["password"]),
            temporary=bool(options["temporary_password"]),
        )
        self.stdout.write(self.style.SUCCESS("Set Keycloak password"))

        first_name = str(options["first_name"]).strip()
        last_name = str(options["last_name"]).strip()
        display_name = str(options["display_name"]).strip() or " ".join([first_name, last_name]).strip()
        org_name = str(options["organization_name"]).strip() or f"{email.split('@', 1)[0]} Organization"

        with transaction.atomic():
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                organization = Organization.objects.create(name=org_name)
                user = User.objects.create_user(
                    email=email,
                    password=None,
                    first_name=first_name,
                    last_name=last_name,
                    display_name=display_name,
                    organization=organization,
                    role=str(options["role"]),
                    is_staff=True,
                    is_superuser=True,
                )
                created_local = True
            else:
                created_local = False
                updates: list[str] = []
                if user.organization_id is None:
                    user.organization = Organization.objects.create(name=org_name)
                    updates.append("organization")
                if not user.display_name and display_name:
                    user.display_name = display_name
                    updates.append("display_name")
                if user.role != str(options["role"]):
                    user.role = str(options["role"])
                    updates.append("role")
                if not user.is_staff:
                    user.is_staff = True
                    updates.append("is_staff")
                if not user.is_superuser:
                    user.is_superuser = True
                    updates.append("is_superuser")
                if updates:
                    user.save(update_fields=updates)

        issuer = build_realm_url(str(getattr(settings, "KEYCLOAK_PUBLIC_BASE_URL", "")).strip(), keycloak.realm)
        if not issuer:
            raise CommandError("KEYCLOAK_PUBLIC_BASE_URL is required for identity linking")

        identity = resolve_or_provision_identity(
            issuer=issuer,
            subject=keycloak_user_id,
            claims={
                "email": email,
                "given_name": first_name,
                "family_name": last_name,
                "name": display_name,
            },
            auto_provision_users=True,
            auto_provision_organization=True,
        )
        if identity is None:
            raise CommandError("Failed creating OIDC identity link")

        if identity.user_id != user.id:
            identity.user = user
            identity.save(update_fields=["user"])

        if created_local:
            self.stdout.write(self.style.SUCCESS(f"Created Django user: {email} ({user.id})"))
        else:
            self.stdout.write(self.style.WARNING(f"Django user already existed: {email} ({user.id})"))
        self.stdout.write(self.style.SUCCESS(f"Linked OIDC identity: issuer={issuer} sub={keycloak_user_id}"))
