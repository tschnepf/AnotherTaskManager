from rest_framework.permissions import BasePermission

from core.rbac import can_manage_org_resources


class IsOwnerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and can_manage_org_resources(user))
