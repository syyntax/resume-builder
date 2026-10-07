"""Security audit log (DESIGN.md §8.7). Never pass document content or secrets as details."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import client_ip, user_agent
from app.db.models import AuditLog

log = logging.getLogger("resume_tailor.audit")


async def audit(
    db: AsyncSession,
    event: str,
    request: Request | None = None,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    **details: Any,
) -> None:
    db.add(
        AuditLog(
            event=event,
            actor_user_id=actor_id,
            target_user_id=target_id,
            ip=client_ip(request) if request else None,
            user_agent=user_agent(request) if request else None,
            details=details,
        )
    )
    log.info("audit %s actor=%s target=%s", event, actor_id, target_id)
