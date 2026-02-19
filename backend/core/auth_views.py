from django.conf import settings
from django.http import Http404
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from core.serializers import CustomTokenObtainPairSerializer, RegisterSerializer


@method_decorator(csrf_protect, name="dispatch")
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        access = str(data.pop("access", "")).strip()
        refresh = str(data.pop("refresh", "")).strip()
        response = Response(
            {
                "user_id": data.get("user_id"),
                "organization_id": data.get("organization_id"),
                "role": data.get("role"),
            },
            status=status.HTTP_200_OK,
        )
        _set_auth_cookies(response, access_token=access, refresh_token=refresh)
        return response


class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_value = str(request.data.get("refresh") or request.COOKIES.get(settings.AUTH_COOKIE_REFRESH_NAME) or "").strip()
        if not refresh_value:
            return Response(
                {"detail": "No refresh token available"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.get_serializer(data={"refresh": refresh_value})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        access = str(data.get("access") or "").strip()
        rotated_refresh = str(data.get("refresh") or "").strip()

        response = Response({"status": "refreshed"}, status=status.HTTP_200_OK)
        _set_auth_cookies(
            response,
            access_token=access,
            refresh_token=rotated_refresh or None,
        )
        return response

    def get_serializer(self, *args, **kwargs):
        from rest_framework_simplejwt.serializers import TokenRefreshSerializer

        return TokenRefreshSerializer(*args, **kwargs)


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def register_view(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    return Response(
        {
            "id": str(user.id),
            "email": user.email,
            "organization_id": str(user.organization_id),
            "role": user.role,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    refresh = str(request.data.get("refresh") or request.COOKIES.get(settings.AUTH_COOKIE_REFRESH_NAME) or "").strip()
    if refresh:
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except Exception:
            pass
    response = Response({"status": "logged_out"}, status=status.HTTP_200_OK)
    _clear_auth_cookies(response)
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_session_view(request):
    return Response(
        {
            "user_id": str(request.user.id),
            "organization_id": str(request.user.organization_id) if request.user.organization_id else None,
            "role": request.user.role,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_cookie_view(request):
    return Response({"csrfToken": get_token(request)}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tenant_check_view(request, organization_id):
    if request.user.organization_id != organization_id:
        raise Http404

    return Response({"ok": True, "organization_id": str(organization_id)}, status=status.HTTP_200_OK)


def _set_auth_cookies(response: Response, *, access_token: str, refresh_token: str | None = None):
    if access_token:
        response.set_cookie(
            settings.AUTH_COOKIE_ACCESS_NAME,
            access_token,
            max_age=int(jwt_api_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path=settings.AUTH_COOKIE_ACCESS_PATH,
        )

    if refresh_token:
        response.set_cookie(
            settings.AUTH_COOKIE_REFRESH_NAME,
            refresh_token,
            max_age=int(jwt_api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            domain=settings.AUTH_COOKIE_DOMAIN,
            path=settings.AUTH_COOKIE_REFRESH_PATH,
        )


def _clear_auth_cookies(response: Response):
    response.delete_cookie(
        settings.AUTH_COOKIE_ACCESS_NAME,
        path=settings.AUTH_COOKIE_ACCESS_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )
    response.delete_cookie(
        settings.AUTH_COOKIE_REFRESH_NAME,
        path=settings.AUTH_COOKIE_REFRESH_PATH,
        domain=settings.AUTH_COOKIE_DOMAIN,
    )
