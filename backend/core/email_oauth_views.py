import base64
import os
import secrets
from urllib.parse import urlencode

import requests
from django.core import signing
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import Organization
from core.permissions import IsOwnerOrAdmin
from core.settings_views import serialize_email_capture_settings
from tasks.email_capture_service import EmailIngestError, ingest_raw_email_for_org

GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
STATE_SALT = "taskhub-gmail-oauth-state"


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def gmail_oauth_initiate_view(request):
    org = request.user.organization
    if org is None:
        return Response(
            {"error_code": "validation_error", "message": "user must belong to an organization", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        client_id, _client_secret, redirect_uri = _google_oauth_config()
    except ValueError as exc:
        return Response(
            {"error_code": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    state = signing.dumps(
        {
            "organization_id": str(org.id),
            "nonce": secrets.token_urlsafe(16),
        },
        salt=STATE_SALT,
    )
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": f"{GMAIL_SCOPE} openid email",
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }
    if org.inbound_email_address:
        query["login_hint"] = org.inbound_email_address

    return Response(
        {
            "auth_url": f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(query)}",
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def gmail_oauth_exchange_view(request):
    org = request.user.organization
    if org is None:
        return Response(
            {"error_code": "validation_error", "message": "user must belong to an organization", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    code = str(request.data.get("code") or "").strip()
    state_value = str(request.data.get("state") or "").strip()
    if not code or not state_value:
        return Response(
            {"error_code": "validation_error", "message": "code and state are required", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        state_payload = signing.loads(state_value, salt=STATE_SALT, max_age=600)
    except signing.BadSignature:
        return Response(
            {"error_code": "forbidden", "message": "invalid oauth state", "details": {}},
            status=status.HTTP_403_FORBIDDEN,
        )
    if state_payload.get("organization_id") != str(org.id):
        return Response(
            {"error_code": "forbidden", "message": "oauth state does not match organization", "details": {}},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        client_id, client_secret, redirect_uri = _google_oauth_config()
    except ValueError as exc:
        return Response(
            {"error_code": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token_response = requests.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return Response(
            {"error_code": "api_error", "message": f"oauth token exchange failed: {exc}", "details": {}},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if token_response.status_code >= 400:
        return Response(
            {
                "error_code": "validation_error",
                "message": "oauth token exchange failed",
                "details": {"provider_status": token_response.status_code},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    token_payload = token_response.json()
    access_token = str(token_payload.get("access_token") or "").strip()
    try:
        existing_refresh_token = org.get_gmail_oauth_refresh_token()
    except ValueError:
        existing_refresh_token = ""
    refresh_token = str(token_payload.get("refresh_token") or "").strip() or existing_refresh_token
    if not access_token:
        return Response(
            {"error_code": "validation_error", "message": "oauth token exchange returned no access token", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not refresh_token:
        return Response(
            {
                "error_code": "validation_error",
                "message": "oauth token exchange returned no refresh token; reconnect with consent prompt",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        userinfo_response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        return Response(
            {"error_code": "api_error", "message": f"failed to fetch oauth user profile: {exc}", "details": {}},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if userinfo_response.status_code >= 400:
        return Response(
            {"error_code": "validation_error", "message": "failed to fetch oauth user profile", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    gmail_email = str(userinfo_response.json().get("email") or "").strip().lower()
    if not gmail_email:
        return Response(
            {"error_code": "validation_error", "message": "oauth user profile returned no email", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    org.inbound_email_provider = Organization.InboundEmailProvider.GMAIL_OAUTH
    org.gmail_oauth_email = gmail_email
    org.set_gmail_oauth_refresh_token(refresh_token)
    update_fields = [
        "inbound_email_provider",
        "gmail_oauth_email",
        "gmail_oauth_refresh_token",
    ]
    if not org.inbound_email_address:
        org.inbound_email_address = gmail_email
        update_fields.append("inbound_email_address")
    org.save(update_fields=update_fields)

    return Response(serialize_email_capture_settings(org))


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def gmail_oauth_disconnect_view(request):
    org = request.user.organization
    if org is None:
        return Response(
            {"error_code": "validation_error", "message": "user must belong to an organization", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    org.inbound_email_provider = Organization.InboundEmailProvider.WEBHOOK
    org.gmail_oauth_email = ""
    org.set_gmail_oauth_refresh_token("")
    org.save(update_fields=["inbound_email_provider", "gmail_oauth_email", "gmail_oauth_refresh_token"])
    return Response(serialize_email_capture_settings(org))


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def gmail_oauth_sync_view(request):
    org = request.user.organization
    if org is None:
        return Response(
            {"error_code": "validation_error", "message": "user must belong to an organization", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        refresh_token = org.get_gmail_oauth_refresh_token()
    except ValueError:
        refresh_token = ""
    if not refresh_token:
        return Response(
            {"error_code": "validation_error", "message": "gmail oauth is not connected", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        max_messages = int(request.data.get("max_messages", 10))
    except (TypeError, ValueError):
        max_messages = 10
    max_messages = max(1, min(max_messages, 50))
    query = str(request.data.get("query") or "is:unread in:inbox").strip()

    try:
        access_token = _refresh_google_access_token(refresh_token)
    except ValueError as exc:
        return Response(
            {"error_code": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except requests.RequestException as exc:
        return Response(
            {"error_code": "api_error", "message": f"oauth refresh failed: {exc}", "details": {}},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        list_response = requests.get(
            GMAIL_MESSAGES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"q": query, "maxResults": max_messages},
            timeout=20,
        )
    except requests.RequestException as exc:
        return Response(
            {"error_code": "api_error", "message": f"gmail messages list failed: {exc}", "details": {}},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if list_response.status_code >= 400:
        return Response(
            {"error_code": "api_error", "message": "gmail messages list failed", "details": {}},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    messages = list_response.json().get("messages") or []
    created_count = 0
    failed = []
    processed_ids = []
    for message in messages:
        message_id = str(message.get("id") or "").strip()
        if not message_id:
            continue
        processed_ids.append(message_id)
        try:
            raw_response = requests.get(
                f"{GMAIL_MESSAGES_URL}/{message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"format": "raw"},
                timeout=20,
            )
            if raw_response.status_code >= 400:
                failed.append({"id": message_id, "message": "failed to fetch message raw"})
                continue

            raw_value = str((raw_response.json() or {}).get("raw") or "").strip()
            if not raw_value:
                failed.append({"id": message_id, "message": "message raw payload missing"})
                continue
            padding = "=" * ((4 - len(raw_value) % 4) % 4)
            raw_eml = base64.urlsafe_b64decode(raw_value + padding)
            ingest_raw_email_for_org(org, raw_eml)
            created_count += 1

            requests.post(
                f"{GMAIL_MESSAGES_URL}/{message_id}/modify",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"removeLabelIds": ["UNREAD"]},
                timeout=20,
            )
        except EmailIngestError as exc:
            failed.append({"id": message_id, "error_code": exc.error_code, "message": exc.message})
        except requests.RequestException as exc:
            failed.append({"id": message_id, "message": f"gmail request failed: {exc}"})
        except Exception as exc:
            failed.append({"id": message_id, "message": f"processing failed: {exc}"})

    return Response(
        {
            "processed": len(processed_ids),
            "created": created_count,
            "failed": failed,
            "settings": serialize_email_capture_settings(org),
        }
    )


def _google_oauth_config():
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise ValueError(
            "google oauth is not configured; set GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REDIRECT_URI"
        )
    return client_id, client_secret, redirect_uri


def _refresh_google_access_token(refresh_token: str) -> str:
    client_id, client_secret, _redirect_uri = _google_oauth_config()
    response = requests.post(
        GOOGLE_OAUTH_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise ValueError("google oauth refresh token is invalid or expired")

    token = str((response.json() or {}).get("access_token") or "").strip()
    if not token:
        raise ValueError("google oauth refresh returned no access token")
    return token
