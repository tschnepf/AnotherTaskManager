import uuid

from django.db import models

from core.models import Organization, User


class SavedView(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="views")
    name = models.CharField(max_length=255)
    filter_json = models.JSONField(default=dict)
    sort_field = models.CharField(max_length=64)
    sort_order = models.CharField(max_length=8)
    is_shared = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_views")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "view"
