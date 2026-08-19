"""Retrieval with access control enforced BEFORE the search, not after.

The ordering is the entire security property. Everything else in this file
follows from it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Principal:
    """Who is asking. Access is decided per USER, never per service.

    A service-level credential that can read everything, with the application
    deciding what to show, means any application bug is a data breach. Passing
    the user's identity to the retrieval layer means the boundary is enforced
    where the data lives.
    """

    user_id: str
    roles: frozenset[str]
    # Explicit per-document grants beyond role-based access.
    granted_docs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Document:
    doc_id: str
    text: str
    # Roles permitted to read this document. Empty means nobody by role;
    # access then requires an explicit grant.
    allowed_roles: frozenset[str]


class PermissionedRetriever:
    def __init__(self, embed_fn) -> None:
        self._embed = embed_fn
        self._docs: list[Document] = []
        self._vectors: np.ndarray | None = None
        # Precomputed per-role masks. Built once; a boolean index at query time
        # is far cheaper than evaluating a permission predicate per document
        # per query.
        self._role_mask: dict[str, np.ndarray] = {}

    def build(self, docs: list[Document]) -> None:
        self._docs = docs
        raw = self._embed([d.text for d in docs])
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        self._vectors = raw / np.clip(norms, 1e-9, None)

        all_roles = {r for d in docs for r in d.allowed_roles}
        for role in all_roles:
            self._role_mask[role] = np.array(
                [role in d.allowed_roles for d in docs], dtype=bool)

    def _visible_mask(self, principal: Principal) -> np.ndarray:
        """Which documents this principal may see. Computed from identity
        alone — never from the query, never from what was retrieved."""
        n = len(self._docs)
        mask = np.zeros(n, dtype=bool)
        for role in principal.roles:
            role_mask = self._role_mask.get(role)
            if role_mask is not None:
                mask |= role_mask
        if principal.granted_docs:
            for i, doc in enumerate(self._docs):
                if doc.doc_id in principal.granted_docs:
                    mask[i] = True
        return mask

    def search(self, query: str, principal: Principal, k: int = 5,
               min_score: float = 0.35) -> list[tuple[Document, float]]:
        """Filter FIRST, then rank the survivors.

        The tempting implementation is to search all documents, then remove the
        ones the user cannot see. That is wrong for two reasons:

        1. It leaks through result count. A user who gets 3 results back from a
           top-5 search learns that 2 matching documents exist which they
           cannot see. Repeated with varied queries, that maps the hidden
           corpus.

        2. It leaks through ranking displacement. If forbidden documents
           occupy the top slots, the permitted results the user DOES see are
           systematically worse than they should be, and comparing across users
           reveals where the hidden documents are.

        Filtering first means the user's search runs over exactly the corpus
        they are entitled to. Their top-5 is the true top-5 of their world.
        """
        if self._vectors is None:
            raise RuntimeError("index not built")

        visible = self._visible_mask(principal)
        if not visible.any():
            return []

        q = self._embed([query])[0]
        q = q / max(float(np.linalg.norm(q)), 1e-9)

        scores = self._vectors @ q
        # Exclude forbidden documents from consideration entirely by driving
        # their score below any possible threshold.
        scores = np.where(visible, scores, -np.inf)

        top = np.argpartition(-scores, min(k, len(scores) - 1))[:k]
        top = top[np.argsort(-scores[top])]

        return [
            (self._docs[i], float(scores[i]))
            for i in top
            if np.isfinite(scores[i]) and scores[i] >= min_score
        ]
