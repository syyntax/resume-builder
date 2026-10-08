"""Account → AI: the user's own API key, model choice, spending cap and usage (DESIGN.md §4.2, §8.6)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMError
from app.api.common import confirm_password, month_range
from app.auth.audit import audit
from app.auth.deps import current_user, get_limits, get_settings
from app.auth.ratelimit import Limits
from app.auth.sessions import AuthContext
from app.config import Settings
from app.db.engine import get_db
from app.db.models import AiCall, Application, ImportJob, JobPosting
from app.db.types import utcnow
from app.errors import ApiError
from app.keys import service as keys
from app.models.api import (
    AiSettingsIn,
    AiSettingsOut,
    ApiKeyIn,
    ApiKeyStatusOut,
    ItemUsageOut,
    MonthUsageOut,
    PasswordConfirmIn,
    SpendOut,
    StageUsageOut,
    UsageOut,
)
from app.pipeline import usage
from app.secrets import DecryptionError
from app.services import settings_store

router = APIRouter(prefix="/api/account", tags=["account-ai"])




async def _verify_with_provider(request: Request, api_key: str) -> None:
    try:
        await request.app.state.llm_factory(api_key).verify()
    except LLMError as exc:
        if exc.code == "key_rejected":
            raise ApiError(400, "Anthropic didn't accept this key. Check that you copied all of it and that it's "
                                "active in the Anthropic Console.",
                           errors=[{"field": "apiKey", "message": "rejected"}],
                           extra={"code": "key_rejected"}) from None
        raise ApiError(502, f"Couldn't check the key with Anthropic: {exc.message}") from None


async def _status(db: AsyncSession, ctx: AuthContext, settings: Settings) -> ApiKeyStatusOut:
    row = await keys.get_row(db, ctx.user.id)
    shared = await keys.shared_key_enabled(db, settings)
    using = "own" if row and row.status == "valid" else ("shared" if shared else None)
    if row is None:
        return ApiKeyStatusOut(has_key=False, shared_key_available=shared, using=using)  # type: ignore[arg-type]
    return ApiKeyStatusOut(has_key=True, hint=row.hint, status=row.status, verified_at=row.verified_at,  # type: ignore[arg-type]
                           last_used_at=row.last_used_at, shared_key_available=shared, using=using)  # type: ignore[arg-type]


@router.get("/api-key", response_model=ApiKeyStatusOut)
async def get_api_key(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db),
                      settings: Settings = Depends(get_settings)) -> ApiKeyStatusOut:
    return await _status(db, ctx, settings)


@router.put("/api-key", response_model=ApiKeyStatusOut)
async def save_api_key(body: ApiKeyIn, request: Request, ctx: AuthContext = Depends(current_user),
                       db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
                       limits: Limits = Depends(get_limits)) -> ApiKeyStatusOut:
    await confirm_password(ctx, body.password, limits)
    key = keys.check_format(body.api_key)
    await _verify_with_provider(request, key)
    replaced = await keys.get_row(db, ctx.user.id) is not None
    await keys.store(db, ctx.user, key, settings)
    await audit(db, "account.apikey.add", request, actor_id=ctx.user.id, target_id=ctx.user.id, replaced=replaced)
    await db.commit()
    return await _status(db, ctx, settings)


@router.post("/api-key/test", response_model=ApiKeyStatusOut)
async def test_api_key(request: Request, ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db),
                       settings: Settings = Depends(get_settings)) -> ApiKeyStatusOut:
    row = await keys.get_row(db, ctx.user.id)
    if row is None:
        raise ApiError(404, "You haven't added an API key.")
    try:
        api_key = keys.decrypt(row, settings)
    except DecryptionError:
        raise ApiError(409, "Your saved key can't be read anymore (the server's secret changed). Enter it again.",
                       extra={"code": "key_unreadable"}) from None
    try:
        await _verify_with_provider(request, api_key)
    except ApiError as exc:
        if (exc.extra or {}).get("code") == "key_rejected":
            row.status = "invalid"
            await audit(db, "account.apikey.rejected", request, actor_id=ctx.user.id, target_id=ctx.user.id)
            await db.commit()
        raise
    row.status, row.verified_at = "valid", utcnow()
    await db.commit()
    return await _status(db, ctx, settings)


@router.delete("/api-key", status_code=204)
async def delete_api_key(body: PasswordConfirmIn, request: Request, ctx: AuthContext = Depends(current_user),
                         db: AsyncSession = Depends(get_db), limits: Limits = Depends(get_limits)) -> Response:
    await confirm_password(ctx, body.password, limits)
    row = await keys.get_row(db, ctx.user.id)
    if row is None:
        raise ApiError(404, "You haven't added an API key.")
    await db.delete(row)
    await audit(db, "account.apikey.remove", request, actor_id=ctx.user.id, target_id=ctx.user.id)
    await db.commit()
    return Response(status_code=204)


# ---- model and cap ----------------------------------------------------------------------------------


async def _ai_settings(db: AsyncSession, ctx: AuthContext, settings: Settings) -> AiSettingsOut:
    policy = await settings_store.model_policy(db)
    return AiSettingsOut(model=policy.choose(ctx.user.preferred_model), allowed_models=policy.allowed,
                         default_model=policy.default, monthly_cap_usd=ctx.user.monthly_cap_usd,
                         default_cap_usd=settings.default_monthly_cap_usd)


@router.get("/ai-settings", response_model=AiSettingsOut)
async def get_ai_settings(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db),
                          settings: Settings = Depends(get_settings)) -> AiSettingsOut:
    return await _ai_settings(db, ctx, settings)


@router.put("/ai-settings", response_model=AiSettingsOut)
async def update_ai_settings(body: AiSettingsIn, request: Request, ctx: AuthContext = Depends(current_user),
                             db: AsyncSession = Depends(get_db),
                             settings: Settings = Depends(get_settings)) -> AiSettingsOut:
    if body.model is not None:
        policy = await settings_store.model_policy(db)
        if body.model not in policy.allowed:
            raise ApiError(422, "That model isn't available on this deployment.",
                           errors=[{"field": "model", "message": "not allowed"}])
        ctx.user.preferred_model = body.model
    if body.reset_cap or body.monthly_cap_usd is not None:
        ctx.user.monthly_cap_usd = None if body.reset_cap else body.monthly_cap_usd
        await audit(db, "account.cap.change", request, actor_id=ctx.user.id, target_id=ctx.user.id,
                    cap=ctx.user.monthly_cap_usd)
    await db.commit()
    return await _ai_settings(db, ctx, settings)


@router.get("/usage", response_model=UsageOut)
async def get_usage(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db),
                    settings: Settings = Depends(get_settings),
                    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> UsageOut:
    """Spending against this month's caps, and tokens and cost for a month by stage and by application or
    import, plus the last 12 months (KEY-5)."""
    def spend(status: usage.CapStatus) -> SpendOut:
        percent = round(100 * status.spent / status.cap, 1) if status.cap else None
        return SpendOut(spent_usd=round(status.spent, 4), cap_usd=status.cap, percent=percent)

    start, end = month_range(month)
    own = await usage.cap_status(db, ctx.user, "own", settings)
    shared = await usage.cap_status(db, ctx.user, "shared", settings)
    show_shared = shared.spent > 0 or await keys.shared_key_enabled(db, settings)
    rows = (await db.execute(
        select(AiCall.stage, func.count(), func.sum(AiCall.input_tokens + AiCall.cache_read_tokens
                                                     + AiCall.cache_write_tokens),
               func.sum(AiCall.output_tokens), func.sum(AiCall.est_cost_usd))
        .where(AiCall.owner_id == ctx.user.id, AiCall.created_at >= start, AiCall.created_at < end)
        .group_by(AiCall.stage).order_by(AiCall.stage)
    )).all()
    items = (await db.execute(
        select(AiCall.application_id, AiCall.import_job_id, JobPosting.title, JobPosting.company,
               ImportJob.source_name, func.count(), func.sum(AiCall.est_cost_usd))
        .outerjoin(Application, Application.id == AiCall.application_id)
        .outerjoin(JobPosting, JobPosting.id == Application.job_id)
        .outerjoin(ImportJob, ImportJob.id == AiCall.import_job_id)
        .where(AiCall.owner_id == ctx.user.id, AiCall.created_at >= start, AiCall.created_at < end)
        .group_by(AiCall.application_id, AiCall.import_job_id, JobPosting.title, JobPosting.company,
                  ImportJob.source_name)
    )).all()
    by_item = []
    for app_id, import_id, title, company, source, calls, cost in items:
        amount = round(float(cost or 0), 4)
        if import_id or source:
            by_item.append(ItemUsageOut(kind="import", id=import_id, label=f"Import: {source}" if source
                                        else "A deleted import", calls=calls, cost_usd=amount))
        else:  # an application, or one since deleted (its calls still count toward the month)
            label = " at ".join(p for p in (title, company) if p) or ("Application" if app_id
                                                                      else "Deleted applications")
            by_item.append(ItemUsageOut(kind="application", id=app_id, label=label, calls=calls, cost_usd=amount))
    by_item.sort(key=lambda i: -i.cost_usd)
    year_ago = (usage.month_start() - timedelta(days=330)).replace(day=1)
    history: dict[str, list[float]] = {}
    for created, cost in (await db.execute(select(AiCall.created_at, AiCall.est_cost_usd).where(
            AiCall.owner_id == ctx.user.id, AiCall.created_at >= year_ago))).all():
        bucket = history.setdefault(created.strftime("%Y-%m"), [0, 0.0])
        bucket[0] += 1
        bucket[1] += float(cost or 0)
    return UsageOut(
        month=start.strftime("%Y-%m"),
        own=spend(own),
        shared=spend(shared) if show_shared else None,
        by_stage=[StageUsageOut(stage=s, calls=c, input_tokens=int(i or 0), output_tokens=int(o or 0),
                                cost_usd=round(float(cost or 0), 4)) for s, c, i, o, cost in rows],
        by_item=by_item,
        months=[MonthUsageOut(month=m, calls=int(v[0]), cost_usd=round(v[1], 4))
                for m, v in sorted(history.items(), reverse=True)],
    )
