"""Health check, JSON Schema and example documents. All public."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db.engine import get_db
from app.models.master import json_schema

router = APIRouter(tags=["meta"])
EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "masters" / "example_master.json"


@cache
def example_master() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


@router.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001  (report, don't raise, from a health check)
        database = "error"
    status = 200 if database == "ok" else 503
    return JSONResponse({"status": "ok" if status == 200 else "degraded", "database": database,
                         "version": __version__}, status_code=status)


@router.get("/api/schema/master-resume")
@router.get("/schema/master-resume.schema.json", include_in_schema=False)
async def master_schema() -> JSONResponse:
    return JSONResponse(json_schema(), media_type="application/schema+json")


@router.get("/api/schema/master-resume/example")
async def master_example() -> JSONResponse:
    return JSONResponse(example_master())
