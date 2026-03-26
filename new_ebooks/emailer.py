from __future__ import annotations
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import keyring

from new_ebooks.config import EmailConfig
from new_ebooks.scraper import EBook

KEYRING_SERVICE = "new-ebooks-smtp"


def get_smtp_password(smtp_user: str) -> Optional[str]:
    return keyring.get_password(KEYRING_SERVICE, smtp_user)


def set_smtp_password(smtp_user: str, password: str) -> None:
    keyring.set_password(KEYRING_SERVICE, smtp_user, password)


def send_email(
    books: list[EBook],
    last_checked: str,
    library_name: str,
    library_base_url: str,
    email_config: EmailConfig,
    password: str,
    html: str,
) -> None:
    count = len(books)
    if count == 0:
        subject = "No new eBooks"
    elif count == 1:
        subject = "1 new eBook"
    else:
        subject = f"{count} new eBooks"
    if last_checked:
        subject += f" since {last_checked}"
    if library_name:
        subject += f" — {library_name}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_config.smtp_from or email_config.smtp_user
    msg["To"] = email_config.smtp_to
    msg.attach(MIMEText(html, "html", "utf-8"))

    port = email_config.smtp_port
    use_ssl = port == 465

    if use_ssl:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(email_config.smtp_host, port, context=ctx) as server:
            if email_config.smtp_user and password:
                server.login(email_config.smtp_user, password)
            server.sendmail(msg["From"], [email_config.smtp_to], msg.as_string())
    else:
        with smtplib.SMTP(email_config.smtp_host, port) as server:
            if email_config.use_tls:
                ctx = ssl.create_default_context()
                server.starttls(context=ctx)
            if email_config.smtp_user and password:
                server.login(email_config.smtp_user, password)
            server.sendmail(msg["From"], [email_config.smtp_to], msg.as_string())
