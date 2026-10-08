"""The workspace (DESIGN.md §4.6–4.9): cover letters, the claim audit, editing, refine, packets, review-first."""

from __future__ import annotations

import copy
import io
from typing import Any

from fastapi import FastAPI
from pypdf import PdfReader

from app.ai.fake import FakeLLM
from app.ai.llm import LLMError, LLMRequest, LLMResult, Usage
from tests.conftest import POSTING, Api, drain

RECIPIENT = {"name": "Priya Shah", "title": "Director of Platform Engineering", "address": ["San Francisco, CA"]}


def application(app: FastAPI, user: Api, example: dict[str, Any], *, letter: dict[str, Any] | None = None,
                **options: Any) -> dict[str, Any]:
    master_id = user.post("/api/master-resumes", json=example).json()["master"]["id"]
    body: dict[str, Any] = {"masterId": master_id, "job": {"text": POSTING}, "options": options}
    if letter is not None:
        body["coverLetter"] = letter
    created = user.post("/api/applications", json=body)
    assert created.status_code == 202, created.text
    drain(app)
    return user.get(f"/api/applications/{created.json()['id']}").json()


def bullets(resume: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for s in resume["sections"] for i in s.get("items", []) for b in i.get("bullets", [])]


# ---- cover letters --------------------------------------------------------------------------------------------


def test_cover_letter_is_written_with_the_resume_and_grounded(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={
        "recipient": RECIPIENT, "tone": "warm", "length": "short",
        "notes": "I've used Globex's SDK for years and admire its docs."})
    assert detail["status"] == "done" and detail["coverLetterStatus"] == "ready"
    letter = detail["coverLetter"]
    assert letter["salutation"] == "Dear Priya Shah,"  # CVL-7: full name, no guessed honorific
    assert letter["recipient"] == {**RECIPIENT, "company": "Globex"} and letter["subject"] == "Staff Platform Engineer"
    assert letter["sender"]["name"] == "Jordan Rivera" and letter["signature"] == "Jordan Rivera"
    assert [p["role"] for p in letter["paragraphs"]] == ["opening", "evidence", "motivation", "closing"]
    opening, evidence, motivation, _ = letter["paragraphs"]
    assert opening["sourceIds"] and evidence["sourceIds"]  # CVL-3: every claim about the candidate cites the master
    assert motivation["companySources"] == ["posting", "notes"] and "PERSONALIZE" not in motivation["flags"]
    assert letter["analysis"]["wordCount"] > 30 and letter["analysis"]["audit"]["status"] == "done"
    assert letter["options"]["tone"] == "warm"


def test_without_notes_the_motivation_is_flagged_and_the_greeting_is_neutral(app: FastAPI, keyed_user: Api,
                                                                             example) -> None:
    letter = application(app, keyed_user, example)["coverLetter"]
    assert letter["salutation"] == "Dear Hiring Team,"
    motivation = next(p for p in letter["paragraphs"] if p["role"] == "motivation")
    assert motivation["flags"] == ["PERSONALIZE"] and motivation["companySources"] == ["posting"]


def test_letters_can_be_skipped_and_written_later(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={"generate": False})
    assert detail["coverLetterStatus"] == "none" and detail["coverLetter"] is None
    app_id = detail["id"]
    started = keyed_user.post(f"/api/applications/{app_id}/cover-letter", json={"recipient": {"name": "Sam Lee"}})
    assert started.status_code == 202
    assert keyed_user.get(f"/api/applications/{app_id}").json()["coverLetterStatus"] == "generating"
    drain(app)
    detail = keyed_user.get(f"/api/applications/{app_id}").json()
    assert detail["coverLetterStatus"] == "ready" and detail["coverLetter"]["salutation"] == "Dear Sam Lee,"


class LetterFailingLLM(FakeLLM):
    async def complete(self, request: LLMRequest) -> LLMResult:
        if request.stage == "letter":
            raise LLMError("refused", "The model declined this request.", usage=Usage(500, 20), model=request.model)
        return await super().complete(request)


def test_a_failed_letter_does_not_fail_the_application(app: FastAPI, keyed_user: Api, example) -> None:
    app.state.llm_factory = LetterFailingLLM
    detail = application(app, keyed_user, example)
    assert detail["status"] == "done" and detail["resume"] is not None
    assert detail["coverLetterStatus"] == "failed" and detail["coverLetterError"]["code"] == "refused"
    app.state.llm_factory = FakeLLM
    assert keyed_user.post(f"/api/applications/{detail['id']}/cover-letter", json={}).status_code == 202
    drain(app)
    assert keyed_user.get(f"/api/applications/{detail['id']}").json()["coverLetterStatus"] == "ready"


def test_letter_editing_and_refine(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={"notes": "Their docs are great."})
    app_id, letter = detail["id"], detail["coverLetter"]
    edited = copy.deepcopy(letter)
    edited["paragraphs"].reverse()
    edited["paragraphs"][0]["text"] = "Thank you for considering my application."
    edited["recipient"] = {"name": "Alex Kim", "company": "Globex"}
    edited["sender"] = {"name": "Mallory"}  # ignored: the sender always comes from the master
    saved = keyed_user.put(f"/api/applications/{app_id}/cover-letter", json={"document": edited})
    assert saved.status_code == 200, saved.text
    doc = saved.json()["document"]
    assert doc["paragraphs"][0]["edited"] is True and doc["paragraphs"][1]["edited"] is False
    assert doc["sender"]["name"] == "Jordan Rivera" and doc["salutation"] == letter["salutation"]  # kept as edited
    bad = keyed_user.put(f"/api/applications/{app_id}/cover-letter", json={"document": {**edited, "paragraphs": []}})
    assert bad.status_code == 422

    one = keyed_user.post(f"/api/applications/{app_id}/cover-letter/refine",
                          json={"targetId": "p2", "instruction": "Make it shorter"}).json()
    assert one["scope"] == "paragraph" and [p["id"] for p in one["paragraphs"]] == ["p2"] and one["costUsd"] > 0
    whole = keyed_user.post(f"/api/applications/{app_id}/cover-letter/refine", json={"instruction": "Warmer"}).json()
    assert whole["scope"] == "letter" and len(whole["paragraphs"]) == 4
    assert keyed_user.get(f"/api/applications/{app_id}").json()["coverLetter"]["paragraphs"][0]["text"] == \
        "Thank you for considering my application."  # refine suggests; it doesn't save


# ---- editing the résumé --------------------------------------------------------------------------------------


def test_edits_keep_facts_and_sources_honest(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={"generate": False})
    app_id, resume = detail["id"], copy.deepcopy(detail["resume"])
    experience = next(s for s in resume["sections"] if s["type"] == "experience")
    acme = experience["items"][0]
    acme["company"] = "Acme Payments Unicorn"  # G1: facts come from the master, not the editor
    acme["position"] = "CTO"
    first = acme["bullets"][0]
    first["text"] = first["text"] + " Grew revenue 99%."  # G3: a number its sources don't have
    acme["bullets"].append({"id": "ub-1", "text": "Spoke at KubeCon.", "sourceIds": [], "origin": "user"})
    acme["bullets"].append({"id": "ub-2", "text": "Borrowed a bullet.", "sourceIds": ["hooli.b1"], "origin": "ai"})
    experience["items"].reverse()  # reordering is allowed
    resume["sections"] = [s for s in resume["sections"] if s["type"] != "certifications"]  # so is excluding

    saved = keyed_user.put(f"/api/applications/{app_id}/resume", json={"document": resume})
    assert saved.status_code == 200, saved.text
    doc = saved.json()["document"]
    experience = next(s for s in doc["sections"] if s["type"] == "experience")
    acme = next(i for i in experience["items"] if i["sourceId"] == "acme")
    assert (acme["company"], acme["position"]) == ("Acme Payments", "Senior Software Engineer, Platform")
    assert experience["items"][-1]["sourceId"] == "acme"
    assert "certifications" not in {s["type"] for s in doc["sections"]}
    by_id = {b["id"]: b for b in bullets(doc)}
    assert by_id[first["id"]]["edited"] is True
    assert any(w["code"] == "NUMBER_NOT_IN_SOURCE" for w in by_id[first["id"]]["warnings"])
    assert by_id["ub-1"]["origin"] == "user" and by_id["ub-1"]["warnings"][0]["code"] == "NO_SOURCE"
    assert by_id["ub-2"]["sourceIds"] == [] and by_id["ub-2"]["origin"] == "user"  # G2: another role's bullet
    assert doc["analysis"]["coverage"]["score"] is not None
    assert keyed_user.get(f"/api/applications/{app_id}").json()["resume"] == doc  # persisted

    broken = copy.deepcopy(doc)
    next(s for s in broken["sections"] if s["type"] == "experience")["items"][0]["sourceId"] = "no-such-role"
    response = keyed_user.put(f"/api/applications/{app_id}/resume", json={"document": broken})
    assert response.status_code == 422 and response.json()["errors"][0]["path"].startswith("sections[")


def test_claim_audit_flags_embellishment_until_the_text_changes(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={"generate": False})
    app_id, resume = detail["id"], copy.deepcopy(detail["resume"])
    assert resume["analysis"]["audit"]["status"] == "done"  # on by default (TLR-8)
    target = bullets(resume)[0]
    target["text"] = "Led migration of 400 payment services, cutting cost 90%."
    keyed_user.put(f"/api/applications/{app_id}/resume", json={"document": resume})
    assert keyed_user.post(f"/api/applications/{app_id}/audit").status_code == 202
    drain(app)
    doc = keyed_user.get(f"/api/applications/{app_id}").json()["resume"]
    flagged = {b["id"]: b for b in bullets(doc)}[target["id"]]
    assert any(w["code"] == "CLAIM_EMBELLISHED" and "400" in w["message"] for w in flagged["warnings"])

    flagged["text"] = flagged["aiText"]  # revert to the AI draft: the old verdict no longer applies
    doc = keyed_user.put(f"/api/applications/{app_id}/resume", json={"document": doc}).json()["document"]
    assert not any(w["code"].startswith("CLAIM_") for w in {b["id"]: b for b in bullets(doc)}[target["id"]]["warnings"])


def test_refine_suggests_without_saving(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={"generate": False})
    app_id, resume = detail["id"], detail["resume"]
    first = bullets(resume)[0]

    bullet = keyed_user.post(f"/api/applications/{app_id}/resume/refine",
                             json={"scope": "bullet", "targetId": first["id"], "instruction": "Make it shorter"}).json()
    assert [c["targetId"] for c in bullet["changes"]] == [first["id"]] and bullet["costUsd"] > 0
    change = bullet["changes"][0]
    assert change["before"] == first["text"] and len(change["after"]) < len(first["text"])
    assert change["sourceIds"] == first["sourceIds"]

    item = keyed_user.post(f"/api/applications/{app_id}/resume/refine",
                           json={"scope": "item", "targetId": "acme", "instruction": "Lead with leadership"}).json()
    assert item["items"][0]["itemId"] == "acme" and all(b["origin"] == "ai" for b in item["items"][0]["bullets"])

    summary = keyed_user.post(f"/api/applications/{app_id}/resume/refine",
                              json={"scope": "summary", "instruction": "Tighter"}).json()
    assert [c["kind"] for c in summary["changes"]] == ["summary"]
    document = keyed_user.post(f"/api/applications/{app_id}/resume/refine",
                               json={"scope": "document", "instruction": "Add a metric for every bullet"}).json()
    assert len(document["changes"]) >= 3 and document["notes"]  # the fake explains it can't invent numbers

    assert keyed_user.post(f"/api/applications/{app_id}/resume/refine",
                           json={"scope": "bullet", "targetId": "tb-999", "instruction": "x"}).status_code == 422
    assert keyed_user.get(f"/api/applications/{app_id}").json()["resume"] == resume  # nothing was applied
    stages = {s["stage"] for s in keyed_user.get("/api/account/usage").json()["byStage"]}
    assert "refine" in stages


# ---- exports, review-first, regenerate, duplicate ----------------------------------------------------------------


def test_letter_and_packet_exports(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, letter={"recipient": RECIPIENT})
    app_id = detail["id"]
    letter_pdf = keyed_user.get(f"/api/applications/{app_id}/preview.pdf", params={"doc": "cover-letter"})
    assert letter_pdf.status_code == 200 and letter_pdf.headers["x-page-count"] == "1"  # CVL-6: one page
    text = PdfReader(io.BytesIO(letter_pdf.content)).pages[0].extract_text()
    assert "Dear Priya Shah," in text and "Jordan Rivera" in text

    packet = keyed_user.get(f"/api/applications/{app_id}/export", params={"doc": "packet", "format": "pdf"})
    reader = PdfReader(io.BytesIO(packet.content))
    resume_pages = int(keyed_user.get(f"/api/applications/{app_id}/preview.pdf").headers["x-page-count"])
    assert len(reader.pages) == 1 + resume_pages
    assert [o.title for o in reader.outline] == ["Cover letter", "Résumé"]
    assert packet.headers["content-disposition"].endswith('_Application.pdf"')
    md = keyed_user.get(f"/api/applications/{app_id}/export", params={"doc": "cover-letter", "format": "md"})
    assert md.text.startswith("**Jordan Rivera**") and "Dear Priya Shah," in md.text
    assert keyed_user.get(f"/api/applications/{app_id}/export",
                          params={"doc": "packet", "format": "md"}).status_code == 422


def test_review_the_analysis_first_then_regenerate(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example, reviewAnalysis=True)
    app_id = detail["id"]
    assert detail["status"] == "review" and detail["resume"] is None and detail["analysis"]
    events = keyed_user.get(f"/api/applications/{app_id}/events").text
    assert "event: review" in events

    keywords = [{"term": k["term"], "importance": 3 if k["term"] == "Terraform" else k["importance"],
                 "mustInclude": k["term"] == "Terraform"} for k in detail["analysis"]["keywords"]]
    keywords.append({"term": "Platform engineering", "importance": 2})
    edited = keyed_user.put(f"/api/applications/{app_id}/analysis",
                            json={"keywords": keywords, "suggestedEmphasis": ["Developer platforms"]})
    assert edited.status_code == 200
    assert next(k for k in edited.json()["keywords"] if k["term"] == "Terraform")["mustInclude"] is True
    assert keyed_user.post(f"/api/applications/{app_id}/continue").status_code == 202
    drain(app)
    detail = keyed_user.get(f"/api/applications/{app_id}").json()
    assert detail["status"] == "done" and detail["analysisEdited"] and detail["coverLetterStatus"] == "ready"
    assert "Platform engineering" in {k["term"] for k in detail["analysis"]["keywords"]}
    assert keyed_user.post(f"/api/applications/{app_id}/continue").status_code == 409

    before = detail["coverLetter"]
    assert keyed_user.post(f"/api/applications/{app_id}/regenerate", json={"letter": False}).status_code == 202
    drain(app)
    again = keyed_user.get(f"/api/applications/{app_id}").json()
    assert again["status"] == "done" and again["coverLetter"] == before  # the letter wasn't rewritten


def test_duplicate(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example)
    copy_out = keyed_user.post(f"/api/applications/{detail['id']}/duplicate")
    assert copy_out.status_code == 201
    twin = keyed_user.get(f"/api/applications/{copy_out.json()['id']}").json()
    assert twin["id"] != detail["id"] and twin["status"] == "done"
    assert twin["resume"]["sections"] == detail["resume"]["sections"]
    assert twin["resume"]["meta"]["applicationId"] == twin["id"]
    assert twin["coverLetter"]["paragraphs"] == detail["coverLetter"]["paragraphs"]
    assert len(keyed_user.get("/api/applications").json()) == 2


def test_interrupted_letters_are_marked_failed(app: FastAPI, keyed_user: Api, example) -> None:
    from app.db.models import Document
    from app.pipeline.run import mark_interrupted

    detail = application(app, keyed_user, example)

    async def interrupt() -> int:
        async with app.state.sessionmaker() as db:
            from sqlalchemy import select

            document = (await db.execute(select(Document).where(Document.kind == "cover_letter"))).scalar_one()
            document.status = "generating"
            await db.commit()
            return await mark_interrupted(db)

    assert app.state.test_portal.call(interrupt) == 1
    detail = keyed_user.get(f"/api/applications/{detail['id']}").json()
    assert detail["coverLetterStatus"] == "failed" and detail["coverLetterError"]["code"] == "interrupted"


def test_letter_highlights_are_checked_and_editable(app: FastAPI, keyed_user: Api, example) -> None:
    detail = application(app, keyed_user, example)
    app_id, letter = detail["id"], copy.deepcopy(detail["coverLetter"])
    highlights = letter["highlights"]
    assert 1 <= len(highlights) <= 3 and all(h["sourceIds"] and h["warnings"] == [] for h in highlights)

    highlights[0]["value"] = "97%"  # a number its sources don't have (G3)
    highlights.append({"value": "12 teams", "label": "unsourced", "sourceIds": ["not-in-master"]})
    saved = keyed_user.put(f"/api/applications/{app_id}/cover-letter", json={"document": letter}).json()["document"]
    first, added = saved["highlights"][0], saved["highlights"][-1]
    assert [w["code"] for w in first["warnings"]] == ["NUMBER_NOT_IN_SOURCE"]
    assert added["sourceIds"] == [] and "NO_SOURCE" in [w["code"] for w in added["warnings"]]
    assert {w["targetId"] for w in saved["analysis"]["warnings"]} >= {"highlight:0"}

    too_long = copy.deepcopy(saved)
    too_long["highlights"][0]["value"] = "x" * 30
    assert keyed_user.put(f"/api/applications/{app_id}/cover-letter", json={"document": too_long}).status_code == 422
    without_key = {k: v for k, v in saved.items() if k != "highlights"}  # an older client: kept as they were
    kept = keyed_user.put(f"/api/applications/{app_id}/cover-letter", json={"document": without_key}).json()
    assert len(kept["document"]["highlights"]) == len(saved["highlights"])
    cleared = keyed_user.put(f"/api/applications/{app_id}/cover-letter",
                             json={"document": {**saved, "highlights": []}}).json()
    assert cleared["document"]["highlights"] == []
