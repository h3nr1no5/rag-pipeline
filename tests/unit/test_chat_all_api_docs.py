"""Unit tests for the all_api_docs detection logic extracted from the Chat page.

The production code in client/pages/3_💬_Chat.py computes:

    api_doc_ids = [doc["id"] for doc in documents
                   if doc["id"] in selected_doc_ids
                   and doc.get("chunking_strategy", {}).get("engine_type") == "api-docs"]
    show_api_docs = len(api_doc_ids) > 0
    all_api_docs = show_api_docs and len(api_doc_ids) == len(selected_doc_ids)

This module extracts that logic into a pure function and tests it.
"""



# ---------------------------------------------------------------------------
# Function under test — extracted from Streamlit page code
# ---------------------------------------------------------------------------


def compute_all_api_docs(documents, selected_doc_ids):
    """Determine whether api-docs documents are present and whether every
    selected document is an api-docs document.

    Parameters
    ----------
    documents : list[dict]
        Each dict has at least ``id`` (str) and
        ``chunking_strategy`` (dict with ``engine_type`` key, e.g.
        ``{"engine_type": "api-docs"}``).
    selected_doc_ids : list[str]
        IDs of currently selected documents.

    Returns
    -------
    tuple[bool, bool]
        ``(show_api_docs, all_api_docs)``.
    """
    api_doc_ids = []
    if selected_doc_ids:
        for doc in documents:
            if doc["id"] in selected_doc_ids:
                strategy = doc.get("chunking_strategy", {})
                if strategy.get("engine_type") == "api-docs":
                    api_doc_ids.append(doc["id"])

    show_api_docs = len(api_doc_ids) > 0
    all_api_docs = show_api_docs and len(api_doc_ids) == len(selected_doc_ids)
    return show_api_docs, all_api_docs


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------

# Shared fixture documents — reused across tests
REGULAR_DOC = {"id": "doc-1", "title": "README", "chunking_strategy": {"engine_type": "semantic"}}
API_DOC = {"id": "doc-2", "title": "API Ref", "chunking_strategy": {"engine_type": "api-docs"}}


def test_no_api_docs_documents_selected():
    """Scenario 1: only regular (non-api-docs) documents are selected.

    show_api_docs should be False, all_api_docs should be False.
    """
    docs = [
        REGULAR_DOC,
        API_DOC,
    ]
    selected = ["doc-1"]  # only the regular doc

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is False
    assert all_ is False


def test_all_selected_are_api_docs():
    """Scenario 2: every selected document is an api-docs document.

    Both show_api_docs and all_api_docs should be True.
    """
    docs = [
        REGULAR_DOC,
        API_DOC,
    ]
    selected = ["doc-2"]  # only the api-docs doc

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is True
    assert all_ is True


def test_mixed_selection():
    """Scenario 3: a mix of api-docs and regular documents are selected.

    show_api_docs should be True (at least one api-docs doc is present),
    but all_api_docs should be False (not every doc is api-docs).
    """
    docs = [
        REGULAR_DOC,
        API_DOC,
    ]
    selected = ["doc-1", "doc-2"]

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is True
    assert all_ is False


def test_no_documents_selected():
    """Scenario 4: no documents are selected at all.

    Both flags should be False.
    """
    docs = [
        REGULAR_DOC,
        API_DOC,
    ]
    selected = []

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is False
    assert all_ is False


def test_single_api_docs_document_selected():
    """Scenario 5: exactly one api-docs document is selected (no other docs).

    Both show_api_docs and all_api_docs should be True.
    """
    docs = [
        {
            "id": "api-only",
            "title": "Single API Doc",
            "chunking_strategy": {"engine_type": "api-docs"},
        },
    ]
    selected = ["api-only"]

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is True
    assert all_ is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_documents_list():
    """No documents exist at all, nothing is selected."""
    show, all_ = compute_all_api_docs([], [])
    assert show is False
    assert all_ is False


def test_api_doc_with_no_chunking_strategy():
    """A selected doc has no ``chunking_strategy`` key — should be treated
    as a non-api-docs document."""
    docs = [
        {"id": "bare", "title": "Bare Doc"},  # no chunking_strategy
    ]
    selected = ["bare"]

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is False
    assert all_ is False


def test_api_doc_with_empty_chunking_strategy():
    """A selected doc has an empty chunking_strategy — not api-docs."""
    docs = [
        {"id": "empty-strat", "title": "Empty Strat", "chunking_strategy": {}},
    ]
    selected = ["empty-strat"]

    show, all_ = compute_all_api_docs(docs, selected)
    assert show is False
    assert all_ is False


def test_selected_doc_not_in_documents_list():
    """A selected ID that doesn't appear in the documents list is silently
    ignored (the production code filters via ``if doc['id'] in selected_doc_ids``,
    so non-matching IDs produce no api_doc_ids entry)."""
    docs = [
        API_DOC,
    ]
    selected = ["doc-2", "nonexistent-id"]

    show, all_ = compute_all_api_docs(docs, selected)
    # "nonexistent-id" is not in documents, so only doc-2 counts
    # selected_doc_ids has 2 entries, api_doc_ids has 1 => all_api_docs = False
    assert show is True
    assert all_ is False
