import smtplib

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.models.invoice import SupplierEmail
from app.services import mailer
from app.services.mailer import MailerError, SmtpMailer


def settings(**changes) -> Settings:
    base = {
        "email_mode": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_username": "accounts@example.in",
        "smtp_password": "app-password",
        "email_from": "Brew & Bake Accounts <accounts@example.in>",
        "email_reply_to": "ap@example.in",
    }
    return Settings(**{**base, **changes})


class FakeSmtp:
    """Stands in for smtplib.SMTP and SMTP_SSL, and records what was done to it."""

    instances: list["FakeSmtp"] = []
    fail_login: Exception | None = None
    fail_send: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None) -> None:
        self.args = (host, port, timeout)
        self.ssl = context is not None
        self.calls: list = []
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.calls.append("quit")

    def starttls(self, context=None) -> None:
        self.calls.append("starttls")

    def login(self, user, password) -> None:
        if FakeSmtp.fail_login:
            raise FakeSmtp.fail_login
        self.calls.append(("login", user, password))

    def send_message(self, message) -> None:
        if FakeSmtp.fail_send:
            raise FakeSmtp.fail_send
        self.calls.append(("send", message))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances, FakeSmtp.fail_login, FakeSmtp.fail_send = [], None, None
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)


def test_a_message_has_the_right_headers_and_body() -> None:
    m = SmtpMailer(settings()).build(
        "ap@sharma.in", "Invoice SD-1042", "Please send a credit note."
    )
    assert m["From"] == "Brew & Bake Accounts <accounts@example.in>"
    assert (m["To"], m["Subject"], m["Reply-To"]) == (
        "ap@sharma.in",
        "Invoice SD-1042",
        "ap@example.in",
    )
    assert m.get_content().strip() == "Please send a credit note."


def test_starttls_login_then_send() -> None:
    SmtpMailer(settings()).send("ap@sharma.in", "Subject", "Body")
    (smtp,) = FakeSmtp.instances
    assert smtp.args == ("smtp.example.com", 587, 15)
    assert not smtp.ssl
    assert [c if isinstance(c, str) else c[0] for c in smtp.calls] == [
        "starttls",
        "login",
        "send",
        "quit",
    ]
    assert smtp.calls[1] == ("login", "accounts@example.in", "app-password")


def test_port_465_is_ssl_from_the_start() -> None:
    SmtpMailer(settings(smtp_port=465, smtp_starttls=False)).send("a@b.in", "S", "B")
    (smtp,) = FakeSmtp.instances
    assert smtp.ssl and "starttls" not in smtp.calls


def test_a_refused_login_is_reported_without_the_password() -> None:
    FakeSmtp.fail_login = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    with pytest.raises(MailerError) as exc:
        SmtpMailer(settings()).send("a@b.in", "S", "B")
    assert "refused the login" in str(exc.value)
    assert "app-password" not in str(exc.value)


@pytest.mark.parametrize(
    "failure, text",
    [
        (smtplib.SMTPRecipientsRefused({"a@b.in": (550, b"no")}), "refused the address a@b.in"),
        (smtplib.SMTPServerDisconnected("gone"), "could not be sent (SMTPServerDisconnected)"),
        (TimeoutError("slow"), "could not be sent (TimeoutError)"),
    ],
)
def test_send_failures_become_a_readable_error(failure, text) -> None:
    FakeSmtp.fail_send = failure
    with pytest.raises(MailerError, match=text.replace("(", r"\(").replace(")", r"\)")):
        SmtpMailer(settings()).send("a@b.in", "S", "B")


def test_email_is_off_unless_fully_set_up(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not settings(email_mode="disabled").email_enabled
    assert not settings(smtp_host="").email_enabled
    assert not settings(email_from="").email_enabled
    assert settings().email_enabled

    for name in ("EMAIL_MODE", "SMTP_HOST", "EMAIL_FROM"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    mailer.get_mailer.cache_clear()
    assert mailer.get_mailer() is None and mailer.display_sender() is None
    get_settings.cache_clear()
    mailer.get_mailer.cache_clear()


def test_the_subject_is_one_line_and_both_parts_are_required() -> None:
    assert SupplierEmail(subject=" Hello ", body=" Hi ").subject == "Hello"
    for bad in (
        {"subject": "Hi\nBcc: someone@else.com", "body": "x"},
        {"subject": "Hi\r\nBcc: x", "body": "x"},
        {"subject": " ", "body": "x"},
        {"subject": "Hi", "body": "  "},
        {"subject": "x" * 201, "body": "x"},
        {"subject": "Hi", "body": "x" * 8001},
    ):
        with pytest.raises(ValidationError):
            SupplierEmail(**bad)
