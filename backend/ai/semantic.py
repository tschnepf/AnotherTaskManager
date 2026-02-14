import os
from difflib import SequenceMatcher

from tasks.models import Task


def semantic_search_with_fallback(queryset, query: str, semantic_requested: bool):
    if not semantic_requested:
        return queryset, False, None

    ai_mode = os.getenv("AI_MODE", "off").lower()
    if ai_mode == "off":
        fallback = queryset.filter(title__icontains=query) | queryset.filter(description__icontains=query)
        return fallback.distinct(), False, "ai_mode_off"

    # Placeholder semantic behavior for now: still use text matching and mark as used.
    matched = queryset.filter(title__icontains=query) | queryset.filter(description__icontains=query)
    return matched.distinct(), True, None


def dedupe_candidates(title: str, candidates: list[Task], threshold: float = 0.92):
    matches = []
    for candidate in candidates:
        ratio = SequenceMatcher(None, title.lower(), candidate.title.lower()).ratio()
        if ratio >= threshold:
            matches.append({"task_id": str(candidate.id), "score": ratio})
    return matches
