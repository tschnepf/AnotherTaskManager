from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from collaboration.models import SavedView
from collaboration.serializers import SavedViewSerializer


class SavedViewViewSet(viewsets.ModelViewSet):
    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        return SavedView.objects.filter(organization=self.request.user.organization).order_by("name")

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization, created_by=self.request.user)
