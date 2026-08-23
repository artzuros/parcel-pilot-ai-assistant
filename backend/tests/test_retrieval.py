"""Retrieval tests — authority-aware search over the 6 extracted documents."""
import pathlib

import pytest

from app.executors.doc_search import doc_search_tool
from app.retrieval import index as ridx

EXTRACTED = ridx.EXTRACTED_DIR


@pytest.fixture(scope="module")
def search():
    if not list(EXTRACTED.glob("*.txt")):
        pytest.skip("Extracted docs missing — run docs-processing/extract_pdfs.py first")
    return ridx.DocSearch(EXTRACTED)


def test_v3_beats_v2_on_current_policy(search):
    r = search.search("first response SLA", max_results=5)
    assert r, "expected results for 'first response SLA'"
    assert r[0]["doc_id"].startswith("01_"), "v3 must top current-policy queries"


def test_deprecated_flag_surfaces(search):
    r = search.search("first response SLA", max_results=10)
    v2 = [x for x in r if x["doc_id"].startswith("02_")]
    assert v2, "v2 should still be retrievable as history"
    assert all(x["status"] == "DEPRECATED" for x in v2)


def test_agreement_surfaces_for_northstar(search):
    r = search.search("Northstar service agreement", max_results=5)
    assert r[0]["doc_id"].startswith("05_"), "agreement should top account-specific queries"
    # and it must stay in the top results for a mixed-terms query
    r2 = search.search("Northstar cancellation fee", max_results=5)
    assert any(x["doc_id"].startswith("05_") for x in r2[:3])


def test_sop_surfaces_for_cancellation(search):
    r = search.search("cancellation fee 250", max_results=5)
    assert any(x["doc_id"].startswith("03_") for x in r[:3])


def test_tokenize_lowercases_input():
    # Regression: `(text or "".lower())` bound .lower() to "" — nothing was
    # lowercased, so uppercase letters were dropped as unmatched tokens
    # (e.g. "TKT-501" tokenized to ["501"], killing recall on ticket/order IDs).
    assert ridx.tokenize("TKT-501") == ["tkt", "501"]
    assert ridx.tokenize("Northstar SLA") == ["northstar", "sla"]
    assert ridx.tokenize(None) == []


def test_known_issue_retrievable(search):
    r = search.search("bulk upload rows limit", max_results=5)
    assert any(x["doc_id"].startswith("04_") for x in r[:3])


def test_gibberish_returns_empty(search):
    assert search.search("zzzqqqzzz") == []
