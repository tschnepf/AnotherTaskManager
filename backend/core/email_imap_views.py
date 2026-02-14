from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.email_mode import INBOUND_EMAIL_MODE_IMAP, get_inbound_email_mode
from core.permissions import IsOwnerOrAdmin
from core.settings_views import serialize_email_capture_settings
from tasks.email_imap_service import sync_inbound_imap


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def imap_sync_view(request):
    org = request.user.organization
    if org is None:
        return Response(
            {"error_code": "validation_error", "message": "user must belong to an organization", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if get_inbound_email_mode() != INBOUND_EMAIL_MODE_IMAP:
        return Response(
            {
                "error_code": "validation_error",
                "message": "INBOUND_EMAIL_MODE must be imap to use IMAP sync",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        max_messages = int(request.data.get("max_messages", 25))
    except (TypeError, ValueError):
        max_messages = 25
    max_messages = max(1, min(max_messages, 100))

    try:
        sync_result = sync_inbound_imap(org, max_messages=max_messages)
    except ValueError as exc:
        return Response(
            {"error_code": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            {"error_code": "api_error", "message": f"imap sync failed: {exc}", "details": {}},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    sync_result["settings"] = serialize_email_capture_settings(org)
    return Response(sync_result)
