from __future__ import annotations

from datetime import timezone as dt_timezone
from typing import Any

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import User
from mobile_api.authentication import MobileJWTAuthentication
from mobile_api.idempotency import with_idempotency
from mobile_api.logging import request_id_from_headers
from mobile_api.models import (
    MobileDevice,
    NotificationPreference,
    OIDCIdentity,
    OIDCIdentityAudit,
    UserMobilePreference,
)
from mobile_api.permissions import (
    MobileApiEnabledPermission,
    MobileAuthenticatedPermission,
    MobileScopePermission,
)
from mobile_api.serializers import (
    MobileDeviceSerializer,
    MobileMetaSerializer,
    MobileTaskSerializer,
    NotificationPreferenceSerializer,
    OIDCIdentitySerializer,
    SessionSerializer,
    UserMobilePreferenceSerializer,
    WidgetTaskSerializer,
    XcodeDeviceRegisterSerializer,
    XcodeDeviceUnregisterSerializer,
)
from mobile_api.sync import decode_cursor, encode_cursor
from mobile_api.throttles import MobileAuthRateThrottle, MobileIntentRateThrottle, MobileSyncRateThrottle
from tasks.models import Task, TaskChangeEvent
from tasks.serializers import TaskSerializer


class MobileEnabledAPIView(APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [MobileApiEnabledPermission, MobileAuthenticatedPermission, MobileScopePermission]
    required_scopes: set[str] = set()

    def _org(self):
        org = self.request.user.organization
        if org is None:
            raise Http404
        return org


def _mobile_datetime(value) -> str | None:
    if value is None:
        return None
    dt = value
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    dt = dt.astimezone(dt_timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def _normalize_payload_summary(payload: Any) -> Any:
    """Normalize nested datetime strings for strict iOS ISO-8601 decoders."""
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str) and key in {"due_at", "updated_at", "created_at", "occurred_at", "deleted_at"}:
                parsed = parse_datetime(value)
                normalized[key] = _mobile_datetime(parsed) if parsed is not None else value
            else:
                normalized[key] = _normalize_payload_summary(value)
        return normalized
    if isinstance(payload, list):
        return [_normalize_payload_summary(item) for item in payload]
    return payload


def _task_is_completed(status_value: Any) -> bool:
    return str(status_value) in {Task.Status.DONE, Task.Status.ARCHIVED}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _coerce_mobile_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = parse_datetime(value)
        return _mobile_datetime(parsed) if parsed is not None else value
    return _mobile_datetime(value)


def _mobile_event_type(event_type: str) -> str:
    mapping = {
        TaskChangeEvent.EventType.CREATED: "task.created",
        TaskChangeEvent.EventType.UPDATED: "task.updated",
        TaskChangeEvent.EventType.DELETED: "task.deleted",
        TaskChangeEvent.EventType.ARCHIVED: "task.deleted",
    }
    return mapping.get(str(event_type), "task.updated")


def _mobile_payload_summary(event: TaskChangeEvent, task: Task | None) -> dict[str, Any]:
    raw = event.payload_summary if isinstance(event.payload_summary, dict) else {}

    title = raw.get("title")
    if title is None and task is not None:
        title = task.title

    is_completed = raw.get("is_completed")
    if is_completed is None and raw.get("status") is not None:
        is_completed = _task_is_completed(raw.get("status"))
    if is_completed is None and task is not None:
        is_completed = _task_is_completed(task.status)
    if is_completed is None:
        is_completed = event.event_type in {TaskChangeEvent.EventType.DELETED, TaskChangeEvent.EventType.ARCHIVED}

    due_at = raw.get("due_at")
    if due_at is None and task is not None:
        due_at = task.due_at

    updated_at = raw.get("updated_at")
    if updated_at is None and task is not None:
        updated_at = task.updated_at
    if updated_at is None:
        updated_at = event.occurred_at

    summary: dict[str, Any] = {
        "title": str(title or ""),
        "is_completed": _coerce_bool(is_completed, default=False),
        "due_at": _coerce_mobile_datetime(due_at),
        "updated_at": _coerce_mobile_datetime(updated_at),
    }
    for key, value in raw.items():
        if key not in summary:
            summary[key] = value
    return _normalize_payload_summary(summary)


def _normalize_device_register_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "apns_device_token" in normalized:
        normalized.setdefault("apns_token", normalized["apns_device_token"])
        normalized.pop("apns_device_token", None)
    if "build_number" in normalized:
        normalized.setdefault("app_build", normalized["build_number"])
        normalized.pop("build_number", None)
    return normalized


def _required_scopes() -> list[str]:
    return ["openid", "offline_access", "mobile.read", "mobile.write", "mobile.sync", "mobile.notify"]


def _required_audience() -> str:
    return str(getattr(settings, "KEYCLOAK_REQUIRED_AUDIENCE", "taskhub-api")).strip()


def _allowed_public_hosts() -> set[str]:
    configured = getattr(settings, "KEYCLOAK_ALLOWED_PUBLIC_HOSTS", "")
    if isinstance(configured, (list, tuple, set)):
        return {str(piece).strip().lower() for piece in configured if str(piece).strip()}
    raw = str(configured).strip()
    return {piece.strip().lower() for piece in raw.split(",") if piece.strip()}


def _base_public_url(request) -> str:
    configured = str(getattr(settings, "KEYCLOAK_PUBLIC_BASE_URL", "")).strip().rstrip("/")
    if configured:
        return configured

    host = request.get_host().lower()
    allowed = _allowed_public_hosts()
    if allowed and host not in allowed:
        raise serializers.ValidationError("host is not in KEYCLOAK_ALLOWED_PUBLIC_HOSTS")
    return f"{request.scheme}://{host}".rstrip("/")


class MobileMetaView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    def get(self, request):
        base_url = _base_public_url(request)
        discovery_url = (
            f"{base_url}/idp/realms/{getattr(settings, 'KEYCLOAK_REALM', 'taskhub')}/"
            ".well-known/openid-configuration"
        )
        payload = {
            "api_version": "1",
            "oidc_discovery_url": discovery_url,
            "oidc_client_id": str(getattr(settings, "KEYCLOAK_IOS_CLIENT_ID", "taskhub-mobile")),
            "required_scopes": _required_scopes(),
            "required_audience": _required_audience(),
            "sync": {
                "max_page_size": int(getattr(settings, "MOBILE_SYNC_MAX_PAGE_SIZE", 500)),
                "event_retention_days": int(getattr(settings, "MOBILE_EVENT_RETENTION_DAYS", 30)),
            },
        }
        serializer = MobileMetaSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class MobileSessionView(MobileEnabledAPIView):
    required_scopes = {"mobile.read"}
    throttle_classes = [MobileAuthRateThrottle]

    def get(self, request):
        payload = {
            "user_id": str(request.user.id),
            "organization_id": str(request.user.organization_id) if request.user.organization_id else None,
            "role": request.user.role,
            "email": request.user.email,
            "display_name": request.user.display_name or "",
        }
        serializer = SessionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class MobileTaskListCreateView(MobileEnabledAPIView):
    required_scopes_by_method = {
        "GET": {"mobile.read"},
        "POST": {"mobile.write"},
    }

    def get(self, request):
        queryset = Task.objects.filter(organization=self._org()).order_by("position", "-created_at")
        limit_raw = request.query_params.get("limit")
        if limit_raw:
            try:
                limit = max(1, min(int(limit_raw), int(getattr(settings, "MOBILE_SYNC_MAX_PAGE_SIZE", 500))))
                queryset = queryset[:limit]
            except ValueError:
                pass
        serializer = MobileTaskSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        body = dict(request.data)
        body.setdefault("area", Task.Area.PERSONAL)

        def action() -> Response:
            serializer = TaskSerializer(data=body, context={"request": request})
            serializer.is_valid(raise_exception=True)
            task = serializer.save()
            return Response(MobileTaskSerializer(task).data, status=status.HTTP_201_CREATED)

        # Backward compatibility: older mobile clients may omit Idempotency-Key.
        if not str(request.headers.get("Idempotency-Key") or "").strip():
            return action()
        return with_idempotency(request, endpoint="POST:/api/mobile/v1/tasks", action=action)


class MobileTaskDetailView(MobileEnabledAPIView):
    required_scopes_by_method = {
        "GET": {"mobile.read"},
        "PATCH": {"mobile.write"},
        "DELETE": {"mobile.write"},
    }

    def _task(self, task_id):
        return get_object_or_404(Task, id=task_id, organization=self._org())

    def get(self, request, task_id):
        task = self._task(task_id)
        serializer = MobileTaskSerializer(task)
        return Response(serializer.data)

    def patch(self, request, task_id):
        task = self._task(task_id)
        serializer = TaskSerializer(task, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response(MobileTaskSerializer(task).data)

    def delete(self, request, task_id):
        task = self._task(task_id)
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MobileDeltaSyncView(MobileEnabledAPIView):
    required_scopes = {"mobile.sync"}
    throttle_classes = [MobileSyncRateThrottle]

    def get(self, request):
        org = self._org()
        cursor_token = str(request.query_params.get("cursor") or "").strip()
        try:
            cursor_id = decode_cursor(cursor_token)
        except serializers.ValidationError:
            return Response(
                {
                    "error": {
                        "code": "cursor_expired",
                        "message": "invalid or expired cursor, perform full resync",
                        "details": {},
                    },
                    "request_id": request_id_from_headers(request.headers),
                },
                status=status.HTTP_410_GONE,
            )

        limit_default = 100
        limit_cap = int(getattr(settings, "MOBILE_SYNC_MAX_PAGE_SIZE", 500))
        try:
            limit = int(request.query_params.get("limit") or limit_default)
        except ValueError:
            limit = limit_default
        limit = max(1, min(limit, limit_cap))

        events_qs = TaskChangeEvent.objects.filter(organization=org).order_by("id")
        oldest = events_qs.first()
        if cursor_id and oldest and cursor_id < (oldest.id - 1):
            return Response(
                {
                    "error": {
                        "code": "cursor_expired",
                        "message": "cursor expired, perform full resync",
                        "details": {"oldest_cursor": encode_cursor(oldest.id)},
                    },
                    "request_id": request_id_from_headers(request.headers),
                },
                status=status.HTTP_410_GONE,
            )

        events = list(events_qs.filter(id__gt=cursor_id)[:limit])
        task_ids = [event.task_id for event in events if event.task_id is not None]
        tasks_by_id = {
            task.id: task
            for task in Task.objects.filter(organization=org, id__in=task_ids).only(
                "id",
                "title",
                "status",
                "due_at",
                "updated_at",
            )
        }
        next_cursor = encode_cursor(events[-1].id if events else cursor_id)
        payload_events: list[dict[str, Any]] = []
        for event in events:
            mobile_event_type = _mobile_event_type(event.event_type)
            payload_events.append(
                {
                    "cursor": encode_cursor(event.id),
                    "event_type": mobile_event_type,
                    "task_id": str(event.task_id) if event.task_id else None,
                    "payload_summary": _mobile_payload_summary(event, tasks_by_id.get(event.task_id)),
                    "occurred_at": _mobile_datetime(event.occurred_at),
                    "tombstone": mobile_event_type == "task.deleted",
                }
            )

        return Response({"events": payload_events, "next_cursor": next_cursor})


class MePreferenceView(MobileEnabledAPIView):
    required_scopes_by_method = {
        "GET": {"mobile.read"},
        "PATCH": {"mobile.write"},
    }

    def get(self, request):
        pref, _ = UserMobilePreference.objects.get_or_create(
            user=request.user,
            organization=request.user.organization,
        )
        serializer = UserMobilePreferenceSerializer(pref)
        return Response(serializer.data)

    def patch(self, request):
        pref, _ = UserMobilePreference.objects.get_or_create(
            user=request.user,
            organization=request.user.organization,
        )
        serializer = UserMobilePreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class NotificationPreferenceView(MobileEnabledAPIView):
    required_scopes = {"mobile.notify"}

    def get(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(
            user=request.user,
            organization=request.user.organization,
        )
        serializer = NotificationPreferenceSerializer(pref)
        return Response(serializer.data)

    def patch(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(
            user=request.user,
            organization=request.user.organization,
        )
        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MobileDeviceRegisterView(MobileEnabledAPIView):
    required_scopes = {"mobile.notify"}

    def post(self, request):
        # Compatibility contract for Xcode sample payload:
        # {token, platform, app_version}
        payload = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        if "token" in payload or "platform" in payload:
            compatibility = XcodeDeviceRegisterSerializer(data=payload)
            compatibility.is_valid(raise_exception=True)
            payload = compatibility.as_mobile_device_payload()
        else:
            payload = _normalize_device_register_payload(payload)

        serializer = MobileDeviceSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        return Response(MobileDeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class MobileDeviceUnregisterView(MobileEnabledAPIView):
    required_scopes = {"mobile.notify"}

    def post(self, request):
        serializer = XcodeDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        expected_env = (
            MobileDevice.APNsEnvironment.SANDBOX
            if bool(getattr(settings, "APNS_USE_SANDBOX", True))
            else MobileDevice.APNsEnvironment.PRODUCTION
        )
        token_hash = MobileDevice.hash_apns_token(serializer.validated_data["token"])
        deleted_count, _ = MobileDevice.objects.filter(
            user=request.user,
            organization=self._org(),
            apns_token_hash=token_hash,
            apns_environment=expected_env,
        ).delete()
        return Response({"unregistered": True, "deleted": deleted_count > 0})


class MobileDeviceDetailView(MobileEnabledAPIView):
    required_scopes = {"mobile.notify"}

    def _device(self, device_id):
        return get_object_or_404(MobileDevice, id=device_id, user=self.request.user, organization=self._org())

    def patch(self, request, device_id):
        device = self._device(device_id)
        serializer = MobileDeviceSerializer(device, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MobileDeviceSerializer(device).data)

    def delete(self, request, device_id):
        device = self._device(device_id)
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IntentCreateTaskView(MobileEnabledAPIView):
    required_scopes = {"mobile.write"}
    throttle_classes = [MobileIntentRateThrottle]

    def post(self, request):
        body = dict(request.data)
        body.setdefault("area", Task.Area.PERSONAL)

        def action() -> Response:
            serializer = TaskSerializer(data=body, context={"request": request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        if not str(request.headers.get("Idempotency-Key") or "").strip():
            return action()
        return with_idempotency(request, endpoint="POST:/api/mobile/v1/intents/create-task", action=action)


class WidgetSnapshotView(MobileEnabledAPIView):
    required_scopes = {"mobile.read"}

    def get(self, request):
        queryset = (
            Task.objects.filter(organization=self._org())
            .exclude(status=Task.Status.ARCHIVED)
            .order_by("due_at", "position", "-updated_at")[:20]
        )
        serializer = WidgetTaskSerializer(queryset, many=True)
        return Response(
            {
                "generated_at": _mobile_datetime(timezone.now()),
                "tasks": serializer.data,
            }
        )


class MobileIdentityLinkListCreateView(MobileEnabledAPIView):
    required_scopes = {"mobile.read", "mobile.write"}

    def _require_admin(self):
        if self.request.user.role not in {User.Role.OWNER, User.Role.ADMIN}:
            raise Http404

    def post(self, request):
        self._require_admin()
        serializer = OIDCIdentitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user = serializer.validated_data["user"]
        if target_user.organization_id != request.user.organization_id:
            raise Http404

        identity, created = OIDCIdentity.objects.update_or_create(
            issuer=serializer.validated_data["issuer"],
            subject=serializer.validated_data["subject"],
            defaults={"user": target_user},
        )
        OIDCIdentityAudit.objects.create(
            actor=request.user,
            action=OIDCIdentityAudit.Action.LINK,
            issuer=identity.issuer,
            subject=identity.subject,
            user=identity.user,
            metadata={"created": created},
        )
        return Response(OIDCIdentitySerializer(identity).data, status=status.HTTP_201_CREATED if created else 200)


class MobileIdentityLinkDetailView(MobileEnabledAPIView):
    required_scopes = {"mobile.write"}

    def _require_admin(self):
        if self.request.user.role not in {User.Role.OWNER, User.Role.ADMIN}:
            raise Http404

    def delete(self, request, link_id):
        self._require_admin()
        identity = get_object_or_404(OIDCIdentity.objects.select_related("user"), id=link_id)
        if identity.user.organization_id != request.user.organization_id:
            raise Http404

        OIDCIdentityAudit.objects.create(
            actor=request.user,
            action=OIDCIdentityAudit.Action.UNLINK,
            issuer=identity.issuer,
            subject=identity.subject,
            user=identity.user,
            metadata={"identity_id": str(identity.id)},
        )
        identity.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
