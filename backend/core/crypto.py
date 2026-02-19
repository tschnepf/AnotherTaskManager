import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

ENCRYPTED_VALUE_PREFIX = "enc$"
FIELD_KEY_DERIVE_SALT = "taskhub-field-encryption-v1"


def is_encrypted_secret(value: str) -> bool:
    return str(value or "").startswith(ENCRYPTED_VALUE_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    raw_value = str(plaintext or "")
    if not raw_value:
        return ""
    if is_encrypted_secret(raw_value):
        return raw_value
    token = _primary_fernet().encrypt(raw_value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_VALUE_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    raw_value = str(value or "")
    if not raw_value:
        return ""
    if not is_encrypted_secret(raw_value):
        return raw_value

    token = raw_value[len(ENCRYPTED_VALUE_PREFIX) :]
    if not token:
        return ""

    for fernet in _all_fernets():
        try:
            return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            continue
    raise ValueError("encrypted secret cannot be decrypted with configured keys")


def rotate_encrypted_secret(plaintext: str) -> str:
    return encrypt_secret(plaintext)


@lru_cache(maxsize=1)
def _all_fernets() -> tuple[Fernet, ...]:
    keys = _configured_field_encryption_keys()
    return tuple(Fernet(key.encode("utf-8")) for key in keys)


def _primary_fernet() -> Fernet:
    return _all_fernets()[0]


def _configured_field_encryption_keys() -> list[str]:
    configured = getattr(settings, "TASKHUB_FIELD_ENCRYPTION_KEYS", ())
    keys = [str(value or "").strip() for value in configured if str(value or "").strip()]
    if not keys:
        raise ValueError("TASKHUB_FIELD_ENCRYPTION_KEYS is empty")

    normalized = []
    seen = set()
    for key in keys:
        normalized_key = _as_fernet_key(key)
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        normalized.append(normalized_key)
    return normalized


def _as_fernet_key(raw_key: str) -> str:
    candidate = str(raw_key or "").strip()
    if not candidate:
        raise ValueError("field encryption key cannot be empty")

    if _looks_like_fernet_key(candidate):
        return candidate

    digest = hashlib.sha256(f"{FIELD_KEY_DERIVE_SALT}:{candidate}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


def _looks_like_fernet_key(value: str) -> bool:
    if len(value) != 44:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value.encode("utf-8"))
    except Exception:
        return False
    return len(decoded) == 32
