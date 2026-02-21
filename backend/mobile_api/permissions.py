from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission

from mobile_api.exceptions import InsufficientScope


class MobileApiEnabledPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(getattr(settings, "MOBILE_API_ENABLED", False))


class MobileAuthenticatedPermission(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        raise NotAuthenticated()


class MobileScopePermission(BasePermission):
    def has_permission(self, request, view):
        scoped_by_method = getattr(view, "required_scopes_by_method", None)
        if isinstance(scoped_by_method, dict):
            required_scopes = set(scoped_by_method.get(request.method, set()) or [])
        else:
            required_scopes = set(getattr(view, "required_scopes", []) or [])
        if not required_scopes:
            return True
        if not getattr(settings, "KEYCLOAK_AUTH_ENABLED", False):
            return True

        payload = request.auth if isinstance(request.auth, dict) else {}
        scope_set = set(payload.get("_scope_set") or [])
        if required_scopes.issubset(scope_set):
            return True

        raise InsufficientScope()
