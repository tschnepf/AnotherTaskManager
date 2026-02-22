import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core import signing
from django.http import Http404
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
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

from core.oidc_identity import resolve_or_provision_identity
from core.oidc_urls import build_realm_url
from core.serializers import CustomTokenObtainPairSerializer, RegisterSerializer


_OIDC_FLOW_COOKIE = "taskhub_oidc_flow"
_OIDC_FLOW_SIGNING_SALT = "core.auth.oidc.flow"


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


def _web_oidc_enabled() -> bool:
    return bool(getattr(settings, "KEYCLOAK_WEB_AUTH_ENABLED", False))


def _oidc_issuer() -> str:
    realm = str(getattr(settings, "KEYCLOAK_REALM", "taskhub")).strip()
    public_base = str(getattr(settings, "KEYCLOAK_PUBLIC_BASE_URL", "")).strip()
    issuer = build_realm_url(public_base, realm)
    if not issuer:
        raise ValueError("KEYCLOAK_PUBLIC_BASE_URL is required for web OIDC")
    return issuer


def _oidc_web_client_id() -> str:
    explicit = str(getattr(settings, "KEYCLOAK_WEB_CLIENT_ID", "")).strip()
    if explicit:
        return explicit
    return str(getattr(settings, "KEYCLOAK_IOS_CLIENT_ID", "taskhub-mobile")).strip()


def _oidc_web_scopes() -> str:
    raw = str(getattr(settings, "KEYCLOAK_WEB_SCOPES", "openid profile email")).strip()
    scopes = [piece.strip() for piece in raw.split() if piece.strip()]
    if "openid" not in scopes:
        scopes.insert(0, "openid")
    return " ".join(scopes)


def _oidc_callback_uri(request) -> str:
    return request.build_absolute_uri(reverse("auth_oidc_callback"))


def _oidc_post_login_redirect() -> str:
    value = str(getattr(settings, "KEYCLOAK_WEB_POST_LOGIN_REDIRECT", "/")).strip() or "/"
    return value if value.startswith("/") else "/"


def _oidc_error_redirect(message: str):
    safe = message.strip() or "oidc_login_failed"
    return redirect(f"/login?error={safe}")


@api_view(["GET"])
@permission_classes([AllowAny])
def oidc_login_start_view(request):
    if not _web_oidc_enabled():
        raise Http404

    issuer = _oidc_issuer()
    client_id = _oidc_web_client_id()
    callback_uri = _oidc_callback_uri(request)
    next_path = str(request.query_params.get("next") or _oidc_post_login_redirect()).strip()
    if not next_path.startswith("/"):
        next_path = _oidc_post_login_redirect()

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest()).rstrip(b"=").decode(
        "ascii"
    )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback_uri,
        "scope": _oidc_web_scopes(),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    audience = str(getattr(settings, "KEYCLOAK_REQUIRED_AUDIENCE", "")).strip()
    if audience:
        params["audience"] = audience

    flow_payload = {
        "state": state,
        "nonce": nonce,
        "code_verifier": code_verifier,
        "next": next_path,
    }
    flow_cookie = signing.dumps(flow_payload, salt=_OIDC_FLOW_SIGNING_SALT)

    response = redirect(f"{issuer}/protocol/openid-connect/auth?{urlencode(params)}")
    response.set_cookie(
        _OIDC_FLOW_COOKIE,
        flow_cookie,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/auth/oidc",
    )
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def oidc_callback_view(request):
    if not _web_oidc_enabled():
        raise Http404

    if request.query_params.get("error"):
        return _oidc_error_redirect(str(request.query_params.get("error")))

    code = str(request.query_params.get("code") or "").strip()
    state = str(request.query_params.get("state") or "").strip()
    if not code or not state:
        return _oidc_error_redirect("invalid_callback")

    raw_flow_cookie = str(request.COOKIES.get(_OIDC_FLOW_COOKIE) or "").strip()
    if not raw_flow_cookie:
        return _oidc_error_redirect("missing_login_state")

    try:
        flow = signing.loads(raw_flow_cookie, salt=_OIDC_FLOW_SIGNING_SALT, max_age=900)
    except Exception:  # noqa: BLE001
        return _oidc_error_redirect("invalid_login_state")

    expected_state = str(flow.get("state") or "").strip()
    code_verifier = str(flow.get("code_verifier") or "").strip()
    next_path = str(flow.get("next") or _oidc_post_login_redirect()).strip()
    if expected_state != state or not code_verifier:
        return _oidc_error_redirect("state_mismatch")
    if not next_path.startswith("/"):
        next_path = _oidc_post_login_redirect()

    issuer = _oidc_issuer()
    callback_uri = _oidc_callback_uri(request)
    token_endpoint = f"{issuer}/protocol/openid-connect/token"
    userinfo_endpoint = f"{issuer}/protocol/openid-connect/userinfo"

    try:
        token_response = requests.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": _oidc_web_client_id(),
                "code": code,
                "redirect_uri": callback_uri,
                "code_verifier": code_verifier,
            },
            timeout=5,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = str(token_payload.get("access_token") or "").strip()
        if not access_token:
            return _oidc_error_redirect("token_exchange_failed")

        userinfo_response = requests.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        )
        userinfo_response.raise_for_status()
        claims = userinfo_response.json()
    except Exception:  # noqa: BLE001
        return _oidc_error_redirect("oidc_exchange_failed")

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        return _oidc_error_redirect("invalid_claims")

    identity = resolve_or_provision_identity(
        issuer=issuer,
        subject=subject,
        claims=claims,
        auto_provision_users=bool(getattr(settings, "KEYCLOAK_AUTO_PROVISION_USERS", False)),
        auto_provision_organization=bool(getattr(settings, "KEYCLOAK_AUTO_PROVISION_ORGANIZATION", True)),
    )
    if identity is None:
        return _oidc_error_redirect("onboarding_required")

    refresh = RefreshToken.for_user(identity.user)
    access = str(refresh.access_token)

    response = redirect(next_path)
    _set_auth_cookies(response, access_token=access, refresh_token=str(refresh))
    response.delete_cookie(_OIDC_FLOW_COOKIE, path="/auth/oidc", domain=settings.AUTH_COOKIE_DOMAIN)
    return response
