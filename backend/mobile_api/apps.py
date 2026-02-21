from django.apps import AppConfig


class MobileApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mobile_api"

    def ready(self):
        from . import signals  # noqa: F401
        from .apns import validate_apns_configuration

        validate_apns_configuration()
