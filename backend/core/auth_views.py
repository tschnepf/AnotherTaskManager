from django.http import Http404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from core.serializers import CustomTokenObtainPairSerializer, RegisterSerializer


class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


@api_view(["POST"])
@permission_classes([AllowAny])
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
    refresh = request.data.get("refresh")
    if refresh:
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except Exception:
            pass
    return Response({"status": "logged_out"}, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tenant_check_view(request, organization_id):
    if request.user.organization_id != organization_id:
        raise Http404

    return Response({"ok": True, "organization_id": str(organization_id)}, status=status.HTTP_200_OK)
