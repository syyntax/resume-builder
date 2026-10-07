"""Owner-scoped data access for master résumés.

Every query adds ``owner_id = :owner``. There is deliberately no unscoped "get by id": another user's
master simply doesn't exist from the caller's point of view (the API answers 404).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MasterResume, MasterResumeVersion
from app.db.types import utcnow


class MasterRepository:
    def __init__(self, db: AsyncSession, owner_id: str) -> None:
        self.db, self.owner_id = db, owner_id

    async def list(self) -> list[tuple[MasterResume, int, MasterResumeVersion | None]]:
        counts = (
            select(MasterResumeVersion.master_id, func.count().label("n"))
            .where(MasterResumeVersion.owner_id == self.owner_id)
            .group_by(MasterResumeVersion.master_id)
            .subquery()
        )
        rows = (
            await self.db.execute(
                select(MasterResume, func.coalesce(counts.c.n, 0), MasterResumeVersion)
                .outerjoin(counts, counts.c.master_id == MasterResume.id)
                .outerjoin(
                    MasterResumeVersion,
                    (MasterResumeVersion.id == MasterResume.current_version_id)
                    & (MasterResumeVersion.owner_id == self.owner_id),
                )
                .where(MasterResume.owner_id == self.owner_id)
                .order_by(MasterResume.updated_at.desc())
            )
        ).all()
        return [(m, int(n), v) for m, n, v in rows]

    async def get(self, master_id: str) -> MasterResume | None:
        return (
            await self.db.execute(
                select(MasterResume).where(MasterResume.id == master_id, MasterResume.owner_id == self.owner_id)
            )
        ).scalar_one_or_none()

    async def version_count(self, master_id: str) -> int:
        stmt = select(func.count()).where(
            MasterResumeVersion.master_id == master_id, MasterResumeVersion.owner_id == self.owner_id
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def get_version(self, master_id: str, version_id: str) -> MasterResumeVersion | None:
        return (
            await self.db.execute(
                select(MasterResumeVersion).where(
                    MasterResumeVersion.id == version_id,
                    MasterResumeVersion.master_id == master_id,
                    MasterResumeVersion.owner_id == self.owner_id,
                )
            )
        ).scalar_one_or_none()

    async def current_version(self, master: MasterResume) -> MasterResumeVersion | None:
        if master.current_version_id is None:
            return None
        return await self.get_version(master.id, master.current_version_id)

    async def list_versions(self, master_id: str) -> list[MasterResumeVersion]:
        return list(
            (
                await self.db.execute(
                    select(MasterResumeVersion)
                    .where(MasterResumeVersion.master_id == master_id, MasterResumeVersion.owner_id == self.owner_id)
                    .order_by(MasterResumeVersion.version_number.desc())
                )
            ).scalars()
        )

    async def create(
        self, label: str, content: dict[str, Any], sha256: str, warnings: list[dict[str, str]]
    ) -> tuple[MasterResume, MasterResumeVersion]:
        now = utcnow()
        master = MasterResume(owner_id=self.owner_id, label=label, created_at=now, updated_at=now)
        self.db.add(master)
        await self.db.flush()
        version = await self.add_version(master, content, sha256, warnings)
        return master, version

    async def add_version(
        self, master: MasterResume, content: dict[str, Any], sha256: str, warnings: list[dict[str, str]]
    ) -> MasterResumeVersion:
        latest = (
            await self.db.execute(
                select(func.max(MasterResumeVersion.version_number)).where(
                    MasterResumeVersion.master_id == master.id, MasterResumeVersion.owner_id == self.owner_id
                )
            )
        ).scalar_one()
        version = MasterResumeVersion(
            master_id=master.id,
            owner_id=self.owner_id,
            version_number=(latest or 0) + 1,
            content=content,
            sha256=sha256,
            schema_version=str((content.get("meta") or {}).get("schemaVersion", "1.0")),
            warnings=warnings,
            created_at=utcnow(),
        )
        self.db.add(version)
        await self.db.flush()
        master.current_version_id = version.id
        master.updated_at = version.created_at
        return version

    async def delete(self, master: MasterResume) -> None:
        await self.db.execute(
            delete(MasterResume).where(MasterResume.id == master.id, MasterResume.owner_id == self.owner_id)
        )

    async def all_with_versions(self) -> list[tuple[MasterResume, list[MasterResumeVersion]]]:
        masters = (
            await self.db.execute(select(MasterResume).where(MasterResume.owner_id == self.owner_id))
        ).scalars().all()
        return [(m, await self.list_versions(m.id)) for m in masters]
