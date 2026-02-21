from __future__ import annotations

from uuid import uuid4


def request_id_from_headers(headers) -> str:
    value = str(headers.get("X-Request-ID") or "").strip()
    return value or str(uuid4())
