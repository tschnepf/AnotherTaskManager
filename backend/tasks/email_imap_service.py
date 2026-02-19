import imaplib

from core.models import Organization
from tasks.email_capture_service import EmailIngestError, ingest_raw_email_for_org
from tasks.email_ingest import parse_eml


def is_imap_configured(organization: Organization) -> bool:
    username = (organization.imap_username or "").strip()
    try:
        password = (organization.get_imap_password() or "").strip()
    except ValueError:
        return False
    return bool(username and password)


def sync_inbound_imap(organization: Organization, max_messages: int = 25) -> dict:
    config = _imap_config(organization)
    max_messages = max(1, min(int(max_messages), 100))

    mailbox = _connect_imap(config)
    processed = 0
    created = 0
    failed = []
    try:
        select_status, _select_data = mailbox.select(config["folder"], readonly=False)
        if select_status != "OK":
            raise RuntimeError(f"failed to select IMAP folder: {config['folder']}")

        search_status, search_data = mailbox.search(None, config["search_criteria"])
        if search_status != "OK":
            raise RuntimeError("failed to search IMAP mailbox")

        message_ids = (search_data[0] or b"").split()
        if max_messages and len(message_ids) > max_messages:
            message_ids = message_ids[-max_messages:]

        for message_id in message_ids:
            processed += 1
            message_label = message_id.decode("utf-8", errors="ignore") or str(message_id)
            try:
                raw_eml = _fetch_message_raw(mailbox, message_id)
                parse_eml(raw_eml)
                ingest_raw_email_for_org(organization, raw_eml)
                created += 1
                if config["mark_seen_on_success"]:
                    mailbox.store(message_id, "+FLAGS", "\\Seen")
            except EmailIngestError as exc:
                failed.append({"id": message_label, "error_code": exc.error_code, "message": exc.message})
            except Exception as exc:  # noqa: BLE001
                failed.append({"id": message_label, "message": f"processing failed: {exc}"})
    finally:
        try:
            mailbox.logout()
        except Exception:  # noqa: BLE001
            pass

    return {
        "processed": processed,
        "created": created,
        "failed": failed,
    }


def _imap_config(organization: Organization) -> dict:
    username = (organization.imap_username or "").strip()
    try:
        password = (organization.get_imap_password() or "").strip()
    except ValueError as exc:
        raise ValueError("IMAP credentials cannot be decrypted; rotate IMAP password in Settings") from exc
    host = (organization.imap_host or "").strip()
    provider = (organization.imap_provider or "auto").strip().lower()
    if not username or not password:
        raise ValueError("IMAP is not configured; set IMAP username and password in Settings > IMAP")
    if not host:
        host = _resolve_imap_host(username, provider)

    port = int(organization.imap_port or 993)
    if port <= 0:
        raise ValueError("IMAP port must be a positive integer")

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "use_ssl": bool(organization.imap_use_ssl),
        "folder": (organization.imap_folder or "INBOX").strip() or "INBOX",
        "search_criteria": (organization.imap_search_criteria or "UNSEEN").strip() or "UNSEEN",
        "mark_seen_on_success": bool(organization.imap_mark_seen_on_success),
    }


def _connect_imap(config: dict):
    if config["use_ssl"]:
        mailbox = imaplib.IMAP4_SSL(config["host"], config["port"])
    else:
        mailbox = imaplib.IMAP4(config["host"], config["port"])
    mailbox.login(config["username"], config["password"])
    return mailbox


def _fetch_message_raw(mailbox, message_id: bytes) -> bytes:
    fetch_status, fetch_data = mailbox.fetch(message_id, "(RFC822)")
    if fetch_status != "OK":
        raise RuntimeError("failed to fetch message from IMAP")

    for item in fetch_data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    raise RuntimeError("IMAP message payload was empty")
def _resolve_imap_host(username: str, provider: str) -> str:
    provider_hosts = {
        "gmail": "imap.gmail.com",
        "google": "imap.gmail.com",
        "outlook": "outlook.office365.com",
        "office365": "outlook.office365.com",
        "microsoft": "outlook.office365.com",
        "yahoo": "imap.mail.yahoo.com",
        "icloud": "imap.mail.me.com",
        "aol": "imap.aol.com",
        "fastmail": "imap.fastmail.com",
    }
    if provider in provider_hosts:
        return provider_hosts[provider]

    domain = ""
    if "@" in username:
        domain = username.split("@", 1)[1].strip().lower()

    if not domain:
        raise ValueError("IMAP_HOST is required when username is not an email address")

    domain_hosts = {
        "gmail.com": "imap.gmail.com",
        "googlemail.com": "imap.gmail.com",
        "outlook.com": "outlook.office365.com",
        "hotmail.com": "outlook.office365.com",
        "live.com": "outlook.office365.com",
        "office365.com": "outlook.office365.com",
        "yahoo.com": "imap.mail.yahoo.com",
        "yahoo.co.uk": "imap.mail.yahoo.com",
        "icloud.com": "imap.mail.me.com",
        "me.com": "imap.mail.me.com",
        "mac.com": "imap.mail.me.com",
        "aol.com": "imap.aol.com",
    }
    if domain in domain_hosts:
        return domain_hosts[domain]

    if domain.endswith(".fastmail.com") or domain.endswith(".fastmail.fm"):
        return "imap.fastmail.com"

    return f"imap.{domain}"
