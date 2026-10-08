"""Optional email (AUTH-7, AUTH-10, DESIGN.md §8.4): forgot password, verified sign-ups, invites, notices."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import mail
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, BASE, USER_PASSWORD, Api


@pytest.fixture
def mailed(settings: Settings) -> Iterator[tuple[FastAPI, mail.MemoryMailer]]:
    """An app with SMTP configured, whose mail goes to an outbox instead."""
    app = create_app(settings.model_copy(update={"smtp_host": "smtp.example.com", "smtp_from": "rt@example.com"}))
    outbox = mail.MemoryMailer()
    app.state.mailer = outbox
    with TestClient(app, base_url=BASE) as main:
        app.state.test_portal = main.portal
        yield app, outbox


def sent(app: FastAPI, outbox: mail.MemoryMailer) -> list[mail.Message]:
    app.state.test_portal.call(mail.drain)
    return outbox.outbox


def link(message: mail.Message) -> str:
    match = re.search(r"https?://\S+", message.body)
    assert match, message.body
    return match.group(0)


def setup_admin(app: FastAPI) -> Api:
    admin = Api(app)
    created = admin.post("/api/auth/setup", json={"token": app.state.setup_token, "email": ADMIN_EMAIL,
                                                  "password": ADMIN_PASSWORD, "displayName": "Ada Admin"})
    assert created.status_code == 201
    return admin


def test_without_smtp_nothing_is_emailed(app: FastAPI, admin: Api) -> None:
    assert Api(app).get("/api/auth/registration").json()["emailEnabled"] is False
    assert Api(app).post("/api/auth/password/forgot", json={"email": ADMIN_EMAIL}).status_code == 404
    assert admin.post("/api/admin/invites", json={"email": "x@example.com"}).json()["emailed"] is False


def test_open_sign_ups_confirm_their_address(mailed) -> None:
    app, outbox = mailed
    setup_admin(app)
    assert Api(app).get("/api/auth/registration").json()["emailEnabled"] is True
    visitor = Api(app)
    body = {"email": "new@example.com", "password": USER_PASSWORD, "displayName": "New Person"}
    signed_up = visitor.post("/api/auth/register", json=body)
    assert signed_up.status_code == 202 and signed_up.json() == {"verificationSent": True, "email": "new@example.com"}
    assert visitor.get("/api/auth/me").status_code == 401  # no session until confirmed

    # the same answer for an address that already has an account, which gets a note instead (§8.4)
    again = Api(app).post("/api/auth/register", json=body)
    assert again.status_code == 202 and again.json() == signed_up.json()
    messages = sent(app, outbox)
    assert [m.subject for m in messages] == ["Confirm your email for Resume Tailor",
                                             "You already have a Resume Tailor account"]

    # signing in before confirming sends a fresh link
    early = Api(app).login("new@example.com", USER_PASSWORD)
    assert early.status_code == 403 and early.json()["code"] == "email_unverified"
    fresh = link(sent(app, outbox)[-1]).rsplit("/", 1)[-1]
    first = link(messages[0]).rsplit("/", 1)[-1]  # still works: people often click the first email
    assert Api(app).post("/api/auth/verify-email", json={"token": first}).status_code == 204
    assert Api(app).post("/api/auth/verify-email", json={"token": first}).status_code == 400  # used
    assert Api(app).post("/api/auth/verify-email", json={"token": fresh}).status_code == 400  # cleared once confirmed
    assert Api(app).login("new@example.com", USER_PASSWORD).json()["stage"] == "active"


def test_forgot_password_by_email(mailed) -> None:
    app, outbox = mailed
    setup_admin(app)
    stranger = Api(app)
    assert stranger.post("/api/auth/password/forgot", json={"email": "nobody@example.com"}).status_code == 202
    assert stranger.post("/api/auth/password/forgot", json={"email": ADMIN_EMAIL.upper()}).status_code == 202
    [message] = sent(app, outbox)
    assert message.to == ADMIN_EMAIL and message.subject == "Reset your Resume Tailor password"
    token = link(message).rsplit("/", 1)[-1]
    new_password = "a fresh and lengthy passphrase"
    reset = stranger.post("/api/auth/password-reset", json={"token": token, "newPassword": new_password})
    assert reset.status_code == 204
    assert Api(app).login(ADMIN_EMAIL, new_password).status_code == 200
    for _ in range(12):  # limited per network
        last = stranger.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    assert last.status_code == 429


def test_invites_and_address_changes_are_emailed(mailed) -> None:
    app, outbox = mailed
    admin = setup_admin(app)
    invite = admin.post("/api/admin/invites", json={"email": "friend@example.com"})
    assert invite.status_code == 201 and invite.json()["emailed"] is True
    message = sent(app, outbox)[-1]
    assert message.to == "friend@example.com" and "Ada Admin invited you" in message.body
    assert link(message) == invite.json()["url"]
    # registering through the invite needs no confirmation: the link went to that address
    friend = Api(app)
    token = invite.json()["url"].rsplit("/", 1)[-1]
    joined = friend.post("/api/auth/register", json={"email": "friend@example.com", "password": USER_PASSWORD,
                                                     "displayName": "Friend", "inviteToken": token})
    assert joined.status_code == 201 and joined.json()["stage"] == "active"

    changed = admin.patch("/api/account/profile", json={"email": "ada@example.com", "currentPassword": ADMIN_PASSWORD})
    assert changed.status_code == 200
    notice = sent(app, outbox)[-1]
    assert notice.to == ADMIN_EMAIL and "ada@example.com" in notice.body


def test_mail_failures_are_logged_without_links(caplog) -> None:
    class Broken:
        async def send(self, message: mail.Message) -> None:
            raise OSError("connection refused")

    async def run() -> None:
        mail.send_later(Broken(), mail.password_reset("a@example.com", "https://x/reset-password/SECRET"))
        await mail.drain()

    import asyncio
    asyncio.run(run())
    assert "could not send" in caplog.text and "SECRET" not in caplog.text


def test_the_smtp_mailer_speaks_smtp(settings: Settings) -> None:
    """A real send, to a minimal SMTP server on localhost (plain SMTP: the "none" security mode for local relays)."""
    import socket
    import threading

    received: list[str] = []
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve() -> None:
        conn, _ = server.accept()
        stream = conn.makefile("rwb")

        def reply(line: str) -> None:
            stream.write(f"{line}\r\n".encode())
            stream.flush()

        reply("220 test ESMTP")
        while line := stream.readline().decode():
            command = line.strip().upper()
            if command.startswith(("EHLO", "HELO")):
                reply("250 test")
            elif command.startswith(("MAIL", "RCPT", "RSET", "NOOP")):
                reply("250 OK")
            elif command == "DATA":
                reply("354 go ahead")
                body = []
                while (data := stream.readline().decode()) not in (".\r\n", ""):
                    body.append(data)
                received.append("".join(body))
                reply("250 queued")
            elif command == "QUIT":
                reply("221 bye")
                break
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    mailer = mail.SmtpMailer(settings.model_copy(update={"smtp_host": "127.0.0.1", "smtp_port": port,
                                                         "smtp_from": "rt@example.com", "smtp_security": "none"}))
    import asyncio
    asyncio.run(mailer.send(mail.password_reset("jo@example.com", "https://rt.example/reset-password/abc")))
    thread.join(5)
    server.close()
    [message] = received
    assert "To: jo@example.com" in message and "From: rt@example.com" in message
    assert "Subject: Reset your Resume Tailor password" in message and "reset-password/abc" in message
