from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class OnboardingRequired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Identity is not linked to a Task Hub account"
    default_code = "onboarding_required"


class IdempotencyConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Idempotency key was reused with a different payload"
    default_code = "idempotency_conflict"


class CursorExpired(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = "Sync cursor expired"
    default_code = "cursor_expired"


class InsufficientScope(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Token does not contain required scopes"
    default_code = "insufficient_scope"
