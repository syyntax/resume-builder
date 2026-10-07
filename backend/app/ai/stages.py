"""AI stages A (analyze) and B (tailor). See DESIGN.md §9.

Message layout keeps the stable content first so consecutive calls reuse the prompt cache:
system → <master_resume> (breakpoint) → <job_posting> (breakpoint) → <task>.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.ai import prompts
from app.ai.llm import Block, LLMClient, LLMError, LLMRequest, LLMResult
from app.ai.schemas import JobAnalysis, TailorDraft, strict_schema

ITEM_SECTIONS = (
    "headlines", "summaries", "work", "projects", "education", "certifications", "skills", "awards",
    "publications", "volunteer", "languages", "interests", "references",
)
log = logging.getLogger("resume_tailor.ai")
DEFAULT_RECENT_YEARS = 15
BULLET_BUDGET = {1: 16, 2: 28}


@dataclass
class StageResult[T]:
    value: T
    call: LLMResult
    prompt_version: str


def prompt_view(master: dict[str, Any]) -> dict[str, Any]:
    """The master as the model sees it: hidden items (and bullets) removed, editor-only keys dropped."""

    def visible(items: list[Any]) -> list[Any]:
        return [i for i in items if not (isinstance(i, dict) and i.get("hidden"))]

    view = {k: v for k, v in master.items() if k != "$schema"}
    for section in ITEM_SECTIONS:
        if isinstance(view.get(section), list):
            view[section] = [
                {**item, "highlights": visible(item["highlights"])}
                if isinstance(item.get("highlights"), list) else item
                for item in visible(view[section])
            ]
    if isinstance(view.get("customSections"), list):
        view["customSections"] = [
            {**section, "items": visible(section.get("items", []))} for section in visible(view["customSections"])
        ]
    return view


def _blocks(master: dict[str, Any], version_id: str, posting: str, task: str) -> list[Block]:
    master_json = json.dumps(prompt_view(master), ensure_ascii=False, separators=(",", ":"))
    return [
        Block(f'<master_resume version="{version_id}">\n{master_json}\n</master_resume>', cache=True),
        Block(f"<job_posting>\n{posting.strip()}\n</job_posting>", cache=True),
        Block(task),
    ]


def _validate[T](stage: str, model: type[T], result: LLMResult) -> T:
    try:
        return model.model_validate(result.data)  # type: ignore[attr-defined, no-any-return]
    except ValidationError as exc:
        # Locations and messages only: Pydantic's messages name the expected values, never the résumé text.
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10])
        log.warning("%s output from %s failed validation (request %s): %s", stage, result.model,
                    result.request_id, problems)
        raise LLMError("bad_output", "The model's answer didn't match the expected structure. Retry.",
                       usage=result.usage, model=result.model, request_id=result.request_id,
                       duration_ms=result.duration_ms, details={"errors": exc.errors(include_url=False)[:5]}) from None


async def analyze(llm: LLMClient, *, model: str, effort: str, master: dict[str, Any], version_id: str,
                  posting: str) -> StageResult[JobAnalysis]:
    task = prompts.load("analyze")
    request = LLMRequest(
        stage="analyze", model=model, system=prompts.load("system").text,
        blocks=_blocks(master, version_id, posting, task.text),
        schema=strict_schema(JobAnalysis), effort=effort, max_tokens=32_000,
    )
    result = await llm.complete(request)
    return StageResult(_validate("analyze", JobAnalysis, result), result, task.tag)


def tailor_options(master: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    prefs = master.get("preferences") or {}
    page_limit = options.get("pageLimit") or prefs.get("pageLimit") or 1
    if page_limit == "auto":
        recent_roles = len(master.get("work") or [])
        page_limit = 2 if recent_roles >= 5 else 1
    return {
        "length": "one page" if page_limit == 1 else "two pages",
        "bullet_budget": BULLET_BUDGET.get(page_limit, 16),
        "tone": options.get("tone") or prefs.get("tone") or "confident",
        "spelling": prefs.get("spelling") or "en-US",
        "recent_years": prefs.get("recentYears") or DEFAULT_RECENT_YEARS,
        "min_bullets": prefs.get("minBulletsPerRecentRole") if prefs.get("minBulletsPerRecentRole") is not None else 2,
        "instructions": (options.get("instructions") or "").strip() or "none",
    }


async def tailor(llm: LLMClient, *, model: str, effort: str, master: dict[str, Any], version_id: str, posting: str,
                 analysis: JobAnalysis, options: dict[str, Any],
                 repair: list[str] | None = None) -> StageResult[TailorDraft]:
    task = prompts.load("tailor")
    analysis_json = json.dumps(analysis.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=1)
    text = task.text.format(analysis=analysis_json, **tailor_options(master, options))
    if repair:
        problems = "\n".join(f"- {p}" for p in repair[:30])
        text += (
            "\n\n<repair>\nYour previous answer had these problems. Return a corrected, complete answer that "
            f"only uses ids that exist in the master résumé:\n{problems}\n</repair>"
        )
    request = LLMRequest(
        stage="tailor_repair" if repair else "tailor", model=model, system=prompts.load("system").text,
        blocks=_blocks(master, version_id, posting, text),
        schema=strict_schema(TailorDraft), effort=effort, max_tokens=64_000,
    )
    result = await llm.complete(request)
    return StageResult(_validate(request.stage, TailorDraft, result), result, task.tag)
