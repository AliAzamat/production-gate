"""Success criteria, defined before the system exists.

Written first for the same reason the eval set is: criteria authored after
seeing what the system does will describe what the system does.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class Measurable(enum.Enum):
    """How a criterion is checked. A criterion that cannot be checked by one of
    these is not a criterion, it is an aspiration."""

    EVAL_SCORE = "eval_score"          # measured by the grader suite
    PRODUCTION_SIGNAL = "prod_signal"  # measured from live telemetry
    HUMAN_REVIEW = "human_review"      # sampled and judged by a person


@dataclass(frozen=True)
class Criterion:
    name: str
    statement: str
    measured_by: Measurable
    # The threshold, and crucially the DIRECTION. "latency under 4s" and
    # "accuracy above 0.85" are both thresholds and they are not interchangeable.
    threshold: float
    higher_is_better: bool
    # What this is compared against. A number with no baseline is not a
    # criterion — 85% accuracy is excellent or unacceptable depending entirely
    # on what the humans doing this task today achieve.
    baseline: float
    baseline_source: str

    def passes(self, observed: float) -> bool:
        return (observed >= self.threshold if self.higher_is_better
                else observed <= self.threshold)

    def beats_baseline(self, observed: float) -> bool:
        return (observed > self.baseline if self.higher_is_better
                else observed < self.baseline)


# The workflow: triage inbound support tickets into a category and priority,
# with a citation to the policy that justifies the priority.
#
# ONE workflow, deliberately. A system that does three things adequately is
# harder to evaluate, harder to secure, and harder to get approved than one that
# does a single thing provably well.
CRITERIA = (
    Criterion(
        name="categorization_accuracy",
        statement="Correct category on held-out tickets",
        measured_by=Measurable.EVAL_SCORE,
        threshold=0.90,
        higher_is_better=True,
        baseline=0.87,
        baseline_source="measured: 200 tickets triaged by two support agents, "
                        "agreement with the final resolved category",
    ),
    Criterion(
        name="priority_citation_rate",
        statement="Priority assignments carrying a valid policy citation",
        measured_by=Measurable.EVAL_SCORE,
        threshold=0.98,
        higher_is_better=True,
        baseline=0.0,
        baseline_source="humans do not cite policy today; this is new capability",
    ),
    Criterion(
        name="p95_latency_s",
        statement="95th percentile end-to-end triage latency",
        measured_by=Measurable.PRODUCTION_SIGNAL,
        threshold=4.0,
        higher_is_better=False,
        baseline=210.0,
        baseline_source="measured: median human triage time, ticket open to "
                        "category assigned",
    ),
    Criterion(
        name="cost_per_ticket_usd",
        statement="Fully loaded model cost per triaged ticket",
        measured_by=Measurable.PRODUCTION_SIGNAL,
        threshold=0.02,
        higher_is_better=False,
        baseline=1.75,
        baseline_source="measured: agent time at loaded rate x median triage time",
    ),
    Criterion(
        name="escalation_precision",
        statement="Tickets escalated to urgent that were genuinely urgent",
        measured_by=Measurable.HUMAN_REVIEW,
        threshold=0.95,
        higher_is_better=True,
        baseline=0.91,
        baseline_source="measured: 3 months of human escalations reviewed "
                        "against outcome",
    ),
)


# Failure is defined explicitly, not left as "not success".
#
# Without this, every borderline outcome becomes a negotiation at review time,
# and the negotiation is won by whoever wants the project to ship.
UNACCEPTABLE = (
    "Any ticket routed to a user who lacks access to the documents cited.",
    "Any escalation to urgent with no policy citation.",
    "Categorization accuracy below the human baseline of 0.87 on ANY "
    "ticket category, even if the overall average passes.",
    "A cost per ticket above 0.02 sustained over any 1-hour window.",
)
