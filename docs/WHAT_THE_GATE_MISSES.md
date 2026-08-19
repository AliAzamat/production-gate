# What this gate does not catch

A gate that is trusted beyond its actual coverage is worse than no gate,
because it converts "we did not check" into "it passed".

## Not covered

1. **Novel attack classes.** The adversarial eval cases are the attacks we
   thought of. A genuinely new injection technique passes every check here.
   Mitigation: the adversarial set is reviewed and extended monthly, and
   production refusals are sampled for attacks we did not anticipate.

2. **Distribution shift.** The eval set is fixed. If the ticket population
   changes — a new product line, a different customer segment — the eval keeps
   measuring the old distribution and keeps passing.
   Mitigation: production accuracy is sampled weekly against human labels; a
   divergence between eval score and sampled production accuracy is the signal.

3. **Slow quality drift from a model update.** A provider-side model change can
   degrade behavior without any change in our code, so no deploy gate runs.
   Mitigation: the eval runs nightly on the unchanged system, not only on
   deploy.

4. **Cost regressions from prompt growth.** A prompt that grows gradually stays
   within budget per request while raising cost per ticket. The budget gate
   catches the limit, not the trend.
   Mitigation: cost per ticket is tracked as a criterion with a threshold, and
   the note line in every gate run surfaces it.

5. **Correctness of the graders themselves over time.** Grader validation is
   point-in-time. A model grader's behavior can drift with the underlying
   model.
   Mitigation: grader re-validation against the human label set is required
   whenever the grader version or its underlying model changes, and the gate
   blocks on version mismatch.

## The honest summary

This gate blocks known regressions on a fixed eval set with validated graders.
It does not certify the system is safe. It certifies that the specific things
we know to check still hold.
