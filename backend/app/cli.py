"""`resume-tailor` command-line tool (DESIGN.md ADM-6). Run inside the container, e.g.

    docker compose exec app resume-tailor admin create --email you@example.com --name "Your Name"
    docker compose exec app resume-tailor setup-token
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import passwords
from app.auth.audit import audit
from app.auth.bootstrap import ensure_setup_token
from app.auth.sessions import revoke_all
from app.config import Settings
from app.db.engine import build_engine, run_migrations
from app.db.models import User, UserApiKey
from app.db.types import utcnow
from app.keys.service import decrypt, secret_box
from app.secrets import DecryptionError
from app.services.users import find_by_email, is_valid_email, normalize_email, would_remove_last_admin

REPO_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"


def _read_password(from_stdin: bool, *, email: str, name: str) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("New password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise SystemExit("Passwords don't match.")
    problems = passwords.policy_errors(password, email=email, display_name=name)
    if problems:
        raise SystemExit("Password rejected: " + " ".join(problems))
    return password


async def _with_db(settings: Settings, fn: Callable[[AsyncSession], Awaitable[int]]) -> int:
    if settings.is_sqlite:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(run_migrations, settings.db_url_sync)
    passwords.configure(settings.argon2_profile)
    engine, sessionmaker = build_engine(settings)
    try:
        async with sessionmaker() as db:
            return await fn(db)
    finally:
        await engine.dispose()


async def _admin_create(db: AsyncSession, args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    if not is_valid_email(email):
        print("Invalid email address.", file=sys.stderr)
        return 2
    if await find_by_email(db, email):
        print(f"{email} already exists. Use `admin reset-password` or change their role in the web UI.",
              file=sys.stderr)
        return 1
    password = _read_password(args.password_stdin, email=email, name=args.name)
    user = User(email=email, display_name=args.name, password_hash=passwords.hash_password(password),
                role="admin", status="active", created_at=utcnow())
    db.add(user)
    await db.flush()
    await audit(db, "cli.admin.create", target_id=user.id)
    await db.commit()
    print(f"Created admin {email}.")
    return 0


async def _admin_reset_password(db: AsyncSession, args: argparse.Namespace) -> int:
    user = await find_by_email(db, args.email)
    if user is None:
        print("No such user.", file=sys.stderr)
        return 1
    user.password_hash = passwords.hash_password(
        _read_password(args.password_stdin, email=user.email, name=user.display_name)
    )
    await revoke_all(db, user.id)
    await audit(db, "cli.password.reset", target_id=user.id)
    await db.commit()
    print(f"Password reset for {user.email}; all of their sessions were signed out.")
    return 0


async def _admin_set_status(db: AsyncSession, args: argparse.Namespace, status: str) -> int:
    user = await find_by_email(db, args.email)
    if user is None:
        print("No such user.", file=sys.stderr)
        return 1
    if status == "disabled" and await would_remove_last_admin(db, user, new_role=None, new_status=status):
        print("Refusing to disable the last active admin.", file=sys.stderr)
        return 1
    user.status = status
    await revoke_all(db, user.id)
    await audit(db, f"cli.user.{'disable' if status == 'disabled' else 'enable'}", target_id=user.id)
    await db.commit()
    print(f"{user.email} is now {status}.")
    return 0


async def _admin_list(db: AsyncSession, _: argparse.Namespace) -> int:
    for user in (await db.execute(select(User).order_by(User.created_at))).scalars():
        print(f"{user.email:40} {user.role:6} {user.status:9} {user.display_name}")
    return 0


async def _setup_token(db: AsyncSession, _: argparse.Namespace) -> int:
    token = await ensure_setup_token(db)
    if token is None:
        print("Setup is already complete (users exist). Use `admin create` to add another admin.")
        return 1
    print(f"Setup token: {token}\n(any previous setup token no longer works)")
    return 0


async def _keys_rotate(db: AsyncSession, settings: Settings) -> int:
    if settings.previous_secret_key() is None:
        print("Set APP_SECRET_KEY to the new secret and APP_SECRET_KEY_PREVIOUS to the old one, then rerun.",
              file=sys.stderr)
        return 2
    box = secret_box(settings)
    rows = (await db.execute(select(UserApiKey).where(UserApiKey.key_fingerprint != box.current_fingerprint))).scalars()
    rotated = unreadable = 0
    for row in rows:
        try:
            plaintext = decrypt(row, settings)
        except DecryptionError:
            unreadable += 1
            continue
        sealed = box.seal(plaintext, bound_to=row.user_id)
        row.ciphertext, row.nonce, row.key_fingerprint = sealed.ciphertext, sealed.nonce, sealed.key_fingerprint
        rotated += 1
    await audit(db, "cli.keys.rotate", rotated=rotated, unreadable=unreadable)
    await db.commit()
    print(f"Re-encrypted {rotated} API key(s) under the new secret."
          + (f" {unreadable} couldn't be read; those users must enter their key again." if unreadable else ""))
    print("You can now remove APP_SECRET_KEY_PREVIOUS.")
    return 0


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def _schema_export(args: argparse.Namespace) -> int:
    from app.api.meta import example_master
    from app.models.master import json_schema

    out = Path(args.out_dir)
    _write_json(out / "master-resume.schema.json", json_schema())
    _write_json(out / "examples" / "master-resume.example.json", example_master())
    return 0


def _openapi(args: argparse.Namespace) -> int:
    from app.main import create_app

    app = create_app(Settings(enable_api_docs=True, app_secret_key="x" * 32))  # type: ignore[arg-type]
    _write_json(Path(args.out), app.openapi())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-tailor", description="Resume Tailor administration")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("admin", help="manage accounts").add_subparsers(dest="action", required=True)
    create = admin.add_parser("create", help="create an admin account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    reset = admin.add_parser("reset-password", help="set a new password and sign the user out everywhere")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-stdin", action="store_true")
    for action in ("disable", "enable"):
        admin.add_parser(action, help=f"{action} an account").add_argument("--email", required=True)
    admin.add_parser("list", help="list accounts")

    sub.add_parser("setup-token", help="print a new first-run setup token (only before the first account)")
    keys = sub.add_parser("keys", help="manage stored API keys").add_subparsers(dest="action", required=True)
    keys.add_parser("rotate", help="re-encrypt stored keys after changing APP_SECRET_KEY")

    schema = sub.add_parser("schema", help="export the master résumé JSON Schema and example")
    schema.add_argument("--out-dir", default=str(REPO_SCHEMA_DIR))

    openapi = sub.add_parser("openapi", help="write the OpenAPI document (used to generate frontend types)")
    openapi.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "schema":
        return _schema_export(args)
    if args.command == "openapi":
        return _openapi(args)

    settings = Settings()
    handlers: dict[str, Callable[[AsyncSession], Awaitable[int]]] = {
        "setup-token": lambda db: _setup_token(db, args),
        "keys": lambda db: _keys_rotate(db, settings),
    }
    if args.command == "admin":
        handlers["admin"] = {
            "create": lambda db: _admin_create(db, args),
            "reset-password": lambda db: _admin_reset_password(db, args),
            "disable": lambda db: _admin_set_status(db, args, "disabled"),
            "enable": lambda db: _admin_set_status(db, args, "active"),
            "list": lambda db: _admin_list(db, args),
        }[args.action]
    return asyncio.run(_with_db(settings, handlers[args.command]))


if __name__ == "__main__":
    raise SystemExit(main())
