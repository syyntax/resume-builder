"""Admin system settings (ADM-3), user preferences and file names (EXP-6), and the account export (AUTH-8)."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from fastapi import FastAPI
from sqlalchemy import func, select

from app.db.models import AiCall
from app.pipeline.export import filename
from tests.conftest import POSTING, Api, drain


def new_application(app: FastAPI, user: Api, example: dict[str, Any]) -> dict[str, Any]:
    master_id = user.post("/api/master-resumes", json=example).json()["master"]["id"]
    created = user.post("/api/applications", json={"masterId": master_id, "job": {"text": POSTING}})
    assert created.status_code == 202, created.text
    drain(app)
    return user.get(f"/api/applications/{created.json()['id']}").json()


def test_admins_set_ai_behaviour_and_the_default_design(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    ai = admin.get("/api/admin/ai-settings").json()
    assert ai["effort"] == {"analyze": "medium", "tailor": "high", "letter": "high", "import": "high",
                            "refine": "medium", "audit": "low", "condense": "low"} and ai["claimAudit"] is True
    changed = admin.put("/api/admin/ai-settings", json={"effort": {**ai["effort"], "tailor": "medium"},
                                                        "claimAudit": False})
    assert changed.status_code == 200 and changed.json()["effort"]["tailor"] == "medium"
    assert app.state.settings.ai_effort_tailor == "medium" and app.state.settings.ai_claim_audit is False

    theme = {"accent": "#7A1F3D", "fonts": "garamond", "density": "compact", "paper": "a4", "margins": "normal",
             "dateFormat": "YYYY", "contactIcons": False}
    saved = admin.put("/api/admin/settings", json={"defaultDesign": {"template": "ledger", "theme": theme}})
    assert saved.status_code == 200 and saved.json()["defaultDesign"]["template"] == "ledger"
    assert admin.put("/api/admin/settings", json={"defaultDesign": {"template": "comic", "theme": theme}}
                     ).status_code == 422

    detail = new_application(app, keyed_user, example)
    assert detail["template"] == "ledger" and detail["theme"] == theme

    async def audits() -> int:
        async with app.state.sessionmaker() as db:
            return (await db.execute(select(func.count()).select_from(AiCall).where(AiCall.stage == "audit"))
                    ).scalar_one()

    assert app.state.test_portal.call(audits) == 0  # the claim audit is off


def test_a_users_own_preferences_win(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    assert keyed_user.get("/api/account/preferences").json() == {
        "design": None, "coverLetter": True, "fileName": "{name}_{company}_{role}_{doc}"}
    theme = {"accent": "#0F766E", "fonts": "plex", "density": "balanced", "paper": "letter", "margins": "narrow",
             "dateFormat": "MMM YYYY", "contactIcons": True}
    prefs = {"design": {"template": "atlas", "theme": theme}, "coverLetter": False,
             "fileName": "{last}, {first} - {doc}"}
    assert keyed_user.put("/api/account/preferences", json=prefs).json() == prefs
    assert keyed_user.put("/api/account/preferences", json={**prefs, "fileName": "../{doc}"}).status_code == 422
    assert keyed_user.put("/api/account/preferences",
                          json={**prefs, "design": {"template": "comic", "theme": theme}}).status_code == 422
    admin.put("/api/admin/settings", json={"defaultDesign": {"template": "ledger", "theme": theme}})

    detail = new_application(app, keyed_user, example)
    assert detail["template"] == "atlas" and detail["theme"]["margins"] == "narrow"
    export = keyed_user.get(f"/api/applications/{detail['id']}/export", params={"format": "pdf"})
    assert export.headers["content-disposition"] == 'attachment; filename="Rivera, Jordan - Resume.pdf"'


def test_file_names_follow_the_pattern() -> None:
    resume, job = {"basics": {"name": "Ana María de la Cruz"}}, {"company": "Acme & Co.", "title": "Lead / SRE"}
    assert filename(resume, job, "Resume", "pdf") == "Ana-Mar-a-de-la-Cruz_Acme-Co_Lead-SRE_Resume.pdf"
    assert filename(resume, {}, "Cover-Letter", "docx", "{doc} for {company} ({role})") == "Cover-Letter for.docx"
    assert filename({}, {}, "Resume", "md", "{name}") == "Resume.md"  # nothing left: the document kind


def test_the_account_export_has_everything_but_secrets(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    detail = new_application(app, keyed_user, example)
    archive = zipfile.ZipFile(io.BytesIO(keyed_user.get("/api/account/export").content))
    names = archive.namelist()
    assert f"applications/{detail['id']}/application.json" in names
    folder = f"applications/{detail['id']}"
    assert f"{folder}/resume.json" in names and f"{folder}/cover-letter.json" in names
    saved = json.loads(archive.read(f"applications/{detail['id']}/application.json"))
    assert saved["job"]["posting"] == POSTING.strip() and saved["job"]["analysis"]
    everything = b"".join(archive.read(n) for n in names)
    assert b"sk-ant-" not in everything and b"totp" not in everything.lower() and b"passwordHash" not in everything
    account = json.loads(archive.read("account.json"))
    assert account["preferences"]["fileName"] and "mfaEnabled" in account["user"]
