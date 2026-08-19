"""Per-request traces.

The test for this module: a customer says "on the 14th, ticket 8812 was
routed wrong." Can you explain what happened without reproducing it?

If the answer is no, the system is not operable, however good its eval score.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict


# Fields that must NEVER appear in a trace, at any sampling rate.
#
# A trace is retained for months, replicated to analytics, and read by people
# who have no business seeing customer content. Redaction is not a privacy
# nicety here — an unredacted trace turns your observability system into an
# uncontrolled copy of the data your access controls protect.
REDACT_ALWAYS = frozenset({
    "ticket_text", "customer_email", "customer_name", "account_number",
    "raw_completion", "retrieved_text",
})


def content_fingerprint(text: str) -> str:
    """A stable hash standing in for redacted content.

    This preserves the one thing debugging needs from the text — whether two
    requests had the SAME content — without retaining the content itself.
    Two traces with equal fingerprints came from identical input.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class StepTrace:
    index: int
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    tool_called: str | None = None
    tool_authorized: bool | None = None
    tool_error: str | None = None


@dataclass
class RequestTrace:
    trace_id: str
    tenant: str
    user_id: str
    ticket_id: str
    started_ms: int

    # Decisions, which are what you actually debug from.
    tier: str = ""
    retrieved_doc_ids: list[str] = field(default_factory=list)
    visible_doc_count: int = 0
    assigned_category: str | None = None
    assigned_priority: str | None = None
    cited_policies: list[str] = field(default_factory=list)

    steps: list[StepTrace] = field(default_factory=list)
    ticket_fingerprint: str = ""
    partial: bool = False
    refused: bool = False

    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0

    def finish(self, started: float) -> None:
        self.total_latency_ms = (time.perf_counter() - started) * 1000
        self.total_cost_usd = sum(s.cost_usd for s in self.steps)

    def to_record(self) -> dict:
        record = asdict(self)
        # Defense in depth: even if a caller attached a forbidden field, it is
        # stripped on the way out. The redaction must not depend on every call
        # site remembering.
        for key in REDACT_ALWAYS:
            record.pop(key, None)
        return record


@dataclass
class SamplingPolicy:
    """Sample the boring requests, keep all the interesting ones.

    Retaining every trace at volume is expensive; retaining a uniform random
    sample loses exactly the requests you will be asked about, because the
    interesting ones are rare by definition.
    """

    base_rate: float = 0.05

    def should_retain(self, trace: RequestTrace) -> bool:
        # Forced retention: anything unusual is kept regardless of the sample
        # rate. These are the requests a complaint will be about.
        if trace.partial or trace.refused:
            return True
        if trace.assigned_priority == "urgent":
            return True
        if any(s.tool_authorized is False for s in trace.steps):
            return True
        if any(s.tool_error for s in trace.steps):
            return True
        if trace.total_cost_usd > 0.05:
            return True
        if trace.total_latency_ms > 4000:
            return True

        # Deterministic sampling by trace id, so the decision is reproducible
        # and independent per request.
        bucket = int(trace.trace_id[:8], 16) % 10_000
        return bucket < self.base_rate * 10_000


def new_trace(tenant: str, user_id: str, ticket_id: str,
              ticket_text: str) -> RequestTrace:
    return RequestTrace(
        trace_id=uuid.uuid4().hex,
        tenant=tenant,
        user_id=user_id,
        ticket_id=ticket_id,
        started_ms=int(time.time() * 1000),
        ticket_fingerprint=content_fingerprint(ticket_text),
    )
