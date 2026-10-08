"""Optional email (SMTP): password resets, invites, address verification and security notices.

Without SMTP settings nothing is sent and the app works as before (admins share links themselves). Messages are
plain text, sent in the background: a slow or failing mail server never slows a response down or reveals
anything through its timing, and a failure is logged without the message's link.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings

log = logging.getLogger("resume_tailor.mail")


@dataclass
class Message:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    async def send(self, message: Message) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_blocking(self, message: Message) -> None:
        s = self.settings
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = s.smtp_from, message.to, message.subject
        email.set_content(message.body)
        context = ssl.create_default_context()
        if s.smtp_security == "ssl":
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=context) as smtp:
                self._login(smtp)
                smtp.send_message(email)
            return
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_security == "starttls":
                smtp.starttls(context=context)
            self._login(smtp)
            smtp.send_message(email)

    def _login(self, smtp: smtplib.SMTP) -> None:
        if self.settings.smtp_user:
            password = self.settings.smtp_password.get_secret_value() if self.settings.smtp_password else ""
            smtp.login(self.settings.smtp_user, password)

    async def send(self, message: Message) -> None:
        await asyncio.to_thread(self._send_blocking, message)


@dataclass
class MemoryMailer:
    """For tests and development: keeps what would have been sent."""

    outbox: list[Message] = field(default_factory=list)

    async def send(self, message: Message) -> None:
        self.outbox.append(message)


_background: set[asyncio.Task[None]] = set()


def send_later(mailer: Mailer | None, message: Message) -> None:
    """Send without waiting. Errors are logged (subject only: links in messages are secrets)."""
    if mailer is None:
        return

    async def run() -> None:
        try:
            await mailer.send(message)
        except Exception as exc:  # noqa: BLE001  (any SMTP or network failure)
            log.warning("could not send %r: %s", message.subject, type(exc).__name__)

    task = asyncio.get_running_loop().create_task(run())
    _background.add(task)
    task.add_done_callback(_background.discard)


async def drain() -> None:
    """Wait for messages being sent (tests, shutdown)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


# ---- messages ----------------------------------------------------------------------------------------------

SIGN_OFF = "\n\n— Resume Tailor\n(You can ignore this message if you didn't expect it.)"


def password_reset(to: str, url: str) -> Message:
    return Message(to, "Reset your Resume Tailor password",
                   f"Someone (hopefully you) asked to reset the password for {to}.\n\nChoose a new password here "
                   f"within 30 minutes:\n{url}\n\nResetting it signs you out everywhere." + SIGN_OFF)


def verify_address(to: str, url: str) -> Message:
    return Message(to, "Confirm your email for Resume Tailor",
                   f"Confirm {to} to finish creating your account:\n{url}\n\nThe link works for 24 hours." + SIGN_OFF)


def already_registered(to: str, login_url: str, forgot_url: str) -> Message:
    return Message(to, "You already have a Resume Tailor account",
                   f"Someone tried to sign up with {to}, which already has an account.\n\nSign in: {login_url}\n"
                   f"Forgot your password? {forgot_url}" + SIGN_OFF)


def invite(to: str, url: str, inviter: str) -> Message:
    return Message(to, "You're invited to Resume Tailor",
                   f"{inviter} invited you to Resume Tailor, a tool for tailoring your résumé and cover letter to "
                   f"each job.\n\nCreate your account here within 7 days:\n{url}" + SIGN_OFF)


def email_changed(to: str, new_email: str) -> Message:
    return Message(to, "Your Resume Tailor email was changed",
                   f"The email for your Resume Tailor account was changed from {to} to {new_email}.\n\nIf you "
                   "didn't do this, contact your administrator right away." + SIGN_OFF)
