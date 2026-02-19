from pathlib import Path
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
    },
}

SIMPLE_JWT = {
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

# Allow same-origin iframe rendering so in-app media previews (PDF/image) can load.
X_FRAME_OPTIONS = "SAMEORIGIN"

ATTACHMENT_ACCESS_TOKEN_MAX_AGE_SECONDS = os.getenv("ATTACHMENT_ACCESS_TOKEN_MAX_AGE_SECONDS", "3600")

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
