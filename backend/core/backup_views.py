import json
import os
import tempfile

from django.core.management import call_command
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsOwnerOrAdmin

RESTORE_CONFIRM_VALUE = "RESTORE"
MAX_BACKUP_FILE_SIZE_BYTES = 100 * 1024 * 1024


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def database_backup_view(request):
    buffer = tempfile.SpooledTemporaryFile(mode="w+t", max_size=5 * 1024 * 1024, encoding="utf-8")
    try:
        call_command(
            "dumpdata",
            "--natural-foreign",
            "--natural-primary",
            "--indent",
            "2",
            stdout=buffer,
        )
        buffer.seek(0)
        payload = buffer.read()
    finally:
        buffer.close()

    filename = f'taskhub-backup-{timezone.now().strftime("%Y%m%d-%H%M%S")}.json'
    response = HttpResponse(payload, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOwnerOrAdmin])
def database_restore_view(request):
    uploaded_file = request.FILES.get("backup_file")
    if uploaded_file is None:
        return Response(
            {
                "error_code": "validation_error",
                "message": "backup_file is required",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if uploaded_file.size > MAX_BACKUP_FILE_SIZE_BYTES:
        return Response(
            {
                "error_code": "validation_error",
                "message": "backup_file exceeds 100MB limit",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    confirm_value = (request.data.get("confirm") or "").strip().upper()
    if confirm_value != RESTORE_CONFIRM_VALUE:
        return Response(
            {
                "error_code": "validation_error",
                "message": f'confirm must be "{RESTORE_CONFIRM_VALUE}"',
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payload = uploaded_file.read().decode("utf-8")
    except UnicodeDecodeError:
        return Response(
            {
                "error_code": "validation_error",
                "message": "backup_file must be valid UTF-8 JSON",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        parsed_payload = json.loads(payload)
    except json.JSONDecodeError:
        return Response(
            {
                "error_code": "validation_error",
                "message": "backup_file must be valid JSON",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not isinstance(parsed_payload, list):
        return Response(
            {
                "error_code": "validation_error",
                "message": "backup_file must be a JSON fixture array",
                "details": {},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
            tmp_path = tmp_file.name

        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", tmp_path, verbosity=0)
    except Exception as cause:
        return Response(
            {
                "error_code": "restore_failed",
                "message": "Database restore failed",
                "details": {"cause": str(cause)},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return Response(
        {
            "status": "restored",
            "message": "Database restore completed. Please sign in again.",
        },
        status=status.HTTP_200_OK,
    )
