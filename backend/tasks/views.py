from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from django.db.models import Case, IntegerField, Max, Q, Value, When
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ai.semantic import dedupe_candidates, semantic_search_with_fallback
from tasks.models import Project, Tag, Task
from tasks.serializers import ProjectSerializer, TagSerializer, TaskSerializer
from tasks.transitions import is_valid_transition


class OrgScopedQuerysetMixin:
    def _org(self):
        return self.request.user.organization


class TaskViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Task.objects.filter(organization=user.organization).order_by("position", "-created_at")
        include_history = self.request.query_params.get("include_history") == "true"
        if getattr(self, "action", None) == "list" and not include_history:
            done_cutoff = timezone.now() - timedelta(days=1)
            qs = qs.exclude(
                Q(status=Task.Status.DONE) & (Q(completed_at__lt=done_cutoff) | Q(completed_at__isnull=True))
            )
            qs = qs.exclude(status=Task.Status.ARCHIVED)

        status_value = self.request.query_params.get("status")
        area = self.request.query_params.get("area")
        project_id = self.request.query_params.get("project_id")
        tag = self.request.query_params.get("tag")
        priority_min = self.request.query_params.get("priority_min")
        priority_max = self.request.query_params.get("priority_max")
        due_before = self.request.query_params.get("due_before")
        due_after = self.request.query_params.get("due_after")
        q = self.request.query_params.get("q")

        if status_value:
            qs = qs.filter(status=status_value)
        if area:
            qs = qs.filter(area=area)
        if project_id:
            qs = qs.filter(project_id=project_id)
        if tag:
            qs = qs.filter(tags__name__iexact=tag)
        if priority_min:
            qs = qs.filter(priority__gte=priority_min)
        if priority_max:
            qs = qs.filter(priority__lte=priority_max)
        if due_before:
            qs = qs.filter(due_at__lte=due_before)
        if due_after:
            qs = qs.filter(due_at__gte=due_after)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        sort_mode = self.request.query_params.get("sort_mode")
        if sort_mode == "priority_manual":
            qs = qs.annotate(
                priority_group=Case(
                    When(priority__gte=4, then=Value(0)),
                    When(priority__gte=2, then=Value(1)),
                    When(priority__gte=1, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            ).order_by("priority_group", "position")
        else:
            sort = self.request.query_params.get("sort", "created_at")
            order = self.request.query_params.get("order", "desc")
            allowlist = {"created_at", "updated_at", "due_at", "priority", "title", "status", "position"}
            if sort in allowlist:
                qs = qs.order_by(f"{'-' if order == 'desc' else ''}{sort}")

        return qs.distinct()

    def list(self, request, *args, **kwargs):
        semantic_requested = request.query_params.get("semantic") == "true"
        q = request.query_params.get("q")
        if semantic_requested and not q:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "semantic=true requires q",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.get_queryset()
        if q:
            queryset, semantic_used, fallback_reason = semantic_search_with_fallback(
                queryset, q, semantic_requested
            )
        else:
            semantic_used = False
            fallback_reason = None
        page = int(request.query_params.get("page", 1))
        page_size = min(int(request.query_params.get("page_size", 25)), 100)
        start = (page - 1) * page_size
        end = start + page_size

        total = queryset.count()
        serializer = self.get_serializer(queryset[start:end], many=True)
        return Response(
            {
                "results": serializer.data,
                "page": page,
                "page_size": page_size,
                "total": total,
                "semantic_requested": semantic_requested,
                "semantic_used": semantic_used,
                "fallback_reason": fallback_reason,
            }
        )

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if response.status_code != status.HTTP_201_CREATED:
            return response

        title = response.data.get("title", "")
        candidates = Task.objects.filter(organization=request.user.organization).exclude(
            id=response.data.get("id")
        )[:25]
        response.data["duplicate_candidates"] = dedupe_candidates(title, list(candidates))
        return response

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        new_status = request.data.get("status")
        if new_status and not is_valid_transition(instance.status, new_status):
            return Response(
                {
                    "error_code": "invalid_transition",
                    "message": "Invalid state transition",
                    "details": {"from": instance.status, "to": new_status},
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        if not is_valid_transition(task.status, Task.Status.DONE):
            return Response({"error_code": "invalid_transition"}, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(task, data={"status": Task.Status.DONE}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        task = self.get_object()
        target = Task.Status.NEXT
        if not is_valid_transition(task.status, target):
            return Response({"error_code": "invalid_transition"}, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(task, data={"status": target}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def reorder(self, request, pk=None):
        task = self.get_object()
        target_task_id = request.data.get("target_task_id")
        placement = request.data.get("placement", "after")

        if not target_task_id:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "target_task_id is required",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if placement not in {"before", "after"}:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "placement must be before or after",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_task = Task.objects.get(id=target_task_id, organization=task.organization)
        except Task.DoesNotExist:
            return Response(
                {
                    "error_code": "not_found",
                    "message": "target task not found",
                    "details": {},
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if task.id == target_task.id:
            return Response(self.get_serializer(task).data)

        with transaction.atomic():
            ordered_ids = list(
                Task.objects.select_for_update()
                .filter(organization=task.organization)
                .order_by("position", "created_at", "id")
                .values_list("id", flat=True)
            )
            if task.id not in ordered_ids or target_task.id not in ordered_ids:
                return Response(
                    {
                        "error_code": "not_found",
                        "message": "task not found in ordering set",
                        "details": {},
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            ordered_ids.remove(task.id)
            target_index = ordered_ids.index(target_task.id)
            insert_index = target_index if placement == "before" else target_index + 1
            ordered_ids.insert(insert_index, task.id)

            updates = [Task(id=task_id, position=index) for index, task_id in enumerate(ordered_ids, start=1)]
            Task.objects.bulk_update(updates, ["position"])

        task.refresh_from_db()
        return Response(self.get_serializer(task).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="attachments/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_attachment(self, request, pk=None):
        task = self.get_object()
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "file is required",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_upload_size_bytes = 20 * 1024 * 1024
        if uploaded_file.size > max_upload_size_bytes:
            return Response(
                {
                    "error_code": "validation_error",
                    "message": "file exceeds 20MB limit",
                    "details": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        original_name = (uploaded_file.name or "").strip() or "attachment"
        safe_name = get_valid_filename(original_name)
        unique_folder = uuid4().hex
        relative_path = f"tasks/{task.organization_id}/{task.id}/{unique_folder}/{safe_name}"
        saved_path = default_storage.save(relative_path, uploaded_file)
        file_url = default_storage.url(saved_path)

        attachments = task.attachments or []
        attachments.append(
            {
                "name": original_name,
                "url": file_url,
            }
        )
        task.attachments = attachments
        task.save(update_fields=["attachments", "updated_at"])

        return Response(
            {
                "attachments": attachments,
            },
            status=status.HTTP_201_CREATED,
        )


class ProjectViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        queryset = Project.objects.filter(organization=self._org())
        area = self.request.query_params.get("area")
        q = (self.request.query_params.get("q") or "").strip()
        limit_value = self.request.query_params.get("limit")

        if area:
            queryset = queryset.filter(area=area)
        if q:
            queryset = queryset.filter(name__icontains=q)

        queryset = queryset.order_by("name")
        if limit_value:
            try:
                limit = max(1, min(int(limit_value), 100))
                queryset = queryset[:limit]
            except ValueError:
                pass
        return queryset

    def perform_create(self, serializer):
        serializer.save(organization=self._org())


class TagViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        return Tag.objects.filter(organization=self._org()).order_by("name")

    def perform_create(self, serializer):
        serializer.save(organization=self._org())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bookmarklet_capture_view(request):
    title = (request.data.get("title") or "").strip()
    if not title:
        return Response(
            {"error_code": "validation_error", "message": "title is required", "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    area = request.data.get("area") or Task.Area.WORK
    source_link = request.data.get("url") or request.data.get("source_link") or ""
    source_snippet = request.data.get("snippet") or request.data.get("source_snippet") or ""

    next_position = (
        Task.objects.filter(organization=request.user.organization).aggregate(max_position=Max("position"))[
            "max_position"
        ]
        or 0
    ) + 1
    task = Task.objects.create(
        organization=request.user.organization,
        created_by_user=request.user,
        position=next_position,
        title=title,
        area=area,
        status=Task.Status.INBOX,
        source_type=Task.SourceType.OTHER,
        source_link=source_link,
        source_snippet=source_snippet,
    )

    serializer = TaskSerializer(task)
    return Response(serializer.data, status=status.HTTP_201_CREATED)
