import re
from html import unescape
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses

from tasks.models import Task

LOW_PRIORITY = 1
EMAIL_HEADER_LINE_RE = re.compile(
    r"^\s*(from|to|sent|date|subject|cc|bcc|reply-to|message-id|mime-version|content-type|content-transfer-encoding)\s*:",
    re.IGNORECASE,
)
FORWARDED_MARKER_RE = re.compile(
    r"^\s*(?:-+\s*original message\s*-+|-*\s*forwarded message\s*-*|begin forwarded message:)\s*$",
    re.IGNORECASE,
)
ON_WROTE_RE = re.compile(r"^\s*on .+ wrote:\s*$", re.IGNORECASE)
FORCE_DIRECTIVE_RE = re.compile(r"^\s*(task|project)\s*:\s*(.*?)\s*$", re.IGNORECASE)
HTML_BREAK_TAG_RE = re.compile(r"(?i)</?(?:br|p|div|li|tr|h[1-6]|blockquote)[^>]*>")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")


def parse_eml(raw_eml: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(raw_eml)


def extract_subject(message: Message) -> str:
    return str(message.get("subject") or "").strip()


def extract_text_body(message: Message) -> str:
    plain_candidates = []
    html_candidates = []
    parts = message.walk() if message.is_multipart() else [message]

    for part in parts:
        if part.is_multipart():
            continue
        content_disposition = (part.get_content_disposition() or "").lower()
        filename = str(part.get_filename() or "").strip()
        if content_disposition == "attachment" or filename:
            continue

        content_type = (part.get_content_type() or "").lower()
        raw_text = _message_part_text(part)
        if not raw_text.strip():
            continue
        if content_type == "text/plain":
            plain_candidates.append(raw_text)
        elif content_type == "text/html":
            html_candidates.append(_html_to_text(raw_text))

    best_plain = _best_body_candidate(plain_candidates)
    if best_plain:
        return best_plain

    best_html = _best_body_candidate(html_candidates)
    if best_html:
        return best_html

    if (message.get_content_type() or "").lower() == "text/plain":
        return _message_part_text(message)
    if (message.get_content_type() or "").lower() == "text/html":
        return _html_to_text(_message_part_text(message))
    return ""


def clean_email_body_text(body_text: str) -> str:
    normalized = str(body_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    cleaned_lines = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if FORWARDED_MARKER_RE.match(stripped):
            if _has_non_empty_content(cleaned_lines):
                break
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            next_index = _skip_header_block(lines, index)
            if next_index > index:
                index = next_index
                while index < len(lines) and not lines[index].strip():
                    index += 1
            continue

        if ON_WROTE_RE.match(stripped):
            if _has_non_empty_content(cleaned_lines):
                break
            index += 1
            continue

        if EMAIL_HEADER_LINE_RE.match(line) and (not cleaned_lines or not cleaned_lines[-1].strip()):
            after_headers = _skip_header_block(lines, index)
            if after_headers > index:
                index = after_headers
                while index < len(lines) and not lines[index].strip():
                    index += 1
                continue

        cleaned_lines.append(line)
        index += 1

    return "\n".join(cleaned_lines).strip()


def extract_email_attachments(message: Message) -> list[dict]:
    attachments = []
    for part in message.walk():
        if part.is_multipart():
            continue

        content_disposition = (part.get_content_disposition() or "").lower()
        filename = str(part.get_filename() or "").strip()
        is_attachment = content_disposition == "attachment" or bool(filename)
        if not is_attachment:
            continue

        payload = part.get_payload(decode=True)
        if payload in (None, b""):
            continue

        content_type = str(part.get_content_type() or "application/octet-stream").strip().lower()
        attachments.append(
            {
                "name": filename or "attachment",
                "content": bytes(payload),
                "content_type": content_type,
            }
        )
    return attachments


def extract_recipient(message: Message) -> str:
    for header in ("Delivered-To", "X-Original-To", "To"):
        addresses = getaddresses([message.get(header, "")])
        for _, addr in addresses:
            normalized = addr.strip().lower()
            if normalized:
                return normalized
    return ""


def extract_sender(message: Message) -> str:
    for header in ("From", "Reply-To", "Sender"):
        addresses = getaddresses([message.get(header, "")])
        for _, addr in addresses:
            normalized = addr.strip().lower()
            if normalized:
                return normalized
    return ""


def parse_task_metadata(body_text: str, subject: str) -> tuple[str, str, str, int]:
    lines = [_clean_input_line(line) for line in body_text.splitlines()]
    lines = [line for line in lines if line]

    title = _value_or_empty(lines, 0, {"task title", "title"})
    project_hint = _value_or_empty(lines, 1, {"project name", "project"})
    area_hint = _value_or_empty(lines, 2, {"work or personal", "area"})
    priority_hint = _value_or_empty(lines, 3, {"priority"})

    title = title or subject or "Email task"
    area = _parse_area(area_hint)
    priority = _parse_priority(priority_hint)
    return title, project_hint, area, priority


def extract_force_directives(body_text: str, subject: str) -> tuple[dict[str, str], str]:
    directives = {}
    remaining_lines = []

    for raw_line in str(body_text or "").splitlines():
        match = FORCE_DIRECTIVE_RE.match(raw_line)
        if not match:
            remaining_lines.append(raw_line)
            continue

        field = match.group(1).strip().lower()
        value = match.group(2).strip()
        if not value:
            continue
        if field == "task":
            directives["task"] = subject if value.lower() == "subject" else value
        elif field == "project":
            directives["project"] = value

    remaining_body = "\n".join(remaining_lines).strip()
    return directives, remaining_body


def loose_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _skip_header_block(lines: list[str], start_index: int) -> int:
    index = start_index
    header_count = 0

    while index < len(lines):
        line = lines[index]
        if not EMAIL_HEADER_LINE_RE.match(line):
            break
        header_count += 1
        index += 1
        while index < len(lines):
            continuation = lines[index]
            if continuation.startswith((" ", "\t")):
                index += 1
                continue
            break

    if header_count == 0:
        return start_index
    if header_count == 1:
        header_name = lines[start_index].split(":", 1)[0].strip().lower()
        if header_name not in {"from", "to", "subject"}:
            return start_index
    return index


def _has_non_empty_content(lines: list[str]) -> bool:
    return any(line.strip() for line in lines)


def _best_body_candidate(candidates: list[str]) -> str:
    best_value = ""
    best_score = -1
    for candidate in candidates:
        cleaned = clean_email_body_text(candidate)
        score = len(cleaned.strip())
        if score > best_score:
            best_score = score
            best_value = candidate
    if best_score <= 0:
        return ""
    return best_value


def _message_part_text(part: Message) -> str:
    payload = part.get_content()
    if isinstance(payload, str):
        return payload
    if isinstance(payload, bytes):
        charset = str(part.get_content_charset() or "utf-8")
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    return str(payload or "")


def _html_to_text(raw_html: str) -> str:
    text = str(raw_html or "")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
    text = HTML_BREAK_TAG_RE.sub("\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = unescape(text)
    normalized_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        compact = HTML_WHITESPACE_RE.sub(" ", line).strip()
        normalized_lines.append(compact)
    return "\n".join(normalized_lines).strip()


def _clean_input_line(raw: str) -> str:
    value = str(raw or "").strip()
    if value.startswith("<") and value.endswith(">") and len(value) > 1:
        value = value[1:-1].strip()
    return value


def _value_or_empty(lines: list[str], index: int, placeholders: set[str]) -> str:
    if index >= len(lines):
        return ""
    value = lines[index].strip()
    if value.lower() in placeholders:
        return ""
    return value


def _parse_area(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == Task.Area.PERSONAL:
        return Task.Area.PERSONAL
    return Task.Area.WORK


def _parse_priority(value: str) -> int:
    normalized = value.strip().lower()
    if not normalized:
        return LOW_PRIORITY

    if normalized.isdigit():
        numeric = int(normalized)
        if 1 <= numeric <= 5:
            return numeric
        return LOW_PRIORITY

    by_label = {
        "low": 1,
        "medium": 3,
        "med": 3,
        "normal": 3,
        "high": 5,
        "urgent": 5,
    }
    return by_label.get(normalized, LOW_PRIORITY)
