from __future__ import annotations


def build_realm_url(raw_base_url: str, realm: str) -> str:
    base = str(raw_base_url).strip().rstrip("/")
    if not base:
        return ""
    if base.endswith(f"/realms/{realm}"):
        return base
    if "/realms/" in base:
        return base
    if base.endswith("/realms"):
        return f"{base}/{realm}"
    if base.endswith("/idp"):
        return f"{base}/realms/{realm}"
    return f"{base}/idp/realms/{realm}"
