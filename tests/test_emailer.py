import smtplib

import pytest

from new_ebooks import emailer
from new_ebooks.config import EmailConfig
from new_ebooks.emailer import send_email


class FakeServer:
    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.tls_started = False
        self.login_args = None
        self.sent = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls_started = True

    def login(self, user, password):
        self.login_args = (user, password)

    def sendmail(self, from_addr, to_addrs, msg):
        self.sent = (from_addr, to_addrs, msg)


def make_config(**overrides) -> EmailConfig:
    values = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "user@example.com",
        "smtp_from": "user@example.com",
        "smtp_to": "reader@example.com",
        "use_tls": True,
    }
    values.update(overrides)
    return EmailConfig(**values)


def _install(monkeypatch, smtp_factory=None, smtp_ssl_factory=None):
    """Replace the SMTP classes; unpatched ones fail the test if used."""
    def unexpected(*args, **kwargs):
        pytest.fail("wrong SMTP class used for this config")

    monkeypatch.setattr(emailer.smtplib, "SMTP", smtp_factory or unexpected)
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", smtp_ssl_factory or unexpected)


def test_send_email_starttls_login_and_send(monkeypatch):
    servers = []

    def factory(host, port, timeout=None):
        server = FakeServer(host, port)
        servers.append(server)
        return server

    _install(monkeypatch, smtp_factory=factory)
    send_email("Subject", "<p>hi</p>", make_config(), "secret")

    assert len(servers) == 1
    server = servers[0]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.tls_started
    assert server.login_args == ("user@example.com", "secret")
    from_addr, to_addrs, raw = server.sent
    assert from_addr == "user@example.com"
    assert to_addrs == ["reader@example.com"]
    assert "Subject" in raw


def test_send_email_no_starttls_when_tls_disabled(monkeypatch):
    servers = []

    def factory(host, port, timeout=None):
        server = FakeServer(host, port)
        servers.append(server)
        return server

    _install(monkeypatch, smtp_factory=factory)
    send_email("S", "x", make_config(use_tls=False), "secret")
    assert servers[0].tls_started is False
    assert servers[0].sent is not None


def test_send_email_port_465_uses_smtp_ssl(monkeypatch):
    servers = []

    def ssl_factory(host, port, context=None, timeout=None):
        server = FakeServer(host, port)
        servers.append(server)
        return server

    _install(monkeypatch, smtp_ssl_factory=ssl_factory)
    send_email("S", "x", make_config(smtp_port=465), "secret")
    assert servers[0].port == 465
    assert servers[0].sent is not None


def test_send_email_skips_login_without_user(monkeypatch):
    servers = []

    def factory(host, port, timeout=None):
        server = FakeServer(host, port)
        servers.append(server)
        return server

    _install(monkeypatch, smtp_factory=factory)
    send_email("S", "x", make_config(smtp_user="", smtp_from="from@example.com"), "")
    assert servers[0].login_args is None
    assert servers[0].sent is not None


def test_send_email_retries_transient_failure_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(emailer.time, "sleep", lambda s: sleeps.append(s))
    attempts = []
    server = FakeServer("smtp.example.com", 587)

    def factory(host, port, timeout=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise smtplib.SMTPConnectError(421, "busy")
        return server

    _install(monkeypatch, smtp_factory=factory)
    send_email("S", "x", make_config(), "secret")
    assert len(attempts) == 3
    assert server.sent is not None
    assert sleeps == [5, 5]


def test_send_email_raises_after_retries_exhausted(monkeypatch):
    monkeypatch.setattr(emailer.time, "sleep", lambda s: None)
    attempts = []

    def factory(host, port, timeout=None):
        attempts.append(1)
        raise smtplib.SMTPConnectError(421, "busy")

    _install(monkeypatch, smtp_factory=factory)
    with pytest.raises(smtplib.SMTPConnectError):
        send_email("S", "x", make_config(), "secret")
    assert len(attempts) == 3


def test_send_email_auth_error_not_retried(monkeypatch):
    monkeypatch.setattr(
        emailer.time, "sleep", lambda s: pytest.fail("must not retry auth errors")
    )
    attempts = []

    class AuthFailServer(FakeServer):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def factory(host, port, timeout=None):
        attempts.append(1)
        return AuthFailServer(host, port)

    _install(monkeypatch, smtp_factory=factory)
    with pytest.raises(smtplib.SMTPAuthenticationError):
        send_email("S", "x", make_config(), "wrong")
    assert len(attempts) == 1
