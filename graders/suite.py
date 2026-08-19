"""Graders, split by whether the check needs judgment.

Everything checkable by a rule is a rule: rules are free, deterministic, and
cannot drift. Model graders are for judgment — and a model grader is itself a
model, so it must be validated before its scores are trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

VALID_CATEGORIES = frozenset({
    "account_access", "billing", "outage", "feature_request", "other",
})
VALID_PRIORITIES = ("urgent", "high", "normal", "low")

# Citations look like [policy-id §section]. Enforced structurally so a citation
# can be resolved and checked rather than merely looking plausible.
CITATION = re.compile(r"\[([a-z0-9\-]+)\s*§\s*([0-9.]+)\]")


@dataclass
class GraderResult:
    passed: bool
    reason: str
    # Which grader produced this. Needed to attribute a score change to a
    # grader change rather than a system change.
    grader: str
    grader_version: str


class RuleGraders:
    """Deterministic checks. No model call, no cost, no variance."""

    VERSION = "rules-v3"

    def category_valid(self, category: str | None) -> GraderResult:
        ok = category in VALID_CATEGORIES
        return GraderResult(
            passed=ok,
            reason="valid category" if ok else f"unknown category {category!r}",
            grader="category_valid",
            grader_version=self.VERSION,
        )

    def citation_present_and_resolvable(
        self, answer: str, corpus_ids: frozenset[str]
    ) -> GraderResult:
        """A citation must parse AND resolve to a document that exists.

        Checking only that a citation-shaped string is present would pass a
        fabricated one, which is the exact failure the citation requirement is
        supposed to prevent.
        """
        matches = CITATION.findall(answer)
        if not matches:
            return GraderResult(False, "no citation present",
                                "citation_present", self.VERSION)
        unresolvable = [doc for doc, _sec in matches if doc not in corpus_ids]
        if unresolvable:
            return GraderResult(
                False,
                f"citation(s) do not resolve: {unresolvable}",
                "citation_present", self.VERSION,
            )
        return GraderResult(True, f"{len(matches)} citation(s) resolved",
                            "citation_present", self.VERSION)

    def no_document_leak(self, answer: str, forbidden_ids: frozenset[str]) -> GraderResult:
        """The answer must not reference any document the user cannot access.

        This is a rule, not a judgment, and it is the highest-severity check in
        the suite: an access violation is not a quality problem.
        """
        leaked = [doc for doc in forbidden_ids if doc in answer]
        return GraderResult(
            passed=not leaked,
            reason="no leak" if not leaked else f"LEAKED: {leaked}",
            grader="no_document_leak",
            grader_version=self.VERSION,
        )


class ModelGraders:
    """Judgment calls. Each one must be validated against human labels before
    its output is used in a gate."""

    VERSION = "judge-v2"

    def __init__(self, judge_fn) -> None:
        self._judge = judge_fn

    def priority_justified(self, ticket: str, priority: str,
                           cited_policy: str) -> GraderResult:
        prompt = (
            "A support ticket was assigned a priority, citing a policy.\n"
            "Judge ONLY whether the cited policy justifies that priority for "
            "this ticket. Do not judge whether the priority feels right.\n\n"
            f"Ticket: {ticket}\n\nAssigned priority: {priority}\n\n"
            f"Cited policy text: {cited_policy}\n\n"
            "Answer JUSTIFIED or NOT_JUSTIFIED, then one sentence of reasoning."
        )
        verdict = self._judge(prompt)
        passed = verdict.strip().upper().startswith("JUSTIFIED")
        return GraderResult(passed, verdict[:200], "priority_justified",
                            self.VERSION)
