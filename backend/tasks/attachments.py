import posixpath
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.core import signing

ATTACHMENT_TOKEN_SALT = "taskhub-attachment-access-v1"

BLOCKED_UPLOAD_EXTENSIONS = {
    "html",
    "htm",
    "svg",
    "js",
    "mjs",
    "xhtml",
    "swf",
}

FORCE_DOWNLOAD_EXTENSIONS = {
    "html",
    "htm",
    "svg",
    "js",
    "mjs",
    "xhtml",
    "xml",
}


def attachment_extension(name: str) -> str:
    suffix = PurePosixPath(str(name or "")).suffix
    if not suffix:
        return ""
    return suffix.lstrip(".").lower()


def normalize_storage_path(raw_path: str) -> str:
    value = str(raw_path or "").strip()
    if not value:
        return ""
    value = value.lstrip("/")
    if value.startswith("media/"):
        value = value[len("media/") :]
    normalized = posixpath.normpath(value)
    if normalized in {".", "", ".."}:
        return ""
    if normalized.startswith("../"):
        return ""
    if not normalized.startswith("tasks/"):
        return ""
    return normalized


def path_matches_org(path: str, organization_id: str) -> bool:
    normalized = normalize_storage_path(path)
    if not normalized:
        return False
    parts = PurePosixPath(normalized).parts
    if len(parts) < 4:
        return False
    return parts[0] == "tasks" and parts[1] == str(organization_id)


def path_matches_task(path: str, task_id: str) -> bool:
    normalized = normalize_storage_path(path)
    if not normalized:
        return False
    parts = PurePosixPath(normalized).parts
    if len(parts) < 4:
        return False
    return parts[2] == str(task_id)


def build_attachment_token(path: str) -> str:
    normalized = normalize_storage_path(path)
    if not normalized:
        raise ValueError("invalid attachment path")
    return signing.dumps({"path": normalized}, salt=ATTACHMENT_TOKEN_SALT)


def decode_attachment_token(token: str, *, max_age: int | None = None) -> str:
    payload = signing.loads(token, salt=ATTACHMENT_TOKEN_SALT, max_age=max_age)
    return normalize_storage_path(payload.get("path") or "")


def build_attachment_access_url(path: str) -> str:
    token = build_attachment_token(path)
    return f"/tasks/attachments/file?{urlencode({'token': token})}"


def attachment_token_max_age_seconds() -> int:
    configured = getattr(settings, "ATTACHMENT_ACCESS_TOKEN_MAX_AGE_SECONDS", 3600)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = 3600
    return max(60, min(value, 7 * 24 * 60 * 60))


def path_from_attachment_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return ""

    if parsed.path.startswith("/media/"):
        return normalize_storage_path(parsed.path)

    if parsed.path == "/tasks/attachments/file":
        token = parse_qs(parsed.query).get("token", [""])[0]
        if not token:
            return ""
        try:
            return decode_attachment_token(token, max_age=None)
        except signing.BadSignature:
            return ""

    return ""


def normalize_attachment_input(item: dict) -> dict:
    name = str((item or {}).get("name") or "").strip() or "Attachment"
    path = normalize_storage_path((item or {}).get("path") or "")
    if not path:
        path = path_from_attachment_url((item or {}).get("url") or "")
    if not path:
        raise ValueError("attachment path is required")
    return {"name": name, "path": path}
