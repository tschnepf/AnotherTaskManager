import logging
from uuid import uuid4

from rest_framework.views import exception_handler
from rest_framework import status

logger = logging.getLogger(__name__)


def _mobile_error_code(exc, response) -> str:
    data = response.data
    if isinstance(data, dict):
        detail_text = str(data.get("detail") or "").strip().lower()
        if detail_text in {"invalid_audience", "invalid_token", "insufficient_scope", "onboarding_required"}:
            return detail_text
        if isinstance(data.get("error"), dict) and data["error"].get("code"):
            return str(data["error"]["code"])
        if data.get("error_code"):
            return str(data["error_code"])
        if data.get("code"):
            return str(data["code"])
    if getattr(exc, "default_code", None):
        return str(exc.default_code)
    if response.status_code == status.HTTP_410_GONE:
        return "cursor_expired"
    if response.status_code == status.HTTP_409_CONFLICT:
        return "idempotency_conflict"
    if response.status_code == status.HTTP_403_FORBIDDEN:
        return "insufficient_scope"
    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        return "invalid_token"
    return "api_error"


def _mobile_error_message(response) -> str:
    data = response.data
    if isinstance(data, dict):
        detail = data.get("detail")
        if detail:
            return str(detail)
        message = data.get("message")
        if message:
            return str(message)
        for key, value in data.items():
            if key in {"detail", "message", "error", "request_id"}:
                continue
            if isinstance(value, list) and value:
                return f"{key}: {value[0]}"
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, list) and nested_value:
                        return f"{nested_key}: {nested_value[0]}"
                    if nested_value:
                        return f"{nested_key}: {nested_value}"
            if value:
                return f"{key}: {value}"
    if isinstance(data, list) and data:
        return str(data[0])
    return "Request failed"


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    request = context.get("request")
    request_id = request.headers.get("X-Request-ID") if request else None

    request_path = request.path if request else ""
    if request_path.startswith("/api/mobile/v1/"):
        response.data = {
            "error": {
                "code": _mobile_error_code(exc, response),
                "message": _mobile_error_message(response),
                "details": response.data if isinstance(response.data, dict) else {"detail": str(response.data)},
            },
            "request_id": request_id or str(uuid4()),
        }
        logger.warning(
            "mobile_api_non_2xx",
            extra={
                "status_code": response.status_code,
                "method": request.method if request else "",
                "path": request_path,
                "request_id": response.data["request_id"],
                "error_code": response.data["error"]["code"],
                "error_payload": response.data,
            },
        )
        return response

    payload = {
        "error_code": "api_error",
        "message": "Request failed",
        "details": response.data,
        "request_id": request_id or str(uuid4()),
    }

    if isinstance(response.data, dict) and "detail" in response.data:
        payload["message"] = str(response.data.get("detail"))

    response.data = payload
    return response
