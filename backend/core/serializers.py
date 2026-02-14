from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from core.models import Organization, User


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    organization_name = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def create(self, validated_data):
        org_name = validated_data.get("organization_name") or "Default Organization"
        org = Organization.objects.create(name=org_name)
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            display_name=validated_data.get("display_name", ""),
            role=User.Role.OWNER,
            organization=org,
        )
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.EMAIL_FIELD

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["user_id"] = str(user.id)
        token["organization_id"] = str(user.organization_id) if user.organization_id else None
        token["role"] = user.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # Superusers created via `createsuperuser` may not have org/role context.
        # Provision a default organization at first login so task APIs are usable.
        if self.user.organization_id is None:
            email_local = self.user.email.split("@", 1)[0] if self.user.email else "default"
            org = Organization.objects.create(name=f"{email_local} Organization")
            self.user.organization = org
            if self.user.is_superuser:
                self.user.role = User.Role.OWNER
                self.user.is_staff = True
            self.user.save(update_fields=["organization", "role", "is_staff"])

            refresh = self.get_token(self.user)
            data["refresh"] = str(refresh)
            data["access"] = str(refresh.access_token)

        data["user_id"] = str(self.user.id)
        data["organization_id"] = str(self.user.organization_id) if self.user.organization_id else None
        data["role"] = self.user.role
        return data
