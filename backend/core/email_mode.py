import os


INBOUND_EMAIL_MODE_IMAP = "imap"
INBOUND_EMAIL_MODE_WEBHOOK = "webhook"
INBOUND_EMAIL_MODE_GMAIL_OAUTH = "gmail_oauth"
INBOUND_EMAIL_MODE_CHOICES = {
    INBOUND_EMAIL_MODE_IMAP,
    INBOUND_EMAIL_MODE_WEBHOOK,
    INBOUND_EMAIL_MODE_GMAIL_OAUTH,
}


def get_inbound_email_mode() -> str:
    mode = os.getenv("INBOUND_EMAIL_MODE", INBOUND_EMAIL_MODE_IMAP).strip().lower()
    if mode in INBOUND_EMAIL_MODE_CHOICES:
        return mode
    return INBOUND_EMAIL_MODE_IMAP
