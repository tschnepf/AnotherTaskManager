import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class Organization(models.Model):
    class InboundEmailProvider(models.TextChoices):
        WEBHOOK = "webhook", "Webhook"
        GMAIL_OAUTH = "gmail_oauth", "Gmail OAuth"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    allow_cloud_ai = models.BooleanField(default=False)
    redact_sensitive_patterns = models.BooleanField(default=False)
    inbound_email_address = models.EmailField(unique=True, null=True, blank=True)
    inbound_email_token = models.CharField(max_length=128, blank=True)
    inbound_email_whitelist = models.JSONField(default=list, blank=True)
    inbound_email_provider = models.CharField(
        max_length=32,
        choices=InboundEmailProvider.choices,
        default=InboundEmailProvider.WEBHOOK,
    )
    gmail_oauth_email = models.EmailField(blank=True)
    gmail_oauth_refresh_token = models.TextField(blank=True)
    imap_username = models.CharField(max_length=320, blank=True)
    imap_password = models.TextField(blank=True)
    imap_host = models.CharField(max_length=255, blank=True)
    imap_provider = models.CharField(max_length=64, blank=True, default="auto")
    imap_port = models.PositiveIntegerField(default=993)
    imap_use_ssl = models.BooleanField(default=True)
    imap_folder = models.CharField(max_length=255, default="INBOX")
    imap_search_criteria = models.CharField(max_length=255, default="UNSEEN")
    imap_mark_seen_on_success = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    username = None
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email
