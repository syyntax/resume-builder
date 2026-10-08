"""Accessibility audit (DESIGN.md §6, WCAG 2.1 AA): axe-core over every page, light and dark, desktop and phone.

Runs against a fresh, running app with the offline model (CI does this after the ZAP scan):

    python -m tests.a11y http://localhost:8080 --setup-token TOKEN --axe path/to/axe.min.js

It creates the admin account with the setup token, then a master résumé, an application with a cover letter,
and an import to review, so the pages it audits have content. Any violation fails the run. axe-core comes
from the frontend's dev dependencies (frontend/node_modules/axe-core/axe.min.js).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx2 as httpx
from playwright.async_api import Page, async_playwright

EXAMPLE = Path(__file__).resolve().parents[1] / "app" / "masters" / "example_master.json"
EMAIL = "a11y@example.com"
POSTING = "Staff Platform Engineer at Globex\nWe need a platform engineer.\n- Kubernetes on AWS\n- Terraform\n"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]
VIEWPORTS = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 390, "height": 844}}
GUEST_PAGES = [("sign in", "/login"), ("register", "/register"), ("forgot password", "/forgot-password")]


def seed(base: str, token: str, password: str) -> list[tuple[str, str]]:
    """Create the admin and some content; return the pages to audit."""
    c = httpx.Client(base_url=base, headers={"Origin": base}, timeout=60)
    r = c.post("/api/auth/setup", json={"token": token, "email": EMAIL, "password": password,
                                        "displayName": "Audit Admin"})
    r.raise_for_status()
    c.headers["X-CSRF-Token"] = r.json()["csrfToken"]
    c.put("/api/account/api-key", json={"apiKey": "sk-ant-api03-offline-audit-0123456789abcdefWXYZ",
                                        "password": password}).raise_for_status()
    r = c.post("/api/master-resumes", content=EXAMPLE.read_bytes(), headers={"content-type": "application/json"})
    r.raise_for_status()
    master = r.json()["master"]["id"]
    r = c.post("/api/applications", json={"masterId": master, "job": {"text": POSTING, "company": "Globex"},
                                          "coverLetter": {"generate": True}})
    r.raise_for_status()
    application = r.json()["id"]
    pasted = "Jordan Rivera\nPlatform engineer.\n" + "Built things at Acme. " * 20
    r = c.post("/api/imports/text", json={"text": pasted})
    r.raise_for_status()
    imported = r.json()["id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        a = c.get(f"/api/applications/{application}").json()
        i = c.get(f"/api/imports/{imported}").json()
        if a["status"] == "done" and a["coverLetterStatus"] != "generating" and i["status"] == "ready":
            break
        time.sleep(0.5)
    else:
        raise SystemExit("The application or import didn't finish in time.")
    return [
        ("home", "/"), ("masters", "/masters"), ("master", f"/masters/{master}"),
        ("master editor", f"/masters/{master}/edit"), ("import start", "/masters/import"),
        ("import review", f"/imports/{imported}"), ("applications", "/applications"),
        ("new application", "/applications/new"), ("résumé workspace", f"/applications/{application}"),
        ("letter workspace", f"/applications/{application}#letter"), ("account", "/account"),
        *((f"admin {tab}", f"/admin?tab={tab}") for tab in ("users", "settings", "ai", "usage", "audit")),
    ]


async def audit(page: Page, axe: str) -> list[dict[str, Any]]:
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(500)
    await page.add_script_tag(content=axe)
    return await page.evaluate("""async (tags) => {
        const r = await axe.run(document, {runOnly: {type: 'tag', values: tags}});
        return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help,
            nodes: v.nodes.slice(0, 5).map(n => ({target: n.target.join(' '), summary: n.failureSummary}))}));
    }""", TAGS)


async def run(base: str, password: str, pages: list[tuple[str, str]], axe: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for size, viewport in VIEWPORTS.items():
            for scheme in ("light", "dark"):
                where = f"{size}, {scheme}"
                # bypass_csp: axe is injected as an inline script, which the app's CSP rightly forbids
                guest = await browser.new_context(color_scheme=scheme, viewport=viewport, bypass_csp=True)
                page = await guest.new_page()
                for name, path in GUEST_PAGES:
                    await page.goto(base + path)
                    found += [{"page": name, "where": where, **v} for v in await audit(page, axe)]
                await guest.close()
                context = await browser.new_context(color_scheme=scheme, viewport=viewport, bypass_csp=True)
                page = await context.new_page()
                await page.goto(base + "/login")
                await page.get_by_label("Email").fill(EMAIL)
                await page.get_by_label("Password").fill(password)
                await page.get_by_role("button", name="Sign in").click()
                await page.wait_for_url(base + "/")
                for name, path in pages:
                    await page.goto(base + path.split("#")[0])
                    if path.endswith("#letter"):
                        await page.get_by_role("tab", name="Cover letter").click()
                    found += [{"page": name, "where": where, **v} for v in await audit(page, axe)]
                await context.close()
        await browser.close()
    return found


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.a11y", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base", help="the app's address, e.g. http://localhost:8080")
    parser.add_argument("--setup-token", required=True, help="the first-run setup token from the app's log")
    parser.add_argument("--axe", type=Path, required=True, help="axe-core's axe.min.js")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    password = secrets.token_urlsafe(18)
    pages = seed(base, args.setup_token, password)
    found = asyncio.run(run(base, password, pages, args.axe.read_text(encoding="utf-8")))
    audited = (len(pages) + len(GUEST_PAGES)) * 2 * len(VIEWPORTS)
    if not found:
        print(f"No accessibility violations on {audited} page views.")
        return 0
    print(f"{len(found)} accessibility violations on {audited} page views:")
    for v in found:
        print(f"- {v['page']} ({v['where']}): {v['id']} [{v['impact']}] {v['help']}")
        for node in v["nodes"]:
            print(f"    {node['target']}: {' '.join(node['summary'].split())[:300]}")
    print(json.dumps(found, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
