"""Sending email to suppliers.

The app only ever emails the supplier on file for an invoice, with a subject and body a
manager has read. The recipient is never taken from a request.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class MailerError(Exception):
    """The message could not be sent. The text is safe to show to a manager."""


class Mailer(Protocol):
    sender: str

    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, s: Settings) -> None:
        self.host, self.port = s.smtp_host, s.smtp_port
        self.username, self.password = s.smtp_username, s.smtp_password
        self.starttls = s.smtp_starttls
        self.timeout = s.smtp_timeout_seconds
        self.sender = s.email_from
        self.reply_to = s.email_reply_to

    def build(self, to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        message.set_content(body)
        return message

    def send(self, to: str, subject: str, body: str) -> None:
        message = self.build(to, subject, body)
        try:
            if self.starttls:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            else:
                context = ssl.create_default_context()
                client = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout, context=context
                )
            with client:
                if self.starttls:
                    client.starttls(context=ssl.create_default_context())
                if self.username:
                    client.login(self.username, self.password)
                client.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            logger.warning("SMTP login refused (%s)", exc.smtp_code)
            raise MailerError(
                "The mail server refused the login. Check SMTP_USERNAME and SMTP_PASSWORD."
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailerError(f"The mail server refused the address {to}.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("Sending email failed: %s", type(exc).__name__)
            raise MailerError(f"The email could not be sent ({type(exc).__name__}).") from exc


@lru_cache
def get_mailer() -> Mailer | None:
    """None when email is switched off or not fully set up."""
    s = get_settings()
    return SmtpMailer(s) if s.email_enabled else None


def display_sender() -> str | None:
    mailer = get_mailer()
    if mailer is None:
        return None
    name, address = parseaddr(mailer.sender)
    return formataddr((name, address)) if name else address
