"""Cost and latency budgets, enforced before the call rather than observed after.

A dashboard tells you that you overspent. A gate prevents it. The difference
matters because the failure mode of an AI system under load is not an error —
it is an invoice.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class Tier(enum.Enum):
    """The degradation ladder.

    When the budget tightens we do not fail — we do less. Each rung is a
    deliberate quality reduction with a known cost saving, chosen in advance
    rather than improvised during an incident.
    """

    FULL = "full"              # best model, full retrieval, agent loop enabled
    REDUCED = "reduced"        # smaller model, full retrieval, single pass
    MINIMAL = "minimal"        # smallest model, top-3 retrieval, no agent loop
    REFUSE = "refuse"          # decline and queue for human triage


@dataclass
class TierConfig:
    model: str
    retrieval_k: int
    agent_steps: int
    est_cost_usd: float


LADDER = {
    Tier.FULL: TierConfig("frontier", retrieval_k=8, agent_steps=4,
                          est_cost_usd=0.018),
    Tier.REDUCED: TierConfig("mid", retrieval_k=8, agent_steps=1,
                             est_cost_usd=0.006),
    Tier.MINIMAL: TierConfig("small", retrieval_k=3, agent_steps=1,
                             est_cost_usd=0.001),
}


@dataclass
class BudgetWindow:
    """A rolling window of spend for one tenant."""

    tenant: str
    limit_usd_per_hour: float
    # (timestamp, cost) pairs. Trimmed to the window on every check.
    spend: list[tuple[float, float]] = field(default_factory=list)

    def record(self, cost_usd: float, now: float | None = None) -> None:
        self.spend.append((now if now is not None else time.time(), cost_usd))

    def spent_in_window(self, now: float | None = None,
                        window_s: float = 3600.0) -> float:
        now = now if now is not None else time.time()
        cutoff = now - window_s
        self.spend = [(t, c) for t, c in self.spend if t >= cutoff]
        return sum(c for _t, c in self.spend)

    def headroom(self, now: float | None = None) -> float:
        return max(0.0, self.limit_usd_per_hour - self.spent_in_window(now))


class BudgetGate:
    def __init__(self, windows: dict[str, BudgetWindow]) -> None:
        self._windows = windows

    def select_tier(self, tenant: str, now: float | None = None) -> Tier:
        """Choose the richest tier the remaining budget affords.

        Selection is per REQUEST, using CURRENT headroom. A tier chosen at
        startup and held would spend the whole budget in the first ten minutes
        of a traffic spike and then have nothing left for the rest of the hour.
        """
        window = self._windows.get(tenant)
        if window is None:
            return Tier.MINIMAL  # unknown tenant gets the cheapest path

        headroom = window.headroom(now)
        # Reserve: never spend the last 10% on full-tier requests, so a burst
        # cannot consume the entire budget and leave nothing for the requests
        # that follow.
        usable = headroom - window.limit_usd_per_hour * 0.10

        for tier in (Tier.FULL, Tier.REDUCED, Tier.MINIMAL):
            if usable >= LADDER[tier].est_cost_usd:
                return tier
        # Below the cheapest tier's cost: refuse rather than proceed and
        # overspend. Refusal is a queued human triage, not a dropped ticket.
        return Tier.REFUSE


@dataclass
class LatencyGate:
    """Latency budget, enforced by deadline rather than by timeout.

    A per-call timeout does not bound total latency: an agent making four tool
    calls each with a 3s timeout can take 12s. A deadline set once at the start
    and checked before each step bounds the whole request.
    """

    budget_s: float

    def deadline(self, started_at: float) -> float:
        return started_at + self.budget_s

    def remaining(self, started_at: float, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        return self.deadline(started_at) - now

    def may_continue(self, started_at: float, next_step_est_s: float,
                     now: float | None = None) -> bool:
        """Check BEFORE the step, using its estimated duration.

        Checking after the step means discovering you exceeded the budget once
        you already have. The estimate does not need to be precise — it needs
        to prevent starting work that obviously cannot finish in time.
        """
        return self.remaining(started_at, now) > next_step_est_s
