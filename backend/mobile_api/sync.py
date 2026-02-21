from __future__ import annotations

import base64

from rest_framework import serializers

_CURSOR_PREFIX = "v1."


def encode_cursor(event_id: int) -> str:
    normalized = max(0, int(event_id))
    raw = str(normalized).encode("ascii")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{_CURSOR_PREFIX}{encoded}"


def decode_cursor(token: str) -> int:
    value = str(token or "").strip()
    if not value:
        return 0

    # Backward compatibility for early numeric cursors before opaque encoding.
    if value.isdigit():
        return max(0, int(value))

    if not value.startswith(_CURSOR_PREFIX):
        raise serializers.ValidationError({"cursor": "invalid cursor token"})

    encoded = value[len(_CURSOR_PREFIX) :]
    if not encoded:
        raise serializers.ValidationError({"cursor": "invalid cursor token"})

    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{encoded}{padding}".encode("ascii")).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        raise serializers.ValidationError({"cursor": "invalid cursor token"}) from exc

    if not decoded.isdigit():
        raise serializers.ValidationError({"cursor": "invalid cursor token"})
    return max(0, int(decoded))
