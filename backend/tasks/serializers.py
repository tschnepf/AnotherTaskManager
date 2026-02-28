from uuid import UUID

from django.db import IntegrityError, transaction
from rest_framework import serializers
from django.db.models import Max
from django.utils import timezone

from core.models import User
from tasks.attachments import (
    build_attachment_access_url,
    normalize_attachment_input,
    path_matches_org,
    path_matches_task,
)
from tasks.models import Project, Tag, Task
from tasks.recurrence import next_due_at_for_completion
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
            "recurrence",
            "completed_at",
            "source_type",
            "source_external_id",
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
            "source_external_id",
        ]

    def _project_name_from_payload(self) -> str | None:
        return getattr(self, "_project_name_from_input", None)

    def _set_project_name_from_payload(self, value: str | None) -> None:
        self._project_name_from_input = value

    def _is_uuid_string(self, value: str) -> bool:
        try:
            UUID(str(value))
            return True
        except (TypeError, ValueError):
            return False

    def to_internal_value(self, data):
        self._set_project_name_from_payload(None)
        mutable_data = data.copy() if hasattr(data, "copy") else dict(data)
        raw_project = mutable_data.get("project", serializers.empty)

        if isinstance(raw_project, str):
            normalized = raw_project.strip()
            if not normalized:
                mutable_data["project"] = None
            elif self._is_uuid_string(normalized):
                mutable_data["project"] = normalized
            else:
                if len(normalized) > 255:
                    raise serializers.ValidationError({"project": "project name is too long"})
                self._set_project_name_from_payload(normalized)
                mutable_data["project"] = None

        return super().to_internal_value(mutable_data)

    def _resolve_project_from_name(self, *, name: str | None, area: str | None) -> Project | None:
        if not name:
            return None
        request = self.context["request"]
        org = request.user.organization
        if org is None:
            raise serializers.ValidationError("user must belong to an organization")

        existing = Project.objects.filter(organization=org, name__iexact=name).first()
        if existing is not None:
            return existing

        project_area = area or Task.Area.WORK
        try:
            return Project.objects.create(
                organization=org,
                name=name,
                area=project_area,
            )
        except IntegrityError:
            existing = Project.objects.filter(organization=org, name__iexact=name).first()
            if existing is not None:
                return existing
            raise

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

        instance = self.instance
        if "recurrence" in attrs:
            recurrence = attrs.get("recurrence")
        else:
            recurrence = instance.recurrence if instance is not None else Task.Recurrence.NONE

        if "due_at" in attrs:
            due_at = attrs.get("due_at")
        else:
            due_at = instance.due_at if instance is not None else None

        if recurrence != Task.Recurrence.NONE and due_at is None:
            raise serializers.ValidationError({"due_at": "due_at is required for recurring tasks"})

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
        project_name = self._project_name_from_payload()
        if project_name:
            validated_data["project"] = self._resolve_project_from_name(
                name=project_name,
                area=validated_data.get("area"),
            )
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
        project_name = self._project_name_from_payload()
        if project_name:
            validated_data["project"] = self._resolve_project_from_name(
                name=project_name,
                area=validated_data.get("area") or instance.area,
            )
        old_status = instance.status
        status_changed_to_done = False
        for key, value in validated_data.items():
            setattr(instance, key, value)

        if "status" in validated_data:
            if validated_data["status"] == Task.Status.DONE and instance.completed_at is None:
                instance.completed_at = timezone.now()
                status_changed_to_done = old_status != Task.Status.DONE
            if old_status == Task.Status.DONE and validated_data["status"] != Task.Status.DONE:
                instance.completed_at = None

        with transaction.atomic():
            instance.save()
            if tags is not None:
                instance.tags.set(tags)
            if status_changed_to_done:
                self._create_next_recurring_task(instance)
        return instance

    def _create_next_recurring_task(self, instance):
        if instance.recurrence == Task.Recurrence.NONE or instance.due_at is None:
            return

        completed_at = instance.completed_at or timezone.now()
        next_due_at = next_due_at_for_completion(instance.due_at, instance.recurrence, completed_at)
        if next_due_at is None:
            return

        next_position = (
            Task.objects.filter(organization=instance.organization).aggregate(max_position=Max("position"))[
                "max_position"
            ]
            or 0
        ) + 1
        next_task = Task.objects.create(
            organization=instance.organization,
            created_by_user=instance.created_by_user,
            assigned_to_user=instance.assigned_to_user,
            title=instance.title,
            description=instance.description,
            notes=instance.notes,
            intent=instance.intent,
            area=instance.area,
            project=instance.project,
            status=Task.Status.INBOX,
            priority=instance.priority,
            due_at=next_due_at,
            recurrence=instance.recurrence,
            source_type=Task.SourceType.SELF,
            allow_cloud_processing=instance.allow_cloud_processing,
            position=next_position,
        )
        next_task.tags.set(instance.tags.all())

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
