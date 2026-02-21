from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Callable

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from mobile_api.exceptions import IdempotencyConflict
from mobile_api.logging import request_id_from_headers
from mobile_api.models import IdempotencyRecord


def _idempotency_ttl_hours() -> int:
    from django.conf import settings

    return int(getattr(settings, "MOBILE_IDEMPOTENCY_TTL_HOURS", 24))


def _canonical_request_hash(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_safe_payload(value):
    return json.loads(json.dumps(value, default=str))


def _record_for(request, endpoint: str, idempotency_key: str):
    now = timezone.now()
    return (
        IdempotencyRecord.objects.filter(
            user=request.user,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            expires_at__gt=now,
        )
        .order_by("-created_at")
        .first()
    )


def with_idempotency(request: HttpRequest, endpoint: str, action: Callable[[], Response]) -> Response:
    idempotency_key = str(request.headers.get("Idempotency-Key") or "").strip()
    if not idempotency_key:
        return Response(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Idempotency-Key header is required",
                    "details": {},
                },
                "request_id": request_id_from_headers(request.headers),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    request_hash = _canonical_request_hash(request.data)
    existing = _record_for(request, endpoint, idempotency_key)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict()
        return Response(existing.response_body, status=existing.response_status)

    response = action()
    if response.status_code >= 500:
        return response

    expires_at = timezone.now() + timedelta(hours=_idempotency_ttl_hours())

    try:
        with transaction.atomic():
            IdempotencyRecord.objects.create(
                user=request.user,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_status=response.status_code,
                response_body=_json_safe_payload(response.data) if isinstance(response.data, (dict, list)) else {},
                expires_at=expires_at,
            )
    except IntegrityError:
        existing = _record_for(request, endpoint, idempotency_key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflict()
            return Response(existing.response_body, status=existing.response_status)

    return response
