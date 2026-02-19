from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsOwnerOrAdmin
from core.security import rotate_inbound_ingest_token
from core.email_mode import get_inbound_email_mode
from tasks.email_imap_service import is_imap_configured


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def email_capture_settings_view(request):
    org = request.user.organization
    if org is None:
        return Response(
            {"error_code": "validation_error", "message": "user must belong to an organization", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if request.method == "GET":
        return Response(serialize_email_capture_settings(org))

    inbound_email_address = request.data.get("inbound_email_address", None)
    inbound_email_whitelist = request.data.get("inbound_email_whitelist", None)
    rotate_token = _coerce_bool(request.data.get("rotate_token", False))
    imap_username = request.data.get("imap_username", None)
    imap_password = request.data.get("imap_password", None)
    imap_clear_password = _coerce_bool(request.data.get("imap_clear_password", False))
    imap_host = request.data.get("imap_host", None)
    imap_provider = request.data.get("imap_provider", None)
    imap_port = request.data.get("imap_port", None)
    imap_use_ssl = request.data.get("imap_use_ssl", None)
    imap_folder = request.data.get("imap_folder", None)
    imap_search_criteria = request.data.get("imap_search_criteria", None)
    imap_mark_seen_on_success = request.data.get("imap_mark_seen_on_success", None)
    fields_to_update = []
    issued_inbound_token = ""

    if inbound_email_address is not None:
        normalized = str(inbound_email_address).strip().lower()
        if normalized:
            try:
                validate_email(normalized)
            except DjangoValidationError:
                return Response(
                    {
                        "error_code": "validation_error",
                        "message": "inbound_email_address must be a valid email",
                        "details": {},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            org.inbound_email_address = normalized
        else:
            org.inbound_email_address = None
        fields_to_update.append("inbound_email_address")

    if inbound_email_whitelist is not None:
        try:
            normalized_whitelist = _normalize_whitelist(inbound_email_whitelist)
        except ValueError as exc:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": str(exc),
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        org.inbound_email_whitelist = normalized_whitelist
        fields_to_update.append("inbound_email_whitelist")

    if imap_username is not None:
        org.imap_username = str(imap_username or "").strip()
        fields_to_update.append("imap_username")

    if imap_clear_password:
        org.set_imap_password("")
        fields_to_update.append("imap_password")
    elif imap_password is not None:
        # Empty string means "leave unchanged"; use imap_clear_password to clear.
        normalized_password = str(imap_password or "")
        if normalized_password.strip():
            org.set_imap_password(normalized_password)
            fields_to_update.append("imap_password")

    if imap_host is not None:
        org.imap_host = str(imap_host or "").strip().lower()
        fields_to_update.append("imap_host")

    if imap_provider is not None:
        normalized_provider = str(imap_provider or "auto").strip().lower() or "auto"
        org.imap_provider = normalized_provider
        fields_to_update.append("imap_provider")

    if imap_port is not None:
        try:
            normalized_port = int(imap_port)
        except (TypeError, ValueError):
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "imap_port must be a valid integer",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if normalized_port < 1 or normalized_port > 65535:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "imap_port must be between 1 and 65535",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        org.imap_port = normalized_port
        fields_to_update.append("imap_port")

    if imap_use_ssl is not None:
        org.imap_use_ssl = _coerce_bool(imap_use_ssl)
        fields_to_update.append("imap_use_ssl")

    if imap_folder is not None:
        org.imap_folder = str(imap_folder or "").strip() or "INBOX"
        fields_to_update.append("imap_folder")

    if imap_search_criteria is not None:
        org.imap_search_criteria = str(imap_search_criteria or "").strip() or "UNSEEN"
        fields_to_update.append("imap_search_criteria")

    if imap_mark_seen_on_success is not None:
        org.imap_mark_seen_on_success = _coerce_bool(imap_mark_seen_on_success)
        fields_to_update.append("imap_mark_seen_on_success")

    if rotate_token or not org.inbound_email_token:
        issued_inbound_token, hashed_inbound_token = rotate_inbound_ingest_token()
        org.inbound_email_token = hashed_inbound_token
        fields_to_update.append("inbound_email_token")

    if fields_to_update:
        org.save(update_fields=fields_to_update)

    return Response(
        serialize_email_capture_settings(
            org,
            reveal_inbound_token=bool(issued_inbound_token),
            issued_inbound_token=issued_inbound_token,
        )
    )


def _normalize_whitelist(raw_value):
    if raw_value in ("", None):
        return []
    if not isinstance(raw_value, list):
        raise ValueError("inbound_email_whitelist must be an array of email addresses")

    normalized = []
    seen = set()
    for value in raw_value:
        candidate = str(value or "").strip().lower()
        if not candidate:
            continue
        try:
            validate_email(candidate)
        except DjangoValidationError as exc:
            raise ValueError(f"invalid whitelist email: {candidate}") from exc
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)

    if len(normalized) > 200:
        raise ValueError("inbound_email_whitelist cannot contain more than 200 addresses")

    return normalized


def serialize_email_capture_settings(
    org,
    *,
    reveal_inbound_token: bool = False,
    issued_inbound_token: str = "",
):
    inbound_mode = get_inbound_email_mode()
    inbound_token = issued_inbound_token if reveal_inbound_token else ""
    try:
        imap_password_configured = org.has_imap_password()
    except ValueError:
        imap_password_configured = False
    try:
        gmail_oauth_connected = org.has_gmail_oauth_refresh_token()
    except ValueError:
        gmail_oauth_connected = False
    return {
        "inbound_email_address": org.inbound_email_address,
        "inbound_email_token": inbound_token,
        "inbound_email_whitelist": org.inbound_email_whitelist or [],
        "inbound_email_mode": inbound_mode,
        "inbound_email_provider": org.inbound_email_provider,
        "gmail_oauth_email": org.gmail_oauth_email or "",
        "gmail_oauth_connected": gmail_oauth_connected,
        "imap_username": org.imap_username or "",
        "imap_password_configured": imap_password_configured,
        "imap_host": org.imap_host or "",
        "imap_provider": org.imap_provider or "auto",
        "imap_port": org.imap_port or 993,
        "imap_use_ssl": bool(org.imap_use_ssl),
        "imap_folder": org.imap_folder or "INBOX",
        "imap_search_criteria": org.imap_search_criteria or "UNSEEN",
        "imap_mark_seen_on_success": bool(org.imap_mark_seen_on_success),
        "imap_configured": is_imap_configured(org),
    }


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
