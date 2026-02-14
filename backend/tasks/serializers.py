from rest_framework import serializers
from django.db.models import Max

from core.models import User
from tasks.models import Project, Tag, Task
from tasks.transitions import is_valid_transition


class TaskSerializer(serializers.ModelSerializer):
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        source="tags",
        queryset=Tag.objects.all(),
        required=False,
    )

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
            "status",
            "priority",
            "due_at",
            "completed_at",
            "source_type",
            "source_link",
            "source_snippet",
            "assigned_to_user",
            "created_by_user",
            "organization",
            "created_at",
            "updated_at",
            "tag_ids",
            "allow_cloud_processing",
            "position",
        ]
        read_only_fields = [
            "id",
            "created_by_user",
            "organization",
            "created_at",
            "updated_at",
            "completed_at",
            "position",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        org = user.organization
        if org is None:
            raise serializers.ValidationError("user must belong to an organization")

        project = attrs.get("project")
        if project and project.organization_id != org.id:
            raise serializers.ValidationError("project must belong to the same organization")

        assigned_to = attrs.get("assigned_to_user")
        if assigned_to and assigned_to.organization_id != org.id:
            raise serializers.ValidationError("assigned_to_user must belong to the same organization")

        if assigned_to and user.role == User.Role.MEMBER and assigned_to.id != user.id:
            raise serializers.ValidationError("member can only assign tasks to self")

        instance = self.instance
        if instance and "status" in attrs:
            new_status = attrs["status"]
            if not is_valid_transition(instance.status, new_status):
                raise serializers.ValidationError({"status": "invalid transition"})

        return attrs

    def validate_attachments(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("attachments must be a list")
        if len(value) > 25:
            raise serializers.ValidationError("attachments cannot contain more than 25 items")

        normalized = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("each attachment must be an object")
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if not url:
                raise serializers.ValidationError("attachment url is required")
            if len(url) > 4000:
                raise serializers.ValidationError("attachment url is too long")
            if len(name) > 255:
                raise serializers.ValidationError("attachment name is too long")
            normalized.append(
                {
                    "name": name or "Attachment",
                    "url": url,
                }
            )
        return normalized

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        user = self.context["request"].user
        next_position = (
            Task.objects.filter(organization=user.organization).aggregate(max_position=Max("position"))[
                "max_position"
            ]
            or 0
        ) + 1
        task = Task.objects.create(
            organization=user.organization,
            created_by_user=user,
            position=next_position,
            **validated_data,
        )
        if tags:
            task.tags.set(tags)
        return task

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        old_status = instance.status
        for key, value in validated_data.items():
            setattr(instance, key, value)

        if "status" in validated_data:
            if validated_data["status"] == Task.Status.DONE and instance.completed_at is None:
                from django.utils import timezone

                instance.completed_at = timezone.now()
            if old_status == Task.Status.DONE and validated_data["status"] != Task.Status.DONE:
                instance.completed_at = None

        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        return instance


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = "__all__"
        read_only_fields = ["id", "organization", "created_at"]


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = "__all__"
        read_only_fields = ["id", "organization", "created_at"]
