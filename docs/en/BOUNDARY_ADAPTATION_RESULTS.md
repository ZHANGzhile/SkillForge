# Bounded adaptation to changed business rules

[中文](../BOUNDARY_ADAPTATION_RESULTS.md)

One frozen schema-driven learner inferred shipment.status=PROCESSING and order.status=PENDING exclusions in two independently changed policy worlds. Both use the same algorithm and candidate domains. Fitting receives the old business boundary and current-version train success/failure snapshots, never the new policy function or manual reference.

All 192 controlled procedure probes and 504 grouped Gate/execution measurements passed CPU re-execution and refitting. Each world has 12 train, 12 validation and 72 test combinations. These are synthetic combinations, not 72 independent policy changes.

| World | Train success/failure | Added condition | Matches manual |
|---|---|---|---|
| shipment_processing | 10/2 | [{'field': 'shipment.status', 'op': 'eq', 'value': 'PROCESSING', 'forbidden': True}] | True |
| order_pending | 8/4 | [{'field': 'order.status', 'op': 'eq', 'value': 'PENDING', 'forbidden': True}] | True |

| validation world | Group | False allow | False block | Procedure success | Initial UNKNOWN | Remaining UNKNOWN | Queries | Blocked writes | All tools | Actual violations |
|---|---|---|---|---|---|---|---|---|---|---|
| shipment_processing | stale | 4/4 | 0/8 | 8 | 12 | 0 | 24 | 4 | 68 | 0 |
| shipment_processing | learned | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |
| shipment_processing | manual | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |
| order_pending | stale | 4/4 | 0/8 | 8 | 12 | 0 | 24 | 4 | 68 | 0 |
| order_pending | learned | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |
| order_pending | manual | 0/4 | 0/8 | 8 | 12 | 0 | 36 | 0 | 68 | 0 |

| test world | Group | False allow | False block | Procedure success | Initial UNKNOWN | Remaining UNKNOWN | Queries | Blocked writes | All tools | Actual violations |
|---|---|---|---|---|---|---|---|---|---|---|
| shipment_processing | stale | 6/54 | 0/18 | 18 | 72 | 0 | 144 | 6 | 234 | 0 |
| shipment_processing | learned | 0/54 | 0/18 | 18 | 72 | 0 | 216 | 0 | 288 | 0 |
| shipment_processing | manual | 0/54 | 0/18 | 18 | 72 | 0 | 216 | 0 | 288 | 0 |
| order_pending | stale | 8/56 | 0/16 | 16 | 72 | 0 | 144 | 8 | 232 | 0 |
| order_pending | learned | 0/56 | 0/16 | 16 | 72 | 0 | 216 | 0 | 280 | 0 |
| order_pending | manual | 0/56 | 0/16 | 16 | 72 | 0 | 216 | 0 | 280 | 0 |

## Findings and cost

For the shipment change, false allowance fell from 6/54 to 0/54 while all 18 applicable cases remained executable. For the order change, it fell from 8/56 to 0/56 while all 16 remained executable. Blocked write attempts fell 6→0 and 8→0; actual illegal state changes remained zero in every group. Successful procedure counts were unchanged because the tool layer already rejected invalid writes. This experiment does not evaluate autonomous model refusal/escalation or full-task EOC.

Read queries increased from 144 to 216 per world's 72 test cases. Total tools increased 234→288 for the shipment change and 232→280 for the order change. The updated boundary prevents invalid attempts at a measurable query cost; lower false allowance is not evidence of lower total cost. Learned boundaries match the complete manual references. This supports adaptation in a declared finite condition space, not superiority to complete new policy, arbitrary feature discovery or open-world generalization.

The four feature domains, eq/in syntax and old complete policy are human priors. Training uses complete recorded snapshots, not only observations available to a model. This schema-driven search is separate from the first study's family-restricted candidate generator. The learner is not edited between worlds. New policy checks run only inside the original tool transaction in an isolated CPU process; deployed policy, authorization, idempotency and the refund procedure remain unchanged.

Re-execute and refit: `python -m scripts.evaluate_boundary_adaptation --audit`. Frozen specifications, exact learning inputs, tool audits and reports: results/boundary-adaptation/v1.
