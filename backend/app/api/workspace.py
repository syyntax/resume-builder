"""The application workspace (DESIGN.md §4.6–4.9, §12.2–12.3): edit the résumé and the cover letter, ask for
AI refinements, generate or regenerate the letter, re-run the claim audit, and edit the job analysis."""

from __future__ import annotations

import copy
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.ai import stages
from app.ai.schemas import JobAnalysis
from app.api.applications import ApplicationRepository, _out, get_repo, start
from app.auth.deps import current_user, get_settings
from app.auth.sessions import AuthContext
from app.config import Settings
from app.db.models import Application, Document, DocumentRevision, JobPosting
from app.db.types import utcnow
from app.errors import ApiError
from app.keys import service as keys
from app.models.api import (
    AnalysisEditIn,
    ApplicationOut,
    CoverLetterOptions,
    DocumentIn,
    FitIn,
    FitOut,
    LetterRefineIn,
    LetterRefineOut,
    RefineIn,
    RefineOut,
    RegenerateIn,
    RestoreOut,
    SuggestedChange,
    SuggestedItem,
)
from app.pipeline import usage
from app.pipeline.editing import annotate_resume, normalize_resume
from app.pipeline.fit import fit_resume, measure
from app.pipeline.hydrate import MasterIndex
from app.pipeline.letter import annotate_letter, normalize_letter
from app.pipeline.run import ACTIVE, Context, run_audit, run_letter
from app.pipeline.validators import build_term_groups, check_text, source_text
from app.render.service import render_letter_as, render_resume_as, stored_design

router = APIRouter(prefix="/api/applications", tags=["workspace"])
MAX_DOCUMENT_CHARS = 1_000_000


async def _context(request: Request, repo: ApplicationRepository, user: Any, application_id: str) -> Context:
    application, job, version, _ = await repo.get(application_id)
    if application.status in ACTIVE:
        raise ApiError(409, "This application is still generating. Wait for it to finish.")
    if not job.analysis:
        raise ApiError(409, "This application has no job analysis yet.")
    return Context(request.app, repo.db, application, user, job, version)


async def _refine_call(ctx: Context, stage: str, runner: Any) -> tuple[Any, float]:
    """One refine call: cap check, then the call with its usage recorded; returns the value and its cost."""
    await ctx.llm()
    await ctx.ensure_cap("condense" if stage == "condense" else "refine")
    before = await usage.month_spend(ctx.db, ctx.user.id)
    result = await ctx.call(stage, runner)
    return result.value, round(await usage.month_spend(ctx.db, ctx.user.id) - before, 4)


def _too_big(document: dict[str, Any]) -> None:
    if len(repr(document)) > MAX_DOCUMENT_CHARS:
        raise ApiError(413, "The document is too large.")


# ---- the résumé ---------------------------------------------------------------------------------------------


@router.put("/{application_id}/resume", response_model=DocumentIn)
async def save_resume(application_id: str, body: DocumentIn,
                      repo: ApplicationRepository = Depends(get_repo)) -> DocumentIn:
    """Autosave the edited résumé. Facts and sources are enforced, and warnings and coverage recomputed."""
    application, job, version, _ = await repo.get(application_id)
    document = await repo.resume(application_id)
    if document is None or document.current is None or application.status in ACTIVE:
        raise ApiError(409, "This résumé can't be edited right now.")
    _too_big(body.document)
    analysis = JobAnalysis.model_validate(job.analysis)
    resume = normalize_resume(body.document, document.current, version.content, analysis)
    document.current, document.updated_at = resume, utcnow()
    application.coverage_score, application.updated_at = resume["analysis"]["coverage"]["score"], utcnow()
    await repo.db.commit()
    return DocumentIn(document=resume)


def _bullets_by_id(resume: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {b["id"]: (item["sourceId"], b) for s in resume.get("sections") or [] for item in s.get("items") or []
            for b in item.get("bullets") or []}


def _target_text(resume: dict[str, Any], body: RefineIn) -> str:
    bullets = _bullets_by_id(resume)
    if body.scope == "bullet":
        if body.target_id not in bullets:
            raise ApiError(422, "That bullet isn't in the résumé.")
        return f"bullet {body.target_id} of {bullets[body.target_id][0]}: {bullets[body.target_id][1]['text']}"
    if body.scope == "item":
        lines = [f"- {bullet['id']}: {bullet['text']}" for owner, bullet in bullets.values() if owner == body.target_id]
        items = {i["sourceId"] for s in resume.get("sections") or [] for i in s.get("items") or []}
        if body.target_id not in items:
            raise ApiError(422, "That role or project isn't in the résumé.")
        return f"all bullets of {body.target_id}:\n" + "\n".join(lines)
    if body.scope in ("headline", "summary"):
        return f"the {body.scope}: {(resume.get(body.scope) or {}).get('text', '')}"
    return "the whole résumé"


@router.post("/{application_id}/resume/refine", response_model=RefineOut)
async def refine_resume(application_id: str, body: RefineIn, request: Request,
                        ctx_auth: AuthContext = Depends(current_user),
                        repo: ApplicationRepository = Depends(get_repo)) -> RefineOut:
    """AI refine (EDT-4): suggestions only. Nothing changes until the editor applies them."""
    ctx = await _context(request, repo, ctx_auth.user, application_id)
    document = await repo.resume(application_id)
    if document is None or not document.current:
        raise ApiError(409, "This application has no résumé yet.")
    resume = document.current
    target = _target_text(resume, body)
    analysis = ctx.analysis()
    llm = await ctx.llm()
    draft, cost = await _refine_call(ctx, "refine", lambda: stages.refine(
        llm, model=ctx.application.model, effort=ctx.settings.ai_effort_refine, master=ctx.master,
        version_id=ctx.version.id, posting=ctx.job.raw_text, analysis=analysis, resume=resume, scope=body.scope,
        target=target, instruction=body.instruction))

    index = MasterIndex.build(ctx.master)
    groups = build_term_groups(ctx.master, analysis)
    bullets = _bullets_by_id(resume)

    def own_sources(item_id: str, ids: list[str]) -> list[str]:
        own = index.bullets.get(item_id, {})
        return [s for s in ids if s in own and s not in index.hidden]

    def in_scope(item_id: str, bullet_id: str | None) -> bool:
        return (body.scope == "document" or (body.scope == "item" and item_id == body.target_id)
                or (body.scope == "bullet" and bullet_id == body.target_id))

    changes: list[SuggestedChange] = []
    for rb in draft.bullets:
        if rb.target_id not in bullets or not rb.text.strip():
            continue
        item_id, current = bullets[rb.target_id]
        if not in_scope(item_id, rb.target_id) or rb.text.strip() == current["text"]:
            continue
        sources = own_sources(item_id, rb.source_ids) or current.get("sourceIds", [])
        changes.append(SuggestedChange(kind="bullet", target_id=rb.target_id, before=current["text"],
                                       after=rb.text.strip(), source_ids=sources,
                                       warnings=check_text(rb.text, source_text(index, item_id, sources), groups)))
    for key in ("headline", "summary"):
        block = getattr(draft, key)
        if block.text.strip() and body.scope in (key, "document"):
            sources = ([s for s in block.source_ids if s in index.all_ids]
                       or (resume.get(key) or {}).get("sourceIds", []))
            changes.append(SuggestedChange(kind=key, target_id=key, before=(resume.get(key) or {}).get("text", ""),
                                           after=block.text.strip(), source_ids=sources,
                                           warnings=check_text(block.text, source_text(index, None, sources), groups)))
    items: list[SuggestedItem] = []
    for ri in draft.items:
        if not in_scope(ri.item_id, None) or body.scope == "bullet":
            continue
        new_bullets = []
        for rb in ri.bullets:
            sources = own_sources(ri.item_id, rb.source_ids)
            if not rb.text.strip() or not sources:
                continue
            same_item = bullets.get(rb.target_id, ("",))[0] == ri.item_id
            bullet_id = rb.target_id if same_item else f"rb-{secrets.token_hex(3)}"
            new_bullets.append({"id": bullet_id, "text": rb.text.strip(), "sourceIds": sources, "relevance": 4,
                                "keywords": rb.keywords, "origin": "ai", "edited": False, "aiText": rb.text.strip(),
                                "warnings": check_text(rb.text, source_text(index, ri.item_id, sources), groups)})
        if new_bullets:
            items.append(SuggestedItem(item_id=ri.item_id, bullets=new_bullets))
    return RefineOut(changes=changes, items=items, notes=[n.model_dump(by_alias=True) for n in draft.notes],
                     cost_usd=cost)


# ---- the cover letter ---------------------------------------------------------------------------------------


@router.post("/{application_id}/cover-letter", response_model=ApplicationOut, status_code=202)
async def generate_letter(application_id: str, body: CoverLetterOptions, request: Request,
                          ctx_auth: AuthContext = Depends(current_user), settings: Settings = Depends(get_settings),
                          repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    """Write (or rewrite) the cover letter with these options (CVL-1, CVL-2)."""
    ctx = await _context(request, repo, ctx_auth.user, application_id)
    if await repo.resume(application_id) is None:
        raise ApiError(409, "Generate the résumé first: the letter builds on it.")
    existing = await repo.letter(application_id)
    if existing is not None and existing.status == "generating":
        raise ApiError(409, "The cover letter is already being written.")
    key = await keys.resolve(repo.db, ctx.user, settings)
    await usage.ensure_within_cap(repo.db, ctx.user, key.source, settings,
                                  usage.estimate_job_cost(ctx.application.model, settings, stages=("letter",)))
    options = {**body.model_dump(by_alias=True), "generate": True}
    if existing is None:
        existing = Document(owner_id=ctx.user.id, application_id=application_id, kind="cover_letter")
        repo.db.add(existing)
    existing.status, existing.error, existing.options, existing.updated_at = "generating", None, options, utcnow()
    ctx.application.options = {**(ctx.application.options or {}), "coverLetter": options}
    await repo.db.commit()
    app = request.app
    app.state.jobs.submit(ctx.user.id, lambda: run_letter(app, application_id, options))
    return ApplicationOut(**_out(await repo.get(application_id)))


@router.put("/{application_id}/cover-letter", response_model=DocumentIn)
async def save_letter(application_id: str, body: DocumentIn,
                      repo: ApplicationRepository = Depends(get_repo)) -> DocumentIn:
    """Autosave the edited cover letter (CVL-5)."""
    _, job, version, _ = await repo.get(application_id)
    document = await repo.letter(application_id)
    if document is None or document.status != "ready" or not document.current:
        raise ApiError(409, "There's no cover letter to edit right now.")
    _too_big(body.document)
    letter = normalize_letter(body.document, document.current, version.content,
                              JobAnalysis.model_validate(job.analysis), job.raw_text)
    document.current, document.updated_at = letter, utcnow()
    await repo.db.commit()
    return DocumentIn(document=letter)


@router.post("/{application_id}/cover-letter/refine", response_model=LetterRefineOut)
async def refine_letter(application_id: str, body: LetterRefineIn, request: Request,
                        ctx_auth: AuthContext = Depends(current_user),
                        repo: ApplicationRepository = Depends(get_repo)) -> LetterRefineOut:
    """Rewrite one paragraph, or the whole letter, from an instruction. A suggestion only."""
    ctx = await _context(request, repo, ctx_auth.user, application_id)
    document = await repo.letter(application_id)
    if document is None or document.status != "ready" or not document.current:
        raise ApiError(409, "There's no cover letter to refine.")
    letter = document.current
    paragraphs = {p["id"]: p for p in letter.get("paragraphs") or []}
    if body.target_id and body.target_id not in paragraphs:
        raise ApiError(422, "That paragraph isn't in the letter.")
    target = (f"paragraph {body.target_id}: {paragraphs[body.target_id]['text']}" if body.target_id
              else "the whole letter")
    notes = ((letter.get("options") or {}).get("notes") or "")
    llm = await ctx.llm()
    draft, cost = await _refine_call(ctx, "letter_refine", lambda: stages.refine_letter(
        llm, model=ctx.application.model, effort=ctx.settings.ai_effort_refine, master=ctx.master,
        version_id=ctx.version.id, posting=ctx.job.raw_text, analysis=ctx.analysis(), letter_doc=letter, notes=notes,
        target=target, instruction=body.instruction))
    index = MasterIndex.build(ctx.master)
    requirement_ids = {r.id for r in ctx.analysis().requirements}
    out = []
    for rp in draft.paragraphs:
        if not rp.text.strip():
            continue
        if body.target_id and rp.target_id != body.target_id:
            continue
        pid = rp.target_id if rp.target_id in paragraphs else f"p{secrets.token_hex(2)}"
        out.append({"id": pid, "role": rp.role, "text": rp.text.strip(),
                    "sourceIds": [s for s in rp.source_ids if s in index.all_ids and s not in index.hidden],
                    "jobRefs": [r for r in rp.job_refs if r in requirement_ids],
                    "companySources": list(dict.fromkeys(rp.company_sources)), "aiText": rp.text.strip(),
                    "edited": False, "flags": [], "warnings": []})
    return LetterRefineOut(scope="paragraph" if body.target_id else "letter", paragraphs=out,
                           notes=[n.model_dump(by_alias=True) for n in draft.notes], cost_usd=cost)


# ---- audit, analysis, continue, regenerate, duplicate ---------------------------------------------------------------


@router.post("/{application_id}/audit", response_model=ApplicationOut, status_code=202)
async def rerun_audit(application_id: str, request: Request, ctx_auth: AuthContext = Depends(current_user),
                      settings: Settings = Depends(get_settings),
                      repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    """Check the current wording again (TLR-8), for example after edits."""
    ctx = await _context(request, repo, ctx_auth.user, application_id)
    key = await keys.resolve(repo.db, ctx.user, settings)
    await usage.ensure_within_cap(repo.db, ctx.user, key.source, settings,
                                  usage.estimate_job_cost(ctx.application.model, settings, stages=("audit",)))
    document = await repo.resume(application_id)
    if document is not None and document.current:
        current = dict(document.current)
        report = dict(current.get("analysis") or {})
        report["audit"] = {**(report.get("audit") or {}), "status": "running"}
        document.current = {**current, "analysis": report}
        await repo.db.commit()
    app = request.app
    app.state.jobs.submit(ctx.user.id, lambda: run_audit(app, application_id))
    return ApplicationOut(**_out(await repo.get(application_id)))


@router.put("/{application_id}/analysis", response_model=dict[str, Any])
async def edit_analysis(application_id: str, body: AnalysisEditIn,
                        repo: ApplicationRepository = Depends(get_repo)) -> dict[str, Any]:
    """Promote, demote or add keywords, mark must-includes, and set the themes to emphasize (JOB-4).
    Regenerating then uses the edited analysis."""
    application, job, _, _ = await repo.get(application_id)
    if application.status in ACTIVE or not job.analysis:
        raise ApiError(409, "The analysis can't be edited right now.")
    analysis = dict(job.analysis)
    existing = {k["term"].casefold(): k for k in analysis.get("keywords") or []}
    keywords = []
    for edit in body.keywords:
        base = existing.get(edit.term.casefold(), {"term": edit.term, "aliases": [], "category": "other"})
        keywords.append({**base, "importance": edit.importance, "mustInclude": edit.must_include})
    analysis["keywords"] = keywords
    analysis["suggestedEmphasis"] = [e for e in body.suggested_emphasis if e]
    try:
        validated = JobAnalysis.model_validate(analysis)
    except ValidationError as exc:
        raise ApiError(422, "The analysis isn't valid.") from exc
    job.analysis, job.analysis_edited = validated.model_dump(mode="json", by_alias=True), True
    application.updated_at = utcnow()
    await repo.db.commit()
    return job.analysis


async def _queue_tailor(request: Request, repo: ApplicationRepository, user: Any, settings: Settings,
                        application: Application, letter: bool | None) -> None:
    key = await keys.resolve(repo.db, user, settings)
    stage_names = ("tailor", "letter", "audit") if letter else ("tailor", "audit")
    await usage.ensure_within_cap(repo.db, user, key.source, settings,
                                  usage.estimate_job_cost(application.model, settings, stages=stage_names))
    if letter is not None:
        options = dict(application.options or {})
        options["coverLetter"] = {**(options.get("coverLetter") or CoverLetterOptions().model_dump(by_alias=True)),
                                  "generate": letter}
        application.options = options
    application.status, application.error, application.updated_at = "queued", None, utcnow()
    await repo.db.commit()
    start(request, user.id, application.id, "tailor")


@router.post("/{application_id}/continue", response_model=ApplicationOut, status_code=202)
async def continue_after_review(application_id: str, request: Request, ctx_auth: AuthContext = Depends(current_user),
                                settings: Settings = Depends(get_settings),
                                repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    """After reviewing (and maybe editing) the analysis, write the résumé (JOB-5)."""
    application = (await repo.get(application_id))[0]
    if application.status != "review":
        raise ApiError(409, "This application isn't waiting for a review.")
    await _queue_tailor(request, repo, ctx_auth.user, settings, application, None)
    return ApplicationOut(**_out(await repo.get(application_id)))


@router.post("/{application_id}/regenerate", response_model=ApplicationOut, status_code=202)
async def regenerate(application_id: str, body: RegenerateIn, request: Request,
                     ctx_auth: AuthContext = Depends(current_user), settings: Settings = Depends(get_settings),
                     repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    """Write the résumé again from the current analysis. This replaces the edited résumé."""
    application, job, _, _ = await repo.get(application_id)
    if application.status in ACTIVE or not job.analysis:
        raise ApiError(409, "This application can't be regenerated right now.")
    await _queue_tailor(request, repo, ctx_auth.user, settings, application, body.letter)
    return ApplicationOut(**_out(await repo.get(application_id)))


@router.post("/{application_id}/duplicate", response_model=ApplicationOut, status_code=201)
async def duplicate(application_id: str, repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    """A copy to try a different version against (EDT-7): same posting, analysis and documents."""
    application, job, _, _ = await repo.get(application_id)
    if application.status in ACTIVE:
        raise ApiError(409, "Wait for this application to finish generating.")
    now = utcnow()
    job_copy = JobPosting(owner_id=repo.owner_id, company=job.company, title=job.title, url=job.url,
                          raw_text=job.raw_text, analysis=job.analysis, analysis_edited=job.analysis_edited,
                          created_at=now)
    repo.db.add(job_copy)
    await repo.db.flush()
    copy = Application(owner_id=repo.owner_id, master_version_id=application.master_version_id, job_id=job_copy.id,
                       status=application.status, error=application.error, options=application.options,
                       model=application.model, template=application.template, theme=application.theme,
                       coverage_score=application.coverage_score, created_at=now, updated_at=now)
    repo.db.add(copy)
    await repo.db.flush()
    for kind in ("resume", "cover_letter"):
        document = await repo.document(application_id, kind)
        if document is not None:
            current = dict(document.current or {})
            if "meta" in current:
                current["meta"] = {**current["meta"], "applicationId": copy.id}
            repo.db.add(Document(owner_id=repo.owner_id, application_id=copy.id, kind=kind, options=document.options,
                                 ai_draft=document.ai_draft, current=current, status=document.status,
                                 error=document.error, updated_at=now))
    await repo.db.commit()
    return ApplicationOut(**_out(await repo.get(copy.id)))


# ---- fit to page and undo (DESIGN.md §11.7, TPL-4) ---------------------------------------------------------------

KEEP_REVISIONS = 10


async def _snapshot(repo: ApplicationRepository, application: Application, document: Document, reason: str) -> str:
    """Save the document and design as they are, to undo the change about to be made; keep the last few."""
    revision = DocumentRevision(owner_id=repo.owner_id, document_id=document.id,
                                content=copy.deepcopy(document.current),
                                design={"template": application.template, "theme": application.theme}, reason=reason)
    repo.db.add(revision)
    await repo.db.flush()
    keep = select(DocumentRevision.id).where(DocumentRevision.document_id == document.id).order_by(
        DocumentRevision.created_at.desc(), DocumentRevision.id.desc()).limit(KEEP_REVISIONS)
    await repo.db.execute(delete(DocumentRevision).where(DocumentRevision.document_id == document.id,
                                                         DocumentRevision.id.not_in(keep)))
    return revision.id


def _page_target(application: Application, master: dict[str, Any], requested: int | None) -> int:
    if requested:
        return requested
    limit = (application.options or {}).get("pageLimit") or (master.get("preferences") or {}).get("pageLimit")
    if isinstance(limit, int):
        return limit
    return 2 if limit == "auto" and len(master.get("work") or []) >= 5 else 1


def _with_design(document: dict[str, Any], template: str, theme: dict[str, Any]) -> dict[str, Any]:
    return {**document, "meta": {**(document.get("meta") or {}), "template": template, "theme": theme}}


@router.post("/{application_id}/resume/fit", response_model=FitOut)
async def fit_resume_to_page(application_id: str, body: FitIn, request: Request,
                             repo: ApplicationRepository = Depends(get_repo)) -> FitOut:
    """Fit the résumé to its page target: tighter spacing, then narrower margins, then the fewest less relevant
    bullets (never pinned, edited or your own). Saved at once, with a snapshot to undo it."""
    application, job, version, _ = await repo.get(application_id)
    document = await repo.resume(application_id)
    if document is None or not document.current or application.status in ACTIVE:
        raise ApiError(409, "This résumé can't be fitted right now.")
    template, theme = stored_design(application.template, application.theme)
    target = _page_target(application, version.content, body.target_pages)
    info = {"company": job.company, "title": job.title}

    async def render(resume: dict[str, Any], candidate: Any) -> Any:
        return await render_resume_as(request.app, resume, info, template, candidate)

    result = await fit_resume(render, document.current, version.content, template, theme, target)
    revision_id = None
    removed_text = []
    if result.changed:
        revision_id = await _snapshot(repo, application, document, "fit")
        bullets = _bullets_by_id(document.current)
        removed_text = [bullets[b][1]["text"] for b in result.removed if b in bullets]
        resume = copy.deepcopy(result.document)
        if result.removed:
            annotate_resume(resume, version.content, JobAnalysis.model_validate(job.analysis))
            application.coverage_score = resume["analysis"]["coverage"]["score"]
        theme_json = result.theme.model_dump(mode="json", by_alias=True)
        document.current, document.updated_at = _with_design(resume, template, theme_json), utcnow()
        application.theme, application.updated_at = theme_json, utcnow()
        await repo.db.commit()
    return FitOut(fits=result.fits, pages=result.pages, room=result.room, changes=result.changes,
                  removed=removed_text, document=document.current, template=template, theme=result.theme,
                  revision_id=revision_id)


@router.post("/{application_id}/cover-letter/fit", response_model=FitOut)
async def fit_letter_to_page(application_id: str, request: Request, ctx_auth: AuthContext = Depends(current_user),
                             repo: ApplicationRepository = Depends(get_repo)) -> FitOut:
    """Fit the cover letter on one page by condensing its paragraphs (stage F), at most twice. The design is
    shared with the résumé, so it isn't changed here."""
    ctx = await _context(request, repo, ctx_auth.user, application_id)
    document = await repo.letter(application_id)
    if document is None or document.status != "ready" or not document.current:
        raise ApiError(409, "There's no cover letter to fit.")
    template, theme = stored_design(ctx.application.template, ctx.application.theme)
    info = {"company": ctx.job.company, "title": ctx.job.title}
    letter = copy.deepcopy(document.current)
    current = measure(await render_letter_as(request.app, letter, info, template, theme), template, theme)
    if current.pages <= 1:
        return FitOut(fits=True, pages=1, room=False, changes=[], document=letter, template=template, theme=theme)

    def words() -> int:
        return sum(len(p["text"].split()) for p in letter.get("paragraphs") or [])

    start, cost, llm = words(), 0.0, await ctx.llm()
    for _ in range(2):
        over = current.pages - 1 + current.fill  # pages past the first
        percent = max(10, min(40, round(100 * over / (0.75 + over)) + 5))  # the body is about 3/4 of page 1
        goal = f"Cut about {percent}% of the words in total, aiming for about {round(words() * (100 - percent) / 100)}."
        items = [{"id": p["id"], "text": p["text"]} for p in letter.get("paragraphs") or []]
        draft, spent = await _refine_call(ctx, "condense", lambda goal=goal, items=items: stages.condense(
            llm, model=ctx.application.model, effort=ctx.settings.ai_effort_condense, items=items, goal=goal))
        cost += spent
        shorter = {i.target_id: i.text.strip() for i in draft.items if i.text.strip()}
        for p in letter.get("paragraphs") or []:
            if p["id"] in shorter and len(shorter[p["id"]]) < len(p["text"]):
                p["text"] = p["aiText"] = shorter[p["id"]]
                p["edited"] = False
        current = measure(await render_letter_as(request.app, letter, info, template, theme), template, theme)
        if current.pages <= 1:
            break
    annotate_letter(letter, ctx.master, ctx.analysis(), ctx.job.raw_text)
    revision_id = await _snapshot(repo, ctx.application, document, "fit")
    document.current, document.updated_at = letter, utcnow()
    await repo.db.commit()
    return FitOut(fits=current.pages <= 1, pages=current.pages, room=False, document=letter, template=template,
                  theme=theme, changes=[f"Condensed the paragraphs from {start} to {words()} words"],
                  revision_id=revision_id, cost_usd=round(cost, 4))


@router.post("/{application_id}/revisions/{revision_id}/restore", response_model=RestoreOut)
async def restore_revision(application_id: str, revision_id: str,
                           repo: ApplicationRepository = Depends(get_repo)) -> RestoreOut:
    """Undo an automatic change: the document, and the design, as they were before it."""
    application = (await repo.get(application_id))[0]
    found = (await repo.db.execute(select(DocumentRevision, Document).join(
        Document, Document.id == DocumentRevision.document_id).where(
        DocumentRevision.id == revision_id, DocumentRevision.owner_id == repo.owner_id,
        Document.application_id == application_id))).first()
    if found is None:
        raise ApiError(404, "There's nothing to undo.")
    revision, document = found
    if application.status in ACTIVE:
        raise ApiError(409, "Wait for this application to finish generating.")
    design = revision.design or {}
    template, theme = stored_design(design.get("template") or application.template,
                                    design.get("theme") or application.theme)
    theme_json = theme.model_dump(mode="json", by_alias=True)
    application.template, application.theme, application.updated_at = template, theme_json, utcnow()
    content = copy.deepcopy(revision.content)
    if document.kind == "resume":
        content = _with_design(content, template, theme_json)
        application.coverage_score = ((content.get("analysis") or {}).get("coverage") or {}).get("score")
    document.current, document.updated_at = content, utcnow()
    await repo.db.delete(revision)
    await repo.db.commit()
    return RestoreOut(kind=document.kind, document=content, template=template, theme=theme)
