import secrets

from django.utils.crypto import constant_time_compare, salted_hmac

INBOUND_TOKEN_HASH_PREFIX = "sha256$"
INBOUND_TOKEN_HASH_SALT = "taskhub.inbound_email_ingest"


def _digest_inbound_ingest_token(raw_token: str) -> str:
    return salted_hmac(INBOUND_TOKEN_HASH_SALT, raw_token).hexdigest()


def hash_inbound_ingest_token(raw_token: str) -> str:
    return f"{INBOUND_TOKEN_HASH_PREFIX}{_digest_inbound_ingest_token(raw_token)}"


def verify_inbound_ingest_token(provided_token: str, stored_value: str) -> bool:
    provided = str(provided_token or "")
    stored = str(stored_value or "")
    if not provided or not stored:
        return False
    if stored.startswith(INBOUND_TOKEN_HASH_PREFIX):
        expected = hash_inbound_ingest_token(provided)
        return constant_time_compare(expected, stored)
    return constant_time_compare(provided, stored)


def rotate_inbound_ingest_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_inbound_ingest_token(raw)

