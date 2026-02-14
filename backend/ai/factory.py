import os

from ai.privacy import cloud_allowed
from ai.providers import AIProvider, CloudProvider, HybridProvider, LocalProvider


def get_provider(mode: str | None = None, *, org_allow_cloud_ai: bool = False, task_allow_cloud_processing: bool | None = None) -> AIProvider | None:
    resolved_mode = (mode or os.getenv("AI_MODE", "off")).lower()
    if resolved_mode == "off":
        return None

    if resolved_mode == "local":
        return LocalProvider()

    if resolved_mode == "cloud":
        return CloudProvider() if cloud_allowed(org_allow_cloud_ai, task_allow_cloud_processing) else None

    if resolved_mode == "hybrid":
        if cloud_allowed(org_allow_cloud_ai, task_allow_cloud_processing):
            return HybridProvider()
        return LocalProvider()

    return None
