"""The LLM judge (DESIGN.md §17): a rubric for relevance and letter quality, scored 1 to 5.

Facts are graded deterministically elsewhere (grade.py); the judge covers what code can't: whether the résumé
leads with what this posting cares about, and whether the letter reads like one worth sending.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from app.ai.llm import Block, LLMClient, LLMRequest, Usage
from app.ai.schemas import _Out, strict_schema

MIN_MEAN = 3.5  # across all cases, per criterion
MIN_SCORE = 3  # no single case below this

SYSTEM = """You review tailored job application materials for quality. You are strict and specific: a 5 is \
rare and means a hiring manager would be impressed; a 3 is acceptable but generic; 1 or 2 means it would hurt \
the candidate. The master résumé is everything the candidate has done; the tailored résumé and the letter may \
only draw on it. Judge only the two criteria asked. Don't judge factual accuracy: that's checked separately."""

RUBRIC = """Score two criteria from 1 to 5.

relevance: Does the tailored résumé put the experience, results, and skills this posting cares most about \
first and most prominently? Does it leave out anything in the master that this posting would clearly value? \
Is the headline and summary aimed at this role? 5: a recruiter for this role sees the fit within seconds. \
1: it reads like an untailored résumé, or it emphasizes the wrong things.

letter: Is the cover letter specific to this company and role, built on concrete evidence from the \
candidate's experience, well organized, free of clichés and filler, and an appropriate length? 5: ready to \
send with light edits. 1: generic, vague, or off-putting.

For each, give the score and one or two sentences of reasoning. Then list up to 5 concrete problems, most \
important first (an empty list if there are none)."""


class Score(_Out):
    score: Literal[1, 2, 3, 4, 5]
    reason: str


class Verdict(_Out):
    relevance: Score
    letter: Score
    problems: list[str]


def request(*, model: str, master: dict[str, Any], posting: str, resume_md: str, letter_md: str) -> LLMRequest:
    return LLMRequest(
        stage="eval_judge",
        model=model,
        system=SYSTEM,
        blocks=[
            Block(f"<master_resume>\n{json.dumps(master, ensure_ascii=False)}\n</master_resume>"),
            Block(f"<job_posting>\n{posting}\n</job_posting>"),
            Block(f"<tailored_resume>\n{resume_md}\n</tailored_resume>\n\n<cover_letter>\n{letter_md}\n"
                  f"</cover_letter>\n\n{RUBRIC}"),
        ],
        schema=strict_schema(Verdict),
        effort="medium",
        max_tokens=4000,
    )


async def judge(llm: LLMClient, **kwargs: Any) -> tuple[Verdict, Usage, str]:
    result = await llm.complete(request(**kwargs))
    return Verdict.model_validate(result.data), result.usage, result.model
