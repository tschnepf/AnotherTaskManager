from rest_framework import serializers
from django.db.models import Max

from core.models import User
from tasks.attachments import (
    build_attachment_access_url,
    normalize_attachment_input,
    path_matches_org,
    path_matches_task,
)
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

        tags = attrs.get("tags")
        if tags is not None:
            invalid_tag = next((tag for tag in tags if tag.organization_id != org.id), None)
            if invalid_tag is not None:
                raise serializers.ValidationError("all tags must belong to the same organization")

        return attrs

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        tag_field = fields.get("tag_ids")
        if tag_field is not None:
            if request and getattr(request, "user", None) and request.user.is_authenticated:
                tag_field.queryset = Tag.objects.filter(organization=request.user.organization)
            else:
                tag_field.queryset = Tag.objects.none()
        return fields

    def validate_attachments(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("attachments must be a list")
        if len(value) > 25:
            raise serializers.ValidationError("attachments cannot contain more than 25 items")

        normalized = []
        request = self.context["request"]
        org_id = str(request.user.organization_id)
        task_id = str(self.instance.id) if self.instance is not None else ""
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("each attachment must be an object")
            try:
                normalized_item = normalize_attachment_input(item)
            except ValueError as exc:
                raise serializers.ValidationError(str(exc)) from exc

            name = str(normalized_item["name"] or "").strip()
            path = str(normalized_item["path"] or "").strip()
            if len(name) > 255:
                raise serializers.ValidationError("attachment name is too long")
            if len(path) > 4000:
                raise serializers.ValidationError("attachment path is too long")
            if not path_matches_org(path, org_id):
                raise serializers.ValidationError("attachment must belong to the same organization")
            if task_id and not path_matches_task(path, task_id):
                raise serializers.ValidationError("attachment must belong to the same task")
            normalized.append(
                {
                    "name": name or "Attachment",
                    "path": path,
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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        attachments = []
        for item in instance.attachments or []:
            if not isinstance(item, dict):
                continue
            try:
                normalized_item = normalize_attachment_input(item)
            except ValueError:
                continue
            normalized_name = str(normalized_item["name"] or "").strip() or "Attachment"
            normalized_path = str(normalized_item["path"] or "").strip()
            attachments.append(
                {
                    "name": normalized_name,
                    "path": normalized_path,
                    "url": build_attachment_access_url(normalized_path),
                }
            )
        data["attachments"] = attachments
        return data


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
