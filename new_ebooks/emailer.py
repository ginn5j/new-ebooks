from __future__ import annotations
import smtplib
import socket
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import keyring

from new_ebooks.config import EmailConfig

KEYRING_SERVICE = "new-ebooks-smtp"


def get_smtp_password(smtp_user: str) -> Optional[str]:
    return keyring.get_password(KEYRING_SERVICE, smtp_user)


def set_smtp_password(smtp_user: str, password: str) -> None:
    keyring.set_password(KEYRING_SERVICE, smtp_user, password)


def send_email(
    subject: str,
    html: str,
    email_config: EmailConfig,
    password: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_config.smtp_from or email_config.smtp_user
    msg["To"] = email_config.smtp_to
    msg.attach(MIMEText(html, "html", "utf-8"))

    port = email_config.smtp_port
    use_ssl = port == 465
    raw = msg.as_string()

    for attempt in range(3):
        try:
            if use_ssl:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(email_config.smtp_host, port, context=ctx, timeout=30) as server:
                    if email_config.smtp_user and password:
                        server.login(email_config.smtp_user, password)
                    server.sendmail(msg["From"], [email_config.smtp_to], raw)
            else:
                with smtplib.SMTP(email_config.smtp_host, port, timeout=30) as server:
                    if email_config.use_tls:
                        ctx = ssl.create_default_context()
                        server.starttls(context=ctx)
                    if email_config.smtp_user and password:
                        server.login(email_config.smtp_user, password)
                    server.sendmail(msg["From"], [email_config.smtp_to], raw)
            return
        # socket.timeout is a distinct class before Python 3.10
        except (TimeoutError, socket.timeout, ConnectionError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected):
            if attempt < 2:
                time.sleep(5)
                continue
            raise
