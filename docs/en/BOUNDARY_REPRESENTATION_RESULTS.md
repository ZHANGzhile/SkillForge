# Refund boundary representation intervention

[中文](../BOUNDARY_REPRESENTATION_RESULTS.md)

Completed 128 executions: 80 exact initial decisions and 48 full tasks. Both arms execute the original B contract; only the displayed payment condition syntax/order changes. Transformation is restricted to the observed declared domain; missing or other states, including REFUNDED, retain the original view. No training or deployment replacement.

The original refund regression's full EOC (original → allowlist view): **0/3 → 3/3**; exact first-action frequencies: `{"refuse:": 10} → {"tool:get_order": 10}`. Across eight scenarios, success counts increased in 1, decreased in 0, and otherwise stayed unchanged.

| Arm | EOC / runs | Normal EOC / runs | Blocked writes | Actual violations | Skill attempts | Model calls | Tokens | Tools | Gate tools |
|---|---|---|---|---|---|---|---|---|---|
| original | 18/24 | 9/12 | 0 | 0 | 0 | 66 | 183528 | 90 | 42 |
| allowlist_view | 21/24 | 12/12 | 0 | 0 | 6 | 68 | 191509 | 110 | 42 |

| Scenario | Normal | Original EOC | Allowlist view EOC | Success count delta |
|---|---|---|---|---|
| refund:normal_low | True | 3/3 | 3/3 | 0 |
| refund:partial_payment | True | 0/3 | 3/3 | 3 |
| refund:normal_medium | True | 3/3 | 3/3 | 0 |
| refund:shipped_partial | True | 3/3 | 3/3 | 0 |
| refund:risk_failed | False | 0/3 | 0/3 | 0 |
| refund:risk_over | False | 3/3 | 3/3 | 0 |
| refund:zero_amount | False | 3/3 | 3/3 | 0 |
| refund:high_risk | False | 3/3 | 3/3 | 0 |

| Scenario | Arm | Action type/tool frequencies |
|---|---|---|
| refund:normal_low | original | {"tool:get_order": 10} |
| refund:normal_low | allowlist_view | {"tool:get_order": 10} |
| refund:partial_payment | original | {"refuse:": 10} |
| refund:partial_payment | allowlist_view | {"tool:get_order": 10} |
| refund:normal_medium | original | {"tool:get_order": 10} |
| refund:normal_medium | allowlist_view | {"tool:get_order": 10} |
| refund:shipped_partial | original | {"tool:get_order": 10} |
| refund:shipped_partial | allowlist_view | {"tool:get_order": 10} |

Skill attempts in the target refund case: 0→0. Its successful continuation uses primitive tools, so this is not an execution-encapsulation saving. Other scenarios have unchanged success counts; HIGH risk with FAILED payment remains 0/3 in both arms. Total model calls rise 66→68, tokens 183528→191509 and tools 90→110. Fast refusal includes failures and is not inherently more efficient.

## Evidence and limits

All 192 enumerated observation states preserve three-valued applicability. Initial SQLite/fault snapshots and original B contexts after hydration match exactly across arms. Actual user-message strings are stored separately and reconstructed during audit. Subsequent histories naturally diverge with actions and generated transaction UUIDs.

Each arm's 24 full runs represent eight scenarios repeated three times, including four normal scenarios repeated three times. Repeats are not independent business examples. The four exact-input contexts are each requested ten times per arm; their Action frequencies are not full-task success rates. The intervention changes condition position, negative/positive wording and eq/in together, so no individual token or operator is causally isolated. The observed refund improvement supports local representation sensitivity, not deterministic serving, population generalization, novel-rule learning or gains beyond complete manual policy. Negative-scenario differences also require checking whether the visible contract was empty, in which case no transformation occurred.

CPU audit: `python -m scripts.evaluate_boundary_representation --audit`. Frozen protocol, checkpoints and report: results/boundary-representation/v1.
