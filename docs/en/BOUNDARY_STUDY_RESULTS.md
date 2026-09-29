# Fixed-program boundary learning study

[中文](../BOUNDARY_STUDY_RESULTS.md) | [English README](../../README.md)

This study separates boundary selection from program encapsulation. Existing core code, model weights, tool policy and the three frozen procedures are unchanged. Experimental contracts remain VALIDATING and are not deployed.

## Original compiler audit

| Family | Negative sources | Leave-one-out admitted | Changed conditions | All negatives removed |
|---|---|---|---|---|
| modify_address | 5 | 5 | 0 | rejected |
| cancel_order | 1 | 0 | 0 | rejected |
| refund | 1 | 0 | 0 | rejected |

Where compilation remained admitted after removing one failure, predicate fields/operators/values did not change. Failures supplied provenance and admission evidence to prewritten conditions; this is not evidence of discovering new rules.

## New bounded learner and data

A retains constant declared features from successful train executions. B adds positive-preserving finite predicates that reject train failures. C uses complete declared policy. D applies the same refinement on top of C. B learned HIGH-risk exclusions for all three families and a FAILED-payment exclusion for refunds. D added no conditions. The full public C and D contracts are identical.

There are 23 train, 23 validation and 24 test tasks; nine test condition combinations are held out from this experiment's train/validation. Some business combinations were already discussed in earlier project experiments: this is not novel-policy or wholly unseen semantic generalization. Train evidence contains 8 successful controlled executions, 14 business-rejected executions and 1 excluded internal-binding failure (zero refund amount); none are presented as autonomous model trajectories.

Feature domains, family-field selection and derived validity predicates are human priors. Training uses complete recorded train snapshots, not just a model's partial observations; test labels never enter fitting. The learner selects bounded categorical conditions; it does not discover arithmetic or arbitrary predicates. A uses no negative validation labels; its constant-feature restrictions cannot be removed by this monotone refinement. All four groups remain in evaluation.

## Pure Gate test

| Group | False allow / 16 | False block / 8 | Normal coverage | Initial UNKNOWN / 96 | Remaining UNKNOWN | Queries / 96 |
|---|---|---|---|---|---|---|
| A | 25.00% | 0.00% | 100.00% | 42 | 0 | 66 |
| B | 0.00% | 0.00% | 100.00% | 44 | 0 | 91 |
| C | 0.00% | 0.00% | 100.00% | 44 | 0 | 91 |
| D | 0.00% | 0.00% | 100.00% | 44 | 0 | 91 |

Full-observation denominators are 16 inapplicable and 8 applicable contexts. Costs/UNKNOWN span all 96 mask-context pairs. B-A false-allow difference is -25 percentage points, paired scenario-cluster percentile bootstrap 95% interval [-50, -6.25] points; false-block difference is zero. D-C is zero. A reports fewer UNKNOWNs partly because it lacks conditions, not because it knows more.

The 2,000-resample intervals describe the selected synthetic scenario clusters, not a population guarantee. An all-zero sample yields a degenerate bootstrap interval; it does not prove zero future risk. Rule oracle labels were cross-checked against actual fixed-procedure execution. C matching this known-policy oracle is expected.

## Real-model systems and candidate-point counterfactuals

216 actual runs / 288 logical runs. Identical C/D public contracts reuse exactly audited trajectories through explicit aliases; these are not independent repeated runs.

| Group | EOC / 24 | Normal EOC | Blocked writes | Model calls | Tokens | Tools | Budget exhausted |
|---|---|---|---|---|---|---|---|
| A | 19 | 8/8 | 5 | 73 | 198811 | 106 | 0 |
| B | 20 | 7/8 | 0 | 63 | 172968 | 118 | 0 |
| C | 21 | 8/8 | 0 | 62 | 171197 | 123 | 0 |
| D | 21 | 8/8 | 0 | 62 | 171197 | 123 | 0 |

| Group | Gate EOC | Bypass EOC | Improved | Regressed | Forced rejections avoided | Gate tools | Bypass tools |
|---|---|---|---|---|---|---|---|
| A | 19 | 20 | 0 | 1 | 11 | 123 | 101 |
| B | 23 | 20 | 3 | 0 | 15 | 120 | 106 |
| C | 24 | 20 | 4 | 0 | 15 | 120 | 106 |
| D | 24 | 20 | 4 | 0 | 15 | 120 | 106 |

Each counterfactual starts before Gate queries with the same database, empty visible observations, fault queues and fixed program. Both arms force the same initial Skill attempt; only that attempt bypasses the Gate in the control. Later decisions use the pinned real model and the same group's boundaries. The Gate never chooses refusal/escalation. Forced attempts are separated from autonomous model intent; all query costs are included.

The paired event breakdown and intervals are in results/boundary-study/v1/report.json. A better Gate score need not improve autonomous outcomes because the model already sees business policy and may avoid selecting the invalid Skill. D=C does not support learning beyond complete policy. No new-rule adaptation or deployment upgrade was performed.

## Admission constraint and observed serving variability

B-A did not meet the preregistered combined claim: autonomous normal-task EOC fell from 8/8 to 7/8 (difference -12.5 points; interval [-37.5, 0]). In the regressed partial-refund case, B's Gate offered the Skill, but the model immediately refused. This is not a Gate false block. A's five blocked autonomous writes were primitive tool actions, not executed Skills, so their reduction cannot be described as five autonomous wrong-Skill reuses prevented.

A post-hoc exact-input audit found 2 divergent-action clusters among 79 repeated serialized input clusters, excluding C/D aliases. Greedy settings did not imply observed bitwise repeatability. For example, B/C Gate branches on the same high-risk/failed-payment refund context produced different next actions despite identical serialized input and pinned settings. The cause is not established. We retain all records without rerunning to choose answers. Scenario-bootstrap intervals do not include repeated-serving variance; autonomous and continuation EOC differences should be treated as single-run descriptive evidence. C/D reuse expresses contract equivalence, not an empirical stability test.

Portable CPU verification: `python -m scripts.audit_boundary_study`. Report regeneration: `python -m scripts.report_boundary_study`.
