from __future__ import annotations

from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from mobile_api.models import (
    MobileDevice,
    NotificationPreference,
    OIDCIdentity,
    UserMobilePreference,
)
from tasks.models import Task
from tasks.serializers import TaskSerializer


class MobileDateTimeField(serializers.DateTimeField):
    """Stable RFC3339 timestamps for iOS JSONDecoder.iso8601 compatibility."""

    def to_representation(self, value):
        if value is None:
            return None
        dt = value
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, dt_timezone.utc)
        dt = dt.astimezone(dt_timezone.utc).replace(microsecond=0)
        return dt.isoformat().replace("+00:00", "Z")


class MobileMetaSerializer(serializers.Serializer):
    api_version = serializers.CharField()
    oidc_discovery_url = serializers.URLField()
    oidc_client_id = serializers.CharField()
    required_scopes = serializers.ListField(child=serializers.CharField())
    required_audience = serializers.CharField()
    sync = serializers.DictField()


class SessionSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    organization_id = serializers.CharField(allow_null=True)
    role = serializers.CharField()
    email = serializers.EmailField()
    display_name = serializers.CharField(allow_blank=True)


class OIDCIdentitySerializer(serializers.ModelSerializer):
    class Meta:
        model = OIDCIdentity
        fields = ["id", "issuer", "subject", "user", "created_at", "last_seen_at"]
        read_only_fields = ["id", "created_at", "last_seen_at"]


class UserMobilePreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMobilePreference
        fields = [
            "default_task_sort",
            "show_completed_default",
            "start_of_week",
            "widget_show_due_only",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "timezone",
            "quiet_hours_start",
            "quiet_hours_end",
            "reminders_enabled",
            "due_soon_offset_minutes",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def validate_timezone(self, value: str):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("timezone must be a valid IANA timezone") from exc
        return value


class MobileDeviceSerializer(serializers.ModelSerializer):
    apns_token = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = MobileDevice
        fields = [
            "id",
            "apns_token",
            "apns_environment",
            "device_installation_id",
            "app_version",
            "app_build",
            "app_bundle_id",
            "ios_version",
            "timezone",
            "last_seen_at",
            "created_at",
        ]
        read_only_fields = ["id", "last_seen_at", "created_at"]

    def validate(self, attrs):
        env = attrs.get("apns_environment") or getattr(self.instance, "apns_environment", None)
        expected_sandbox = bool(getattr(settings, "APNS_USE_SANDBOX", True))
        if env is not None:
            if expected_sandbox and env != MobileDevice.APNsEnvironment.SANDBOX:
                raise serializers.ValidationError({"apns_environment": "must be sandbox in current deployment"})
            if not expected_sandbox and env != MobileDevice.APNsEnvironment.PRODUCTION:
                raise serializers.ValidationError({"apns_environment": "must be production in current deployment"})
        configured_bundle = str(getattr(settings, "APNS_BUNDLE_ID", "")).strip()
        request_bundle = str(attrs.get("app_bundle_id") or getattr(self.instance, "app_bundle_id", "")).strip()
        if configured_bundle and request_bundle and request_bundle != configured_bundle:
            raise serializers.ValidationError({"app_bundle_id": "must match APNS_BUNDLE_ID"})
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        raw_token = validated_data.pop("apns_token", "")
        if not raw_token:
            raise serializers.ValidationError({"apns_token": "apns_token is required"})

        token_hash = MobileDevice.hash_apns_token(raw_token)
        installation_id = validated_data.get("device_installation_id")
        apns_environment = validated_data.get("apns_environment")

        queryset = MobileDevice.objects.filter(user=request.user, organization=request.user.organization)
        device = None
        if installation_id:
            device = queryset.filter(device_installation_id=installation_id).first()
        if device is None:
            device = queryset.filter(apns_token_hash=token_hash, apns_environment=apns_environment).first()

        if device is None:
            device = MobileDevice(user=request.user, organization=request.user.organization)

        for key, value in validated_data.items():
            setattr(device, key, value)
        device.set_apns_token(raw_token)
        device.save()
        return device

    def update(self, instance, validated_data):
        raw_token = validated_data.pop("apns_token", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if raw_token:
            instance.set_apns_token(raw_token)
        instance.save()
        return instance


class XcodeDeviceRegisterSerializer(serializers.Serializer):
    token = serializers.CharField()
    platform = serializers.CharField()
    app_version = serializers.CharField()

    def validate_platform(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized != "ios":
            raise serializers.ValidationError("platform must be ios")
        return normalized

    def as_mobile_device_payload(self) -> dict[str, str]:
        expected_env = (
            MobileDevice.APNsEnvironment.SANDBOX
            if bool(getattr(settings, "APNS_USE_SANDBOX", True))
            else MobileDevice.APNsEnvironment.PRODUCTION
        )
        return {
            "apns_token": self.validated_data["token"],
            "apns_environment": expected_env,
            "app_version": self.validated_data["app_version"],
        }


class XcodeDeviceUnregisterSerializer(serializers.Serializer):
    token = serializers.CharField()
    platform = serializers.CharField()

    def validate_platform(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized != "ios":
            raise serializers.ValidationError("platform must be ios")
        return normalized


class MobileTaskCreateSerializer(TaskSerializer):
    class Meta(TaskSerializer.Meta):
        model = Task


class MobileTaskSerializer(serializers.ModelSerializer):
    is_completed = serializers.SerializerMethodField()
    project = serializers.UUIDField(source="project_id", allow_null=True, read_only=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    due_at = MobileDateTimeField(allow_null=True, required=False)
    updated_at = MobileDateTimeField()

    class Meta:
        model = Task
        fields = ["id", "title", "is_completed", "due_at", "updated_at", "project", "project_name"]

    def get_is_completed(self, instance: Task) -> bool:
        return instance.status in {Task.Status.DONE, Task.Status.ARCHIVED}


class MobileTaskDetailSerializer(serializers.ModelSerializer):
    is_completed = serializers.SerializerMethodField()
    project = serializers.UUIDField(source="project_id", allow_null=True, read_only=True)
    project_name = serializers.CharField(source="project.name", allow_null=True, read_only=True)
    due_at = MobileDateTimeField(allow_null=True, required=False)
    completed_at = MobileDateTimeField(allow_null=True, required=False)
    created_at = MobileDateTimeField()
    updated_at = MobileDateTimeField()

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "notes",
            "attachments",
            "intent",
            "area",
            "project",
            "project_name",
            "status",
            "priority",
            "due_at",
            "recurrence",
            "completed_at",
            "position",
            "created_at",
            "updated_at",
            "is_completed",
        ]

    def get_is_completed(self, instance: Task) -> bool:
        return instance.status in {Task.Status.DONE, Task.Status.ARCHIVED}


class WidgetTaskSerializer(serializers.ModelSerializer):
    due_at = MobileDateTimeField(allow_null=True, required=False)
    updated_at = MobileDateTimeField()

    class Meta:
        model = Task
        fields = ["id", "title", "status", "due_at", "priority", "area", "updated_at"]
