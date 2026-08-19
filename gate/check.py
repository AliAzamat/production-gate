"""The deploy gate.

Everything built so far produces numbers. This is where numbers become a
control: a change that regresses quality or violates a boundary does not ship.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from criteria.definition import CRITERIA, UNACCEPTABLE


@dataclass
class GateResult:
    blocked: bool
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = "BLOCKED" if self.blocked else "PASS"
        lines = [f"[{head}]"]
        for reason in self.blocking_reasons:
            lines.append(f"  BLOCK   {reason}")
        for warning in self.warnings:
            lines.append(f"  warn    {warning}")
        for note in self.notes:
            lines.append(f"  note    {note}")
        return "\n".join(lines)


# Aggregate tolerance absorbs run-to-run noise from model graders. Security
# checks get NO tolerance: they are categorical, and "slightly fewer access
# violations" is not a meaningful state.
AGGREGATE_TOLERANCE = 0.015
SECURITY_GRADERS = frozenset({"no_document_leak"})


def check(baseline: dict, candidate: dict) -> GateResult:
    result = GateResult(blocked=False)

    # 1. Security checks: any failure blocks, regardless of everything else.
    for grader in SECURITY_GRADERS:
        failures = candidate["grader_failures"].get(grader, 0)
        if failures > 0:
            result.blocked = True
            result.blocking_reasons.append(
                f"SECURITY: {grader} failed on {failures} case(s). "
                f"No tolerance applies."
            )

    # 2. Explicit unacceptable conditions.
    for condition, violated in zip(UNACCEPTABLE,
                                   candidate.get("unacceptable_violations", [])):
        if violated:
            result.blocked = True
            result.blocking_reasons.append(f"UNACCEPTABLE: {condition}")

    # 3. Per-criterion thresholds, checked in the criterion's own direction.
    for criterion in CRITERIA:
        observed = candidate["criteria"].get(criterion.name)
        if observed is None:
            result.blocked = True
            result.blocking_reasons.append(
                f"criterion '{criterion.name}' not measured in this run")
            continue
        if not criterion.passes(observed):
            result.blocked = True
            result.blocking_reasons.append(
                f"{criterion.name}: {observed} fails threshold "
                f"{criterion.threshold}")
        elif not criterion.beats_baseline(observed):
            # Passing the threshold while not beating the human baseline is a
            # warning, not a block — the threshold was set deliberately and may
            # sit below baseline for a reason. But it must be visible.
            result.warnings.append(
                f"{criterion.name}: {observed} passes threshold but does not "
                f"beat baseline {criterion.baseline} ({criterion.baseline_source})")

    # 4. Aggregate regression against the committed baseline.
    delta = candidate["eval_score"] - baseline["eval_score"]
    if delta < -AGGREGATE_TOLERANCE:
        result.blocked = True
        result.blocking_reasons.append(
            f"eval score dropped {-delta:.3f} "
            f"({baseline['eval_score']:.3f} -> {candidate['eval_score']:.3f})")

    # 5. Grader version drift makes the comparison invalid.
    if baseline.get("grader_versions") != candidate.get("grader_versions"):
        result.blocked = True
        result.blocking_reasons.append(
            "grader versions differ between baseline and candidate; "
            "the comparison is not valid. Re-run the baseline with the "
            "current graders as a separate reviewed change.")

    # 6. Business connection. Not a gate — a required note, so the eval score
    # is never reported without the outcome it is supposed to predict.
    result.notes.append(
        f"eval {candidate['eval_score']:.3f} | "
        f"tickets auto-triaged {candidate.get('auto_triage_rate', 0):.1%} | "
        f"human corrections {candidate.get('correction_rate', 0):.1%} | "
        f"cost/ticket ${candidate.get('cost_per_ticket', 0):.4f}")

    return result
