from __future__ import annotations

import json
from typing import Any

import pytest

from app.masters.normalize import diff_documents, normalize, normalize_raw, slugify, summarize


def base(**extra: Any) -> dict[str, Any]:
    return {"basics": {"name": "Ann"}, "work": [{"company": "Co", "position": "Eng", "startDate": "2020"}], **extra}


def test_example_normalizes_cleanly_and_is_idempotent(example) -> None:
    first = normalize(example)
    assert first.ok and first.errors == [] and first.warnings == []
    second = normalize(json.loads(json.dumps(first.document)))
    assert second.document == first.document


def test_string_bullets_become_objects_with_ids() -> None:
    doc = base()
    doc["work"][0]["highlights"] = ["One", {"text": "Two"}, {"id": "keep-me", "text": "Three"}]
    result = normalize(doc)
    assert [h["id"] for h in result.document["work"][0]["highlights"]] == ["work-1.b1", "work-1.b2", "keep-me"]


def test_generated_ids_avoid_collisions() -> None:
    doc = base(projects=[{"id": "work-1", "name": "Taken"}])
    result = normalize(doc)
    assert result.document["work"][0]["id"] == "work-1-2"


@pytest.mark.parametrize(("name", "slug"), [("C++", "cpp"), ("C#", "csharp"), ("Node.js", "nodedotjs"),
                                            ("Amazon Web Services", "amazon-web-services"), ("???", "skill")])
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_skill_refs_resolve_by_id_name_or_alias() -> None:
    doc = base(skills=[{"name": "Kubernetes", "aliases": ["K8s"]}, {"id": "py", "name": "Python"}])
    doc["work"][0]["skills"] = ["k8s", "PYTHON", "py", "kubernetes"]
    result = normalize(doc)
    assert result.errors == []
    assert result.document["work"][0]["skills"] == ["kubernetes", "py", "py", "kubernetes"]


def test_unknown_and_ambiguous_skill_refs() -> None:
    doc = base(skills=[{"name": "Go", "aliases": ["golang"]}, {"name": "Golang Tools", "aliases": ["golang"]}])
    doc["work"][0]["skills"] = ["rust", "golang"]
    paths = {e.path: e.message for e in normalize(doc).errors}
    assert paths["work[0].skills[0]"].startswith('unknown skill "rust"')
    assert "more than one skill" in paths["work[0].skills[1]"]


@pytest.mark.parametrize(("value", "expected"), [("2021-3", "2021-03"), ("2021-03-05", "2021-03-05"),
                                                 (2016, "2016"), ("  2019 ", "2019")])
def test_dates_are_normalized(value: Any, expected: str) -> None:
    doc = base()
    doc["work"][0]["startDate"] = value
    assert normalize(doc).document["work"][0]["startDate"] == expected


@pytest.mark.parametrize("end", ["present", "Current", None])
def test_present_end_dates(end: Any) -> None:
    doc = base()
    doc["work"][0]["endDate"] = end
    assert normalize(doc).document["work"][0]["endDate"] is None


@pytest.mark.parametrize(("value", "message"), [
    ("March 2021", 'expected YYYY, YYYY-MM, or YYYY-MM-DD, got "March 2021"'),
    ("2021-13", 'month must be 01-12, got "2021-13"'),
    ("2021-02-30", 'not a real date: "2021-02-30"'),
])
def test_bad_dates(value: str, message: str) -> None:
    doc = base()
    doc["work"][0]["startDate"] = value
    errors = normalize(doc).errors
    assert [(e.path, e.message) for e in errors] == [("work[0].startDate", message)]


def test_end_before_start_compares_partial_dates() -> None:
    same_year = base()
    same_year["work"][0].update(startDate="2020-06", endDate="2020")
    assert normalize(same_year).errors == []
    backwards = base()
    backwards["work"][0].update(startDate="2020-06", endDate="2020-05")
    assert normalize(backwards).errors[0].path == "work[0].endDate"


def test_duplicate_ids_are_errors() -> None:
    doc = base(projects=[{"id": "dup", "name": "A"}, {"id": "dup", "name": "B"}])
    errors = normalize(doc).errors
    assert errors[0].path == "projects[1].id" and "also used at projects[0]" in errors[0].message


def test_unknown_fields_are_kept_with_warnings() -> None:
    doc = base(favouriteColour="green")
    doc["work"][0]["teamSize"] = 6
    result = normalize(doc)
    assert result.ok
    assert {w.path for w in result.warnings} == {"favouriteColour", "work[0].teamSize"}
    assert result.document["favouriteColour"] == "green"
    assert result.document["work"][0]["teamSize"] == 6


def test_validation_error_paths_hide_union_internals() -> None:
    doc = base()
    doc["work"][0]["highlights"] = [{"tags": ["x"]}, 42]
    errors = [(e.path, e.message) for e in normalize(doc).errors]
    assert errors == [("work[0].highlights[0].text", "required"),
                      ("work[0].highlights[1]", 'expected a string, or an object with a "text" field')]


def test_top_level_problems() -> None:
    assert normalize_raw(b"[]").errors[0].message == "expected a JSON object at the top level"
    assert normalize_raw(b"\xff\xfe").errors[0].path == "(document)"
    assert normalize({"basics": {"name": "x"}}).errors[0].path == "work"
    assert normalize({"work": []}).errors[0].path == "basics"


def test_summary_and_diff(example) -> None:
    doc = normalize(example).document
    summary = summarize(doc)
    assert summary["counts"]["bullets"] == 13 and summary["name"] == "Jordan Rivera"
    changed = json.loads(json.dumps(doc))
    changed["basics"]["phone"] = "000"
    changed["skills"] = changed["skills"][:-1]
    diff = diff_documents(doc, changed)
    assert diff["basicsChanged"] is True and diff["removed"] == ["opentelemetry"] and diff["added"] == []
