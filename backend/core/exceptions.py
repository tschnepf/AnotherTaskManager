from uuid import uuid4

from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    request = context.get("request")
    request_id = request.headers.get("X-Request-ID") if request else None
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
