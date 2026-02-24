from pathlib import Path
from datetime import timedelta
import os
import sys
from urllib.parse import urlparse
from django.core.exceptions import ImproperlyConfigured
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

RUNNING_TESTS = "PYTEST_CURRENT_TEST" in os.environ or any("pytest" in arg for arg in sys.argv)

if RUNNING_TESTS:
    os.environ.setdefault("DJANGO_SECRET_KEY", "test-django-secret-key-for-local-tests-only")
    os.environ.setdefault("TASKHUB_FIELD_ENCRYPTION_KEY", "test-field-encryption-key-for-local-tests-only")
    os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"

DEFAULT_DJANGO_SECRET_KEY = "taskhub-dev-secret-key-change-this-in-production-1234567890"
MIN_DJANGO_SECRET_KEY_LENGTH = 32
SECRET_KEY = str(os.getenv("DJANGO_SECRET_KEY", "")).strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = DEFAULT_DJANGO_SECRET_KEY
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required.")


def _field_encryption_keys_from_env() -> tuple[str, ...]:
    keys: list[str] = []

    raw_many = str(os.getenv("TASKHUB_FIELD_ENCRYPTION_KEYS", "")).strip()
    if raw_many:
        keys.extend(segment.strip() for segment in raw_many.split(",") if segment.strip())

    raw_single = str(os.getenv("TASKHUB_FIELD_ENCRYPTION_KEY", "")).strip()
    if raw_single:
        keys.append(raw_single)

    deduped = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)

    if not deduped:
        raise ImproperlyConfigured(
            "Missing field encryption key. Set TASKHUB_FIELD_ENCRYPTION_KEY "
            "or TASKHUB_FIELD_ENCRYPTION_KEYS before starting the app."
        )
    return tuple(deduped)


TASKHUB_FIELD_ENCRYPTION_KEYS = _field_encryption_keys_from_env()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "true" if default else "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = str(os.getenv(name, default)).strip()
    if not raw:
        return []
    return [piece.strip() for piece in raw.split(",") if piece.strip()]

if not DEBUG and SECRET_KEY == DEFAULT_DJANGO_SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is using an unsafe default value. Set a strong unique key."
    )
if not DEBUG and len(SECRET_KEY) < MIN_DJANGO_SECRET_KEY_LENGTH:
    raise ImproperlyConfigured(
        f"DJANGO_SECRET_KEY must be at least {MIN_DJANGO_SECRET_KEY_LENGTH} characters."
    )

allowed_hosts_raw = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
if not allowed_hosts_raw:
    if DEBUG:
        ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
    else:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required when DJANGO_DEBUG is false.")
elif "*" in allowed_hosts_raw:
    if DEBUG:
        ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
    else:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS cannot include '*' when DJANGO_DEBUG is false.")
else:
    ALLOWED_HOSTS = allowed_hosts_raw
CORS_ALLOWED_ORIGINS = [
    origin for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:8080").split(",") if origin
]
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        ",".join(CORS_ALLOWED_ORIGINS),
    ).split(",")
    if origin
]
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "core",
    "tasks",
    "ai",
    "collaboration",
    "mobile_api.apps.MobileApiConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def _db_config_from_env() -> dict:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }

    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/") or "taskhub",
            "USER": parsed.username or "postgres",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
        }

    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


DATABASES = {
    "default": _db_config_from_env(),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "core.authentication.CookieOrHeaderJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "inbound_email_ingest": os.getenv("THROTTLE_INBOUND_EMAIL_INGEST", "60/min"),
        "mobile_auth": os.getenv("MOBILE_RATE_LIMIT_AUTH", "20/min"),
        "mobile_sync": os.getenv("MOBILE_RATE_LIMIT_SYNC", "120/min"),
        "mobile_intent": os.getenv("MOBILE_RATE_LIMIT_INTENT", "30/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", "5"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_LIFETIME_DAYS", "1"))
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

AUTH_COOKIE_ACCESS_NAME = os.getenv("AUTH_COOKIE_ACCESS_NAME", "taskhub_access")
AUTH_COOKIE_REFRESH_NAME = os.getenv("AUTH_COOKIE_REFRESH_NAME", "taskhub_refresh")
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Lax")
AUTH_COOKIE_DOMAIN = str(os.getenv("AUTH_COOKIE_DOMAIN", "")).strip() or None
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false" if DEBUG else "true").lower() == "true"
AUTH_COOKIE_ACCESS_PATH = "/"
AUTH_COOKIE_REFRESH_PATH = "/auth/refresh"
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "false" if DEBUG else "true").lower() == "true"

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)

TASK_ARCHIVE_CADENCE = os.getenv("TASK_ARCHIVE_CADENCE", "weekly").strip().lower()

CELERY_BEAT_SCHEDULE = {}
if TASK_ARCHIVE_CADENCE == "weekly":
    CELERY_BEAT_SCHEDULE["archive-completed-tasks"] = {
        "task": "tasks.archive_completed",
        "schedule": crontab(minute=0, hour=2, day_of_week="monday"),
    }
elif TASK_ARCHIVE_CADENCE == "monthly":
    CELERY_BEAT_SCHEDULE["archive-completed-tasks"] = {
        "task": "tasks.archive_completed",
        "schedule": crontab(minute=0, hour=2, day_of_month="1"),
    }

INBOUND_EMAIL_MODE = os.getenv("INBOUND_EMAIL_MODE", "imap").strip().lower()
if INBOUND_EMAIL_MODE == "imap":
    raw_interval = os.getenv("IMAP_POLL_INTERVAL_MINUTES", "2").strip()
    try:
        imap_poll_interval_minutes = int(raw_interval)
    except ValueError:
        imap_poll_interval_minutes = 2
    imap_poll_interval_minutes = max(1, min(imap_poll_interval_minutes, 59))
    CELERY_BEAT_SCHEDULE["sync-inbound-imap"] = {
        "task": "tasks.sync_inbound_imap",
        "schedule": crontab(minute=f"*/{imap_poll_interval_minutes}"),
    }

if _env_bool("MOBILE_API_ENABLED", False):
    CELERY_BEAT_SCHEDULE["mobile-purge-task-change-events"] = {
        "task": "mobile_api.purge_task_change_events",
        "schedule": crontab(minute=10, hour=3),
    }
    CELERY_BEAT_SCHEDULE["mobile-purge-idempotency-records"] = {
        "task": "mobile_api.purge_idempotency_records",
        "schedule": crontab(minute=20, hour=3),
    }
    CELERY_BEAT_SCHEDULE["mobile-purge-notification-deliveries"] = {
        "task": "mobile_api.purge_notification_deliveries",
        "schedule": crontab(minute=30, hour=3),
    }
    CELERY_BEAT_SCHEDULE["mobile-process-pending-notifications"] = {
        "task": "mobile_api.process_pending_notifications",
        "schedule": crontab(minute="*"),
    }

# Allow same-origin iframe rendering so in-app media previews (PDF/image) can load.
X_FRAME_OPTIONS = "SAMEORIGIN"

ATTACHMENT_ACCESS_TOKEN_MAX_AGE_SECONDS = os.getenv("ATTACHMENT_ACCESS_TOKEN_MAX_AGE_SECONDS", "3600")

MOBILE_API_ENABLED = _env_bool("MOBILE_API_ENABLED", False)
KEYCLOAK_AUTH_ENABLED = _env_bool("KEYCLOAK_AUTH_ENABLED", False)
KEYCLOAK_BASE_URL = str(os.getenv("KEYCLOAK_BASE_URL", "http://keycloak:8080/idp")).strip()
KEYCLOAK_PUBLIC_BASE_URL = str(os.getenv("KEYCLOAK_PUBLIC_BASE_URL", "")).strip()
KEYCLOAK_REALM = str(os.getenv("KEYCLOAK_REALM", "taskhub")).strip()
KEYCLOAK_IOS_CLIENT_ID = str(os.getenv("KEYCLOAK_IOS_CLIENT_ID", "taskhub-mobile")).strip()
KEYCLOAK_REQUIRED_AUDIENCE = str(os.getenv("KEYCLOAK_REQUIRED_AUDIENCE", "taskhub-api")).strip()
KEYCLOAK_ALLOWED_ALGS = str(os.getenv("KEYCLOAK_ALLOWED_ALGS", "RS256")).strip()
KEYCLOAK_JWKS_SOFT_TTL_SECONDS = int(os.getenv("KEYCLOAK_JWKS_SOFT_TTL_SECONDS", "300"))
KEYCLOAK_JWKS_HARD_TTL_SECONDS = int(os.getenv("KEYCLOAK_JWKS_HARD_TTL_SECONDS", "3600"))
KEYCLOAK_JWKS_FETCH_TIMEOUT_SECONDS = int(os.getenv("KEYCLOAK_JWKS_FETCH_TIMEOUT_SECONDS", "3"))
KEYCLOAK_ALLOWED_PUBLIC_HOSTS = _env_csv("KEYCLOAK_ALLOWED_PUBLIC_HOSTS", "")
KEYCLOAK_AUTO_PROVISION_USERS = _env_bool("KEYCLOAK_AUTO_PROVISION_USERS", False)
KEYCLOAK_AUTO_PROVISION_ORGANIZATION = _env_bool("KEYCLOAK_AUTO_PROVISION_ORGANIZATION", True)
KEYCLOAK_WEB_AUTH_ENABLED = _env_bool("KEYCLOAK_WEB_AUTH_ENABLED", False)
KEYCLOAK_WEB_CLIENT_ID = str(os.getenv("KEYCLOAK_WEB_CLIENT_ID", "taskhub-web")).strip()
KEYCLOAK_WEB_SCOPES = str(os.getenv("KEYCLOAK_WEB_SCOPES", "openid")).strip()
KEYCLOAK_WEB_POST_LOGIN_REDIRECT = str(os.getenv("KEYCLOAK_WEB_POST_LOGIN_REDIRECT", "/")).strip() or "/"
KEYCLOAK_WEB_SIGNUP_ENABLED = _env_bool("KEYCLOAK_WEB_SIGNUP_ENABLED", False)
KEYCLOAK_AUTO_BOOTSTRAP_WEB_CLIENT = _env_bool("KEYCLOAK_AUTO_BOOTSTRAP_WEB_CLIENT", True)
KEYCLOAK_ADMIN_REALM = str(os.getenv("KEYCLOAK_ADMIN_REALM", "master")).strip() or "master"
KEYCLOAK_ADMIN_USER = str(os.getenv("KEYCLOAK_ADMIN_USER", "admin")).strip()
KEYCLOAK_ADMIN_PASSWORD = str(os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")).strip()
MOBILE_TOKEN_CLOCK_SKEW_SECONDS = int(os.getenv("MOBILE_TOKEN_CLOCK_SKEW_SECONDS", "60"))
MOBILE_SYNC_MAX_PAGE_SIZE = int(os.getenv("MOBILE_SYNC_MAX_PAGE_SIZE", "500"))
MOBILE_EVENT_RETENTION_DAYS = int(os.getenv("MOBILE_EVENT_RETENTION_DAYS", "30"))
MOBILE_IDEMPOTENCY_TTL_HOURS = int(os.getenv("MOBILE_IDEMPOTENCY_TTL_HOURS", "24"))
MOBILE_NOTIFICATION_DELIVERY_RETENTION_DAYS = int(
    os.getenv("MOBILE_NOTIFICATION_DELIVERY_RETENTION_DAYS", "30")
)
MOBILE_TASK_CHANGE_PUSH_ENABLED = _env_bool("MOBILE_TASK_CHANGE_PUSH_ENABLED", True)
MOBILE_TASK_CHANGE_PUSH_DEDUPE_WINDOW_SECONDS = int(
    os.getenv("MOBILE_TASK_CHANGE_PUSH_DEDUPE_WINDOW_SECONDS", "10")
)
MOBILE_TASK_CHANGE_PUSH_PROCESS_BATCH_SIZE = int(
    os.getenv("MOBILE_TASK_CHANGE_PUSH_PROCESS_BATCH_SIZE", "200")
)
MOBILE_TASK_CHANGE_PUSH_TRIGGER_ASYNC = _env_bool("MOBILE_TASK_CHANGE_PUSH_TRIGGER_ASYNC", True)
APNS_ENABLED = _env_bool("APNS_ENABLED", False)
APNS_KEY_ID = str(os.getenv("APNS_KEY_ID", "")).strip()
APNS_TEAM_ID = str(os.getenv("APNS_TEAM_ID", "")).strip()
APNS_BUNDLE_ID = str(os.getenv("APNS_BUNDLE_ID", "")).strip()
APNS_PRIVATE_KEY_PATH = str(os.getenv("APNS_PRIVATE_KEY_PATH", "")).strip()
APNS_PRIVATE_KEY_B64 = str(os.getenv("APNS_PRIVATE_KEY_B64", "")).strip()
APNS_USE_SANDBOX = _env_bool("APNS_USE_SANDBOX", True)
APNS_PROVIDER = str(os.getenv("APNS_PROVIDER", "mock")).strip().lower()
MOBILE_NOTIFICATION_MAX_ATTEMPTS = int(os.getenv("MOBILE_NOTIFICATION_MAX_ATTEMPTS", "5"))
MOBILE_NOTIFICATION_LEASE_SECONDS = int(os.getenv("MOBILE_NOTIFICATION_LEASE_SECONDS", "60"))
MOBILE_NOTIFICATION_RETRY_BASE_SECONDS = int(os.getenv("MOBILE_NOTIFICATION_RETRY_BASE_SECONDS", "30"))

if REDIS_URL := str(os.getenv("REDIS_URL", "")).strip():
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "taskhub-default",
        }
    }

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
