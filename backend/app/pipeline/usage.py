"""Usage ledger and monthly spending caps (DESIGN.md §8.6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMError, LLMResult, Usage
from app.ai.pricing import cost_usd, load_prices
from app.config import Settings
from app.db.models import AiCall, User
from app.errors import ApiError

KeySource = Literal["own", "shared"]

# Rough per-stage token estimates for the pre-flight cap check (output includes thinking).
STAGE_ESTIMATES = {"analyze": (14_000, 6_000), "tailor": (17_000, 12_000), "import": (15_000, 12_000)}


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def prices(settings: Settings):  # noqa: ANN201
    return load_prices(settings.pricing_file) if settings.pricing_file else load_prices()


def estimate_job_cost(model: str, settings: Settings, stages: tuple[str, ...] = ("analyze", "tailor")) -> float:
    table = prices(settings)
    return sum(cost_usd(model, table, input_tokens=STAGE_ESTIMATES[s][0], output_tokens=STAGE_ESTIMATES[s][1])
               for s in stages)


def cap_for(user: User, source: KeySource, settings: Settings) -> float | None:
    """The monthly cap in USD for this key source, or None when unlimited (a cap of 0)."""
    value = user.monthly_cap_usd if source == "own" else user.shared_cap_usd
    cap = settings.default_monthly_cap_usd if value is None else value
    return None if cap <= 0 else cap


async def month_spend(db: AsyncSession, owner_id: str, source: KeySource | None = None) -> float:
    stmt = select(func.coalesce(func.sum(AiCall.est_cost_usd), 0.0)).where(
        AiCall.owner_id == owner_id, AiCall.created_at >= month_start()
    )
    if source:
        stmt = stmt.where(AiCall.key_source == source)
    return float((await db.execute(stmt)).scalar_one())


@dataclass
class CapStatus:
    source: KeySource
    spent: float
    cap: float | None

    @property
    def remaining(self) -> float | None:
        return None if self.cap is None else max(0.0, self.cap - self.spent)


async def cap_status(db: AsyncSession, user: User, source: KeySource, settings: Settings) -> CapStatus:
    return CapStatus(source, await month_spend(db, user.id, source), cap_for(user, source, settings))


async def ensure_within_cap(db: AsyncSession, user: User, source: KeySource, settings: Settings,
                            estimate: float) -> None:
    status = await cap_status(db, user, source, settings)
    if status.cap is not None and status.spent + estimate > status.cap:
        who = "your monthly cap" if source == "own" else "your monthly allowance on the shared key"
        raise ApiError(
            409,
            f"This would go over {who} (${status.spent:.2f} of ${status.cap:.2f} used this month). "
            + ("Raise it in Account → AI, or wait until next month." if source == "own"
               else "Add your own API key, ask an admin to raise it, or wait until next month."),
            extra={"code": "cap_reached"},
        )


async def record_call(db: AsyncSession, *, owner_id: str, application_id: str | None, stage: str, model: str,
                      key_source: KeySource, prompt_version: str, settings: Settings,
                      result: LLMResult | None = None, error: LLMError | None = None,
                      import_job_id: str | None = None) -> AiCall | None:
    usage: Usage | None = result.usage if result else (error.usage if error else None)
    if usage is None:  # nothing was billed (the request never produced output)
        return None
    served = (result.model if result else error.model if error else None) or model
    call = AiCall(
        owner_id=owner_id, application_id=application_id, import_job_id=import_job_id, stage=stage, model=served,
        key_source=key_source, prompt_version=prompt_version,
        request_id=result.request_id if result else (error.request_id if error else None),
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens, cache_write_tokens=usage.cache_write_tokens,
        stop_reason=result.stop_reason if result else (error.code if error else None),
        duration_ms=result.duration_ms if result else (error.duration_ms if error else 0),
        est_cost_usd=cost_usd(served, prices(settings), input_tokens=usage.input_tokens,
                              output_tokens=usage.output_tokens, cache_read_tokens=usage.cache_read_tokens,
                              cache_write_tokens=usage.cache_write_tokens),
        error=error.code if error else None,
    )
    db.add(call)
    return call
