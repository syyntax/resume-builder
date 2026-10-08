"""A deterministic stand-in for the model: AI_PROVIDER=fake (demos, UI work) and the test suite.

It reads the same request blocks the real model gets, so prompt assembly is exercised too. Its output is
mechanical (bullets are copied verbatim), never a substitute for the real thing.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from typing import Any

from app.ai import fake_import, fake_stages
from app.ai.llm import LLMError, LLMRequest, LLMResult, Usage, key_rejected

# Terms the fake recognizes in postings even when the master résumé doesn't mention them (to produce gaps).
_EXTRA_TERMS = ("GCP", "Azure", "Rust", "Java", "Kafka", "Spark", "Snowflake", "Kotlin", "Scala", "Ruby")
_PREFERRED = re.compile(r"\b(nice to have|preferred|bonus|plus)\b", re.IGNORECASE)


def _between(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>\n?(.*?)\n?</{tag}>", text, re.DOTALL)
    return match.group(1) if match else ""


def _mentions(text: str, term: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _usage(request: LLMRequest, output: dict[str, Any]) -> Usage:
    prompt_chars = len(request.system) + sum(len(b.text) + len(b.document or b"") // 2 for b in request.blocks)
    return Usage(input_tokens=prompt_chars // 4, output_tokens=len(json.dumps(output)) // 4)


class FakeLLM:
    def __init__(self, api_key: str, delay: float = 0.0) -> None:
        self.api_key, self.delay = api_key, delay

    async def verify(self) -> None:
        if "invalid" in self.api_key:
            raise key_rejected()

    async def complete(self, request: LLMRequest) -> LLMResult:
        if "invalid" in self.api_key:
            raise key_rejected()
        if self.delay:
            await asyncio.sleep(self.delay)
        if request.stage == "import":
            data = fake_import.transcribe(self._document_text(request))
            return LLMResult(data=data, usage=_usage(request, data), model=request.model, stop_reason="end_turn",
                             request_id="req_fake", duration_ms=5)
        if request.stage in ("audit", "condense"):
            block = request.blocks[0].text
            data = (fake_stages.audit(json.loads(_between(block, "claims"))) if request.stage == "audit"
                    else fake_stages.condense(json.loads(_between(block, "texts"))))
            return LLMResult(data=data, usage=_usage(request, data), model=request.model, stop_reason="end_turn",
                             request_id="req_fake", duration_ms=5)
        master = json.loads(_between(request.blocks[0].text, "master_resume"))
        posting = _between(request.blocks[1].text, "job_posting")
        task = request.blocks[2].text
        if request.stage == "analyze":
            data = self._analyze(master, posting)
        elif request.stage.startswith("tailor"):
            analysis = json.loads(_between(task, "job_analysis"))
            data = self._tailor(master, analysis)
        elif request.stage == "letter":
            data = fake_stages.letter(json.loads(_between(task, "job_analysis")),
                                      json.loads(_between(task, "tailored_resume")), _between(task, "user_notes"))
        elif request.stage == "refine":
            data = fake_stages.refine(json.loads(_between(task, "current_resume")), _between(task, "request"))
        elif request.stage == "letter_refine":
            data = fake_stages.refine_letter(json.loads(_between(task, "current_letter")), _between(task, "request"))
        else:
            raise LLMError("bad_request", f"fake model has no stage {request.stage!r}")
        return LLMResult(data=data, usage=_usage(request, data), model=request.model, stop_reason="end_turn",
                         request_id="req_fake", duration_ms=5)

    @staticmethod
    def _document_text(request: LLMRequest) -> str:
        source = request.blocks[0]
        if source.document is None:
            return _between(source.text, "resume_document")
        from pypdf import PdfReader  # the real model reads the PDF itself; the fake reads its text layer

        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(source.document)).pages)

    # ---- stage A ----------------------------------------------------------------------------------

    def _analyze(self, master: dict[str, Any], posting: str) -> dict[str, Any]:
        lines = [line.strip() for line in posting.splitlines() if line.strip()]
        title, company = None, None
        if lines and " at " in lines[0]:
            title, company = (part.strip() for part in lines[0].split(" at ", 1))

        keywords: list[dict[str, Any]] = []
        for skill in master.get("skills", []):
            names = [skill["name"], *skill.get("aliases", [])]
            hit = next((n for n in names if _mentions(posting, n)), None)
            if hit:
                keywords.append({"term": hit, "aliases": [n for n in names if n != hit], "importance": 2,
                                 "category": "technology", "mustInclude": False})
        for term in _EXTRA_TERMS:
            if _mentions(posting, term) and all(k["term"] != term for k in keywords):
                keywords.append({"term": term, "aliases": [], "importance": 2, "category": "technology",
                                 "mustInclude": False})

        requirements, matches = [], []
        bullets = [ln.lstrip("-•* ").strip() for ln in lines if ln[:1] in "-•*"]
        for i, text in enumerate(bullets[:12], start=1):
            rid = f"r{i}"
            terms = [k["term"] for k in keywords if _mentions(text, k["term"])]
            kind = "preferred" if _PREFERRED.search(text) else "required"
            requirements.append({"id": rid, "text": text, "kind": kind,
                                 "category": "skill" if terms else "experience", "keywords": terms})
            evidence = [s["id"] for s in master.get("skills", [])
                        if any(_mentions(text, n) for n in [s["name"], *s.get("aliases", [])])]
            missing = any(t in _EXTRA_TERMS and not evidence for t in terms)
            status = "met" if evidence else ("missing" if missing else "partial")
            matches.append({"requirementId": rid, "status": status, "evidenceIds": evidence,
                            "note": "Matched from listed skills." if evidence else "Not clearly shown in the master."})
        met = sum(m["status"] == "met" for m in matches)
        rating = "strong" if matches and met / len(matches) >= 0.6 else "moderate" if met else "weak"
        return {
            "company": company, "title": title, "seniority": "unknown", "location": None, "employmentType": None,
            "roleSummary": " ".join(lines[1:3])[:400] or "Role summary unavailable in offline mode.",
            "requirements": requirements, "responsibilities": [], "keywords": keywords,
            "companySignals": [], "match": matches,
            "fit": {"rating": rating, "rationale": f"{met} of {len(matches)} listed requirements match the master."},
            "suggestedEmphasis": [k["term"] for k in keywords[:4]],
        }

    # ---- stage B ----------------------------------------------------------------------------------

    def _tailor(self, master: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        terms = [k["term"] for k in analysis.get("keywords", [])]

        def bullets_of(item: dict[str, Any]) -> list[dict[str, Any]]:
            out = []
            for b in item.get("highlights", []):
                covered = [t for t in terms if _mentions(b["text"], t)]
                relevance = 5 if b.get("pin") else min(5, 2 + len(covered))
                out.append({"text": b["text"], "sourceIds": [b["id"]], "relevance": relevance, "keywords": covered})
            return sorted(out, key=lambda b: -b["relevance"])

        groups: dict[str, list[dict[str, str]]] = {}
        for skill in master.get("skills", []):
            groups.setdefault(skill.get("category") or "Skills", []).append(
                {"skillId": skill["id"], "display": skill["name"]})
        headline = (master.get("headlines") or [{"id": None, "text": master["basics"].get("label") or ""}])[0]
        summary = (master.get("summaries") or [{"id": None, "text": master["basics"].get("summary") or ""}])[0]
        gaps = [k["term"] for k in analysis.get("keywords", [])
                if not any(_mentions(json.dumps(master), a) for a in [k["term"], *k.get("aliases", [])])]
        return {
            "headline": {"text": headline["text"], "sourceIds": [headline["id"]] if headline["id"] else []},
            "summary": {"text": summary["text"], "sourceIds": [summary["id"]] if summary["id"] else []},
            "sectionOrder": ["summary", "experience", "projects", "skills", "certifications", "education", "custom"],
            "experience": [{"workId": w["id"], "bullets": bullets_of(w)} for w in master.get("work", [])],
            "earlierExperienceIds": [],
            "projects": [{"projectId": p["id"], "bullets": bullets_of(p)} for p in master.get("projects", [])],
            "skills": [{"group": g, "skills": s} for g, s in groups.items()],
            "include": {
                "education": [e["id"] for e in master.get("education", [])],
                "certifications": [c["id"] for c in master.get("certifications", [])],
                "awards": [], "publications": [], "volunteer": [],
                "languages": [lang["id"] for lang in master.get("languages", [])],
                "customSections": [{"sectionId": s["id"], "itemIds": [i["id"] for i in s.get("items", [])]}
                                   for s in master.get("customSections", [])],
            },
            "notes": [{"type": "gap", "text": f"The posting mentions {g}, which isn't in your master résumé."}
                      for g in gaps],
        }
