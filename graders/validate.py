"""Measure whether a model grader agrees with human judgment.

An unvalidated model grader means your eval score is a claim about a model
whose accuracy you never measured.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgreementReport:
    grader: str
    grader_version: str
    n: int
    agree: int
    false_pass: int   # grader passed, human failed. The dangerous direction.
    false_fail: int   # grader failed, human passed.

    @property
    def rate(self) -> float:
        return self.agree / self.n if self.n else 0.0

    @property
    def false_pass_rate(self) -> float:
        return self.false_pass / self.n if self.n else 0.0

    def usable(self) -> tuple[bool, str]:
        """Two independent bars, not one combined score.

        Overall agreement can look fine while false passes are concentrated in
        exactly the cases that matter. Both must clear.
        """
        if self.n < 40:
            return False, f"only {self.n} labels; need >= 40 to measure agreement"
        if self.rate < 0.90:
            return False, f"agreement {self.rate:.2f} below 0.90"
        if self.false_pass_rate > 0.03:
            return False, (f"false pass rate {self.false_pass_rate:.2f} above "
                           f"0.03; this grader rubber-stamps bad answers")
        return True, f"agreement {self.rate:.2f}, false pass {self.false_pass_rate:.2f}"


def validate(grader_fn, labeled: list[tuple[dict, bool]],
             grader_name: str, version: str) -> AgreementReport:
    """labeled: list of (grader_inputs, human_verdict).

    The human labels must include BORDERLINE cases. A label set of obvious
    passes and obvious fails measures nothing — any grader gets those right,
    and the disagreements all live in the middle.
    """
    agree = false_pass = false_fail = 0
    for inputs, human in labeled:
        result = grader_fn(**inputs)
        if result.passed == human:
            agree += 1
        elif result.passed and not human:
            false_pass += 1
        else:
            false_fail += 1

    return AgreementReport(
        grader=grader_name,
        grader_version=version,
        n=len(labeled),
        agree=agree,
        false_pass=false_pass,
        false_fail=false_fail,
    )
