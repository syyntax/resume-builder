"""Merging an import into an existing master (IMP-6): the plan, picking what to add, and the new version."""

from __future__ import annotations

import copy
from typing import Any

from fastapi import FastAPI

from app.masters import merge
from tests import corpus
from tests.conftest import Api
from tests.test_imports import imported

MASTER: dict[str, Any] = {
    "basics": {"name": "Jordan Rivera"},
    "headlines": [{"id": "h1", "text": "Senior Platform Engineer"}],
    "work": [{"id": "acme", "company": "Acme Payments", "position": "Senior Software Engineer, Platform",
              "startDate": "2021-03", "highlights": [
                  {"id": "acme.b1", "text": "Led migration of 40 services from EC2 to Kubernetes."},
                  {"id": "acme.b2", "text": "Mentored 4 engineers.",
                   "variants": [{"text": "Mentored four engineers through design reviews."}]}]}],
    "skills": [{"id": "k8s", "name": "Kubernetes", "aliases": ["K8s"]}],
}

IMPORTED: dict[str, Any] = {
    "basics": {"name": "Jordan Rivera"},
    "headlines": [{"id": "x1", "text": "Senior platform engineer"}, {"id": "x2", "text": "SRE lead"}],
    "work": [
        {"id": "acme", "company": "ACME Payments", "position": "Sr. Software Engineer", "startDate": "2021-03",
         "highlights": [{"id": "acme.b1", "text": "Led the migration of 40 services from EC2 to Kubernetes."},
                        {"id": "acme.b9", "text": "Mentored four engineers through design reviews."},
                        {"id": "acme.b3", "text": "Cut CI time from 42 to 9 minutes."}]},
        {"id": "initech", "company": "Initech", "position": "Software Engineer", "startDate": "2017-06",
         "highlights": [{"id": "i1", "text": "Built Go tooling."}]},
    ],
    "skills": [{"id": "k", "name": "k8s"}, {"id": "t", "name": "Terraform"}],
}


def test_the_plan_finds_whats_new() -> None:
    by_key = {p.key: p for p in merge.plan(IMPORTED, MASTER)}
    acme = by_key["work:0"]
    # the same employer and start date, reworded bullets recognized (including a variant), one bullet new
    assert (acme.status, acme.match_id, acme.bullets) == ("match", "acme", ["Cut CI time from 42 to 9 minutes."])
    assert acme.similar_to == [None]
    assert by_key["work:1"].status == "new" and by_key["work:1"].bullets == ["Built Go tooling."]
    assert by_key["skills:0"].status == "same" and by_key["skills:1"].status == "new"  # an alias counts
    assert by_key["headlines:0"].status == "same" and by_key["headlines:1"].status == "new"


def test_applying_adds_only_whats_picked_and_changes_nothing_else() -> None:
    merged = merge.apply(IMPORTED, MASTER, {"work:0": [0], "work:1": None, "skills:1": None, "skills:0": None,
                                            "headlines:1": None, "nope:3": None, "work:0x": None})
    assert merged["work"][0]["highlights"][:2] == MASTER["work"][0]["highlights"]  # untouched
    assert merged["work"][0]["highlights"][2] == {"text": "Cut CI time from 42 to 9 minutes."}  # no clashing id
    assert merged["work"][1]["company"] == "Initech" and "id" not in merged["work"][1]
    assert [s["name"] for s in merged["skills"]] == ["Kubernetes", "Terraform"]
    assert [h["text"] for h in merged["headlines"]] == ["Senior Platform Engineer", "SRE lead"]
    nothing = merge.apply(IMPORTED, MASTER, {"work:0": []})  # a match with no bullets picked adds nothing
    assert nothing == copy.deepcopy(MASTER)


def test_merging_an_import_into_a_master(app: FastAPI, keyed_user: Api, example: dict[str, Any]) -> None:
    master = keyed_user.post("/api/master-resumes", json=example).json()
    master_id, base = master["master"]["id"], master["version"]["id"]
    detail = imported(app, keyed_user, corpus.text_pdf())
    document = detail["document"]

    plan = keyed_user.post(f"/api/imports/{detail['id']}/merge-plan", json={"masterId": master_id,
                                                                          "document": document})
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["baseVersionId"] == base and body["items"]
    statuses = {i["status"] for i in body["items"]}
    assert "same" in statuses  # the corpus résumé is the example's content: much of it is already there
    acme = next(i for i in body["items"] if i["key"] == "work:0")
    # a reworded bullet about the same work is pointed out, with the master bullet it resembles
    canary = acme["bullets"].index(next(b for b in acme["bullets"] if "canary" in b))
    assert "SLO-driven canary release pipeline" in acme["similarTo"][canary]
    picks = {i["key"]: None for i in body["items"] if i["status"] == "new"}
    picks.update({i["key"]: list(range(len(i["bullets"]))) for i in body["items"] if i["status"] == "match"})

    stale = keyed_user.post(f"/api/imports/{detail['id']}/merge", json={
        "masterId": master_id, "document": document, "baseVersionId": "mv_other", "selections": picks})
    assert stale.status_code == 409
    if picks:
        merged = keyed_user.post(f"/api/imports/{detail['id']}/merge", json={
            "masterId": master_id, "document": document, "baseVersionId": base, "selections": picks})
        assert merged.status_code == 201, merged.text
        saved = merged.json()
        assert saved["master"]["id"] == master_id and saved["master"]["versionCount"] == 2
        assert saved["version"]["sourceFile"] is not None  # the original stays with the version (IMP-8)
        assert keyed_user.get(f"/api/imports/{detail['id']}").json()["status"] == "accepted"
    else:
        nothing = keyed_user.post(f"/api/imports/{detail['id']}/merge", json={
            "masterId": master_id, "document": document, "baseVersionId": base, "selections": {}})
        assert nothing.status_code == 422

    other = Api(app)
    assert other.post(f"/api/imports/{detail['id']}/merge-plan",
                      json={"masterId": master_id, "document": document}).status_code in (401, 403)
