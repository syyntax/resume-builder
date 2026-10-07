"""Sample documents for rendering tests: the content of the approved Meridian mockup (mockups/meridian.html)."""

from __future__ import annotations

import copy
from typing import Any


def _bullets(*texts: str) -> list[dict[str, Any]]:
    return [{"id": f"tb-{i}", "text": t, "sourceIds": [], "relevance": 4, "keywords": [], "origin": "ai",
             "edited": False, "warnings": []} for i, t in enumerate(texts, start=1)]


RESUME: dict[str, Any] = {
    "meta": {"schemaVersion": "1.0", "job": {"company": "Globex", "title": "Staff Platform Engineer"}},
    "basics": {
        "name": "Jordan Rivera", "email": "jordan@example.com", "phone": "(555) 010-0199",
        "location": {"city": "Denver", "region": "CO", "remote": True},
        "profiles": [{"network": "LinkedIn", "url": "https://linkedin.com/in/jrivera"},
                     {"network": "GitHub", "url": "https://github.com/jrivera"}],
    },
    "headline": {"text": "Senior Platform Engineer", "sourceIds": []},
    "summary": {"text": "Platform engineer with 9 years of experience building and running distributed systems at "
                        "scale. Led Kubernetes migrations, self-service developer platforms, and CI/CD modernization "
                        "that cut deploy times from hours to minutes. Pairs deep infrastructure expertise with "
                        "mentorship and clear technical writing.", "sourceIds": []},
    "sections": [
        {"type": "experience", "title": "Experience", "items": [
            {"sourceId": "acme", "company": "Acme Payments", "position": "Senior Software Engineer, Platform",
             "location": "Denver, CO", "startDate": "2021-03", "bullets": _bullets(
                 "Led migration of 40 payment services from EC2 to Kubernetes (EKS), cutting p99 latency 45% and "
                 "infrastructure cost $380K per year.",
                 "Designed a self-service developer platform on Backstage, Argo CD, and reusable Terraform modules; "
                 "adopted by 22 teams, reducing new-service setup from 2 weeks to 1 day.",
                 "Built an SLO-driven canary release pipeline with Argo Rollouts and automated rollback, reducing "
                 "failed production releases by 60%.",
                 "Redesigned on-call and incident review for the platform group, lowering mean time to recovery "
                 "from 54 to 18 minutes.",
                 "Mentored 4 engineers through design reviews and pairing; two were promoted to senior within 18 "
                 "months.")},
            {"sourceId": "initech-2", "company": "Initech", "position": "Software Engineer II",
             "location": "Austin, TX", "startDate": "2019-02", "endDate": "2021-02", "bullets": _bullets(
                 "Rebuilt the monorepo build on Bazel with remote caching, cutting CI time from 42 to 9 minutes for "
                 "150 engineers.",
                 "Created Go tooling that standardized service-mesh mTLS configuration across 60 services.")},
            {"sourceId": "initech-1", "company": "Initech", "position": "Software Engineer", "location": "Austin, TX",
             "startDate": "2017-06", "endDate": "2019-02", "bullets": _bullets(
                 "Ran Postgres fleet upgrades (9.6 → 12) across 30 clusters with zero customer-facing downtime.")},
        ]},
        {"type": "earlier-experience", "title": "Earlier", "items": [
            {"sourceId": "hooli", "company": "Hooli", "position": "Junior Software Engineer", "location": "Austin, TX",
             "startDate": "2016", "endDate": "2017"}]},
        {"type": "projects", "title": "Projects", "items": [
            {"sourceId": "tfguard", "name": "tf-guard", "description": "Open-source Terraform policy linter (Go)",
             "url": "https://github.com/jrivera/tf-guard", "bullets": _bullets(
                 "Reached 1.2K GitHub stars; used in CI by 40+ organizations to block insecure infrastructure changes "
                 "before merge.")}]},
        {"type": "skills", "title": "Skills", "groups": [
            {"name": "Languages", "items": [{"skillId": s, "display": s}
                                            for s in ("Go", "Python", "TypeScript", "Bash")]},
            {"name": "Cloud & Infrastructure", "items": [{"skillId": s, "display": s} for s in (
                "Kubernetes", "AWS (EKS, EC2, RDS)", "Terraform", "Helm", "Argo CD", "Backstage")]},
            {"name": "Observability", "items": [{"skillId": s, "display": s} for s in (
                "Prometheus", "Grafana", "OpenTelemetry")]},
            {"name": "Practices", "items": [{"skillId": s, "display": s} for s in (
                "Platform Engineering", "SRE", "CI/CD", "Incident Management")]},
        ]},
        {"type": "certifications", "title": "Certifications", "items": [
            {"sourceId": "cka", "name": "Certified Kubernetes Administrator (CKA)", "issuer": "CNCF", "date": "2023"},
            {"sourceId": "aws", "name": "AWS Solutions Architect – Associate", "issuer": "Amazon Web Services",
             "date": "2022"}]},
        {"type": "education", "title": "Education", "items": [
            {"sourceId": "cu", "institution": "University of Colorado Boulder", "studyType": "B.S.",
             "area": "Computer Science", "endDate": "2016"}]},
    ],
    "analysis": {"coverage": {"matched": ["Kubernetes", "Terraform", "AWS"]}},
}

LETTER: dict[str, Any] = {
    "sender": RESUME["basics"] | {"label": "Senior Platform Engineer"},
    "date": "2026-10-06",
    "recipient": {"name": "Priya Shah", "title": "Director of Platform Engineering", "company": "Globex Corporation",
                  "address": ["San Francisco, CA"]},
    "subject": "Staff Platform Engineer",
    "salutation": "Dear Priya Shah,",
    "paragraphs": [{"id": f"p{i}", "text": t} for i, t in enumerate([
        "Globex is looking for a Staff Platform Engineer to turn its internal platform into a product engineers "
        "choose to use. That has been my focus for the past four years at Acme Payments, where the platform I "
        "designed now serves 22 product teams.",
        "At Acme, I led the migration of 40 payment services from EC2 to Kubernetes, cutting p99 latency by 45% and "
        "saving $380K a year in infrastructure costs.",
        "Your posting describes reliability as a product feature, which matches how I work.",
        "I would enjoy talking about how I could help Globex’s platform scale. Thank you for your time.",
    ], start=1)],
    "closing": "Sincerely,",
    "signature": "Jordan Rivera",
}


def long_resume(roles: int = 8) -> dict[str, Any]:
    """The sample with many more roles, so it runs to a second page."""
    resume = copy.deepcopy(RESUME)
    experience = resume["sections"][0]["items"]
    for n in range(roles):
        experience.append({**copy.deepcopy(experience[0]), "sourceId": f"extra-{n}", "company": f"Company {n}",
                           "startDate": "2010-01", "endDate": "2012-01"})
    return resume
