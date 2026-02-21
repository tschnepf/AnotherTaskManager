from __future__ import annotations

import hashlib
import uuid

from django.db import models

from core.crypto import decrypt_secret, encrypt_secret
from core.models import Organization, User


class OIDCIdentity(models.Model):
    issuer = models.CharField(max_length=512)
    subject = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oidc_identities")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["issuer", "subject"], name="mobile_oidc_identity_issuer_subject_uniq"),
        ]


class OIDCIdentityAudit(models.Model):
    class Action(models.TextChoices):
        LINK = "link", "Link"
        UNLINK = "unlink", "Unlink"

    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="oidc_audits")
    action = models.CharField(max_length=16, choices=Action.choices)
    issuer = models.CharField(max_length=512)
    subject = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oidc_identity_audits")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class UserMobilePreference(models.Model):
    class StartOfWeek(models.TextChoices):
        MONDAY = "monday", "Monday"
        SUNDAY = "sunday", "Sunday"

    class TaskSort(models.TextChoices):
        POSITION = "position", "Position"
        DUE_AT = "due_at", "Due date"
        CREATED_AT = "created_at", "Created"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mobile_preference")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="mobile_preferences")
    default_task_sort = models.CharField(max_length=32, choices=TaskSort.choices, default=TaskSort.POSITION)
    show_completed_default = models.BooleanField(default=False)
    start_of_week = models.CharField(max_length=16, choices=StartOfWeek.choices, default=StartOfWeek.MONDAY)
    widget_show_due_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_preference")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="notification_preferences")
    timezone = models.CharField(max_length=64, default="UTC")
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    reminders_enabled = models.BooleanField(default=True)
    due_soon_offset_minutes = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MobileDevice(models.Model):
    class APNsEnvironment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="mobile_devices")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mobile_devices")
    apns_token_encrypted = models.TextField(blank=True)
    apns_token_hash = models.CharField(max_length=64)
    apns_environment = models.CharField(max_length=16, choices=APNsEnvironment.choices)
    device_installation_id = models.CharField(max_length=128, null=True, blank=True)
    app_version = models.CharField(max_length=64, blank=True)
    app_build = models.CharField(max_length=64, blank=True)
    app_bundle_id = models.CharField(max_length=255, blank=True)
    ios_version = models.CharField(max_length=64, blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["apns_token_hash", "apns_environment"],
                name="mobile_device_token_hash_environment_uniq",
            ),
            models.UniqueConstraint(
                fields=["device_installation_id"],
                condition=models.Q(device_installation_id__isnull=False),
                name="mobile_device_installation_id_uniq",
            ),
        ]

    @staticmethod
    def hash_apns_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def set_apns_token(self, raw_token: str) -> None:
        self.apns_token_encrypted = encrypt_secret(raw_token)
        self.apns_token_hash = self.hash_apns_token(raw_token)

    def get_apns_token(self) -> str:
        return decrypt_secret(self.apns_token_encrypted)


class NotificationDelivery(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="notification_deliveries")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_deliveries")
    device = models.ForeignKey(MobileDevice, null=True, blank=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    dedupe_key = models.CharField(max_length=255)
    attempts = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    available_at = models.DateTimeField(auto_now_add=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=128, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dedupe_key"], name="mobile_notification_dedupe_key_uniq"),
        ]
        indexes = [
            models.Index(fields=["state", "available_at"]),
            models.Index(fields=["locked_until"]),
        ]


class IdempotencyRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="idempotency_records")
    endpoint = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveIntegerField(default=200)
    response_body = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "endpoint", "idempotency_key"],
                name="mobile_idempotency_user_endpoint_key_uniq",
            )
        ]
        indexes = [models.Index(fields=["expires_at"]) ]
