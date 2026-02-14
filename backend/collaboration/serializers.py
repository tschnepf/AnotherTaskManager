from rest_framework import serializers

from collaboration.models import SavedView


class SavedViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedView
        fields = [
            "id",
            "organization",
            "name",
            "filter_json",
            "sort_field",
            "sort_order",
            "is_shared",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "organization", "created_by", "created_at"]
