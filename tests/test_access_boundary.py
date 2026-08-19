"""Tests for the access boundary.

These are not quality tests. A failure here is a security finding, so they
assert the boundary directly rather than testing observable behavior.
"""
from __future__ import annotations

import numpy as np
import pytest

from retrieval.permissioned import Document, PermissionedRetriever, Principal


def fake_embed(texts):
    # Deterministic pseudo-embedding: content-derived, so semantically
    # identical text embeds identically and tests are reproducible.
    out = np.zeros((len(texts), 8), dtype=float)
    for i, text in enumerate(texts):
        for j, ch in enumerate(text[:8]):
            out[i, j] = (ord(ch) % 17) / 17.0
    return out


@pytest.fixture
def retriever():
    docs = [
        Document("public-1", "general support policy", frozenset({"agent"})),
        Document("public-2", "general refund policy", frozenset({"agent"})),
        Document("hr-1", "general compensation policy", frozenset({"hr"})),
        Document("legal-1", "general litigation policy", frozenset({"legal"})),
    ]
    r = PermissionedRetriever(fake_embed)
    r.build(docs)
    return r


def test_agent_cannot_retrieve_hr_document(retriever):
    agent = Principal("u1", frozenset({"agent"}))
    hits = retriever.search("general compensation policy", agent, k=5,
                            min_score=-1.0)
    assert all(doc.doc_id != "hr-1" for doc, _ in hits)


def test_result_count_does_not_reveal_hidden_documents(retriever):
    """The count leak: an agent searching a query that strongly matches an HR
    document must not get FEWER results than the same search over only the
    documents they can see. If they do, the count itself is a signal."""
    agent = Principal("u1", frozenset({"agent"}))
    hits = retriever.search("general compensation policy", agent, k=2,
                            min_score=-1.0)
    # Two agent-visible documents exist, so a k=2 search must return two.
    assert len(hits) == 2


def test_explicit_grant_overrides_role(retriever):
    agent = Principal("u1", frozenset({"agent"}),
                      granted_docs=frozenset({"hr-1"}))
    hits = retriever.search("general compensation policy", agent, k=5,
                            min_score=-1.0)
    assert any(doc.doc_id == "hr-1" for doc, _ in hits)


def test_no_roles_returns_nothing(retriever):
    nobody = Principal("u2", frozenset())
    assert retriever.search("general support policy", nobody, k=5,
                            min_score=-1.0) == []


def test_visibility_does_not_depend_on_query(retriever):
    """Visibility is a function of identity alone. The same principal must see
    the same document set regardless of what they search for."""
    agent = Principal("u1", frozenset({"agent"}))
    seen = set()
    for query in ("compensation", "litigation", "refund", "zzz nonsense"):
        hits = retriever.search(query, agent, k=10, min_score=-1.0)
        seen.update(doc.doc_id for doc, _ in hits)
    assert seen == {"public-1", "public-2"}
