# Refund outcome precedence repair

[中文](../REFUND_PRIORITY_RESULTS.md)

Completed and audited 92 real-model execution records. Research diagnostic admission: rejected; subsequent diagnostics stopped as declared. Both control and priority retain the bounded allowlist display repair and execute the same B contract. The only additional intervention is a fixed refund-policy clarification: HIGH risk takes precedence over payment/amount refusal.

| Stage | Arm | System EOC | Normal EOC | Fixed decision | Model attempts | Actual violations | Blocked writes | Skill attempts | System LLM calls | System tokens | System tools | Gate tools | Decision tokens | Decision setup read equivalents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| validation | control | 22/23 | 8/8 | 15/23 | 0 | 0 | 0 | 2 | 63 | 178533 | 120 | 67 | 63209 | 77 |
| validation | priority | 21/23 | 8/8 | 14/23 | 0 | 0 | 0 | 2 | 76 | 226019 | 134 | 67 | 63923 | 77 |

| validation scenario | Control EOC | Priority EOC | Control decision | Priority decision | Priority outcomes |
|---|---|---|---|---|---|
| modify_address:pending | 0/1 | 0/1 | 0/1 | 0/1 | {'max_steps_exceeded': 1} |
| refund:normal_medium | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| refund:zero_amount | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| modify_address:normal_low | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| modify_address:processing | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| modify_address:shipped | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| modify_address:high_risk | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| refund:normal_low | 1/1 | 1/1 | 1/1 | 0/1 | {'completed': 1} |
| refund:over_remaining | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| refund:failed_payment | 1/1 | 0/1 | 1/1 | 1/1 | {'escalated': 1} |
| modify_address:normal_medium | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| cancel_order:high_risk | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| refund:exact_remaining | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| refund:partial_payment | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| modify_address:invalid_address | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| modify_address:delivered | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| cancel_order:processing | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| cancel_order:normal_low | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| cancel_order:shipped | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| cancel_order:delivered | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| cancel_order:normal_medium | 1/1 | 1/1 | 1/1 | 1/1 | {'completed': 1} |
| refund:high_risk | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| cancel_order:pending | 1/1 | 1/1 | 0/1 | 0/1 | {'escalated': 1} |

| Stage | Metric | Independent scenarios | Paired delta | 95% scenario bootstrap | Improved | Regressed |
|---|---|---|---|---|---|---|
| validation | success | 23 | -0.043478 | [-0.130435, 0.0] | 0 | 1 |
| validation | correct | 23 | -0.043478 | [-0.130435, 0.0] | 0 | 1 |

## Interpretation

Full-system evaluation verifies terminal EOC, tickets and state chains. Fixed-candidate probes check Skill/refuse/escalate choices after identical authorized reads. They measure constrained selection, with separate denominators and costs. Decision setup read equivalents allocate the frozen authorized-read audit to each probe; HTTP replay does not re-execute tools. These are per-input setup equivalents, not actual inference-time tool calls, and are not added to System tools. HIGH+FAILED requires escalation under the existing tool policy; Skill inapplicability alone does not select the terminal outcome.

The validation gate requires no aggregate regression in EOC, normal completion or fixed-candidate correctness, zero actual violations and no increase in model violation attempts. All scenario gains, regressions and intervals are retained in report.json. Bootstrap resamples business scenarios, not individual repeats. The eight previously seen refund scenarios provide diagnostic evidence, not a fresh generalization test. Both arms make new requests to the same pinned service; historical scores are not reused. Previously observed action variability under identical recorded settings remains a separate limitation.

This is a manually authored business-policy expression repair, not an independent boundary-learning gain. Gate, tool policy and model weights remain unchanged. It does not replace the main project's 69-case validation and 78-case test product admission. Deployment remains the original main-v3 SFT.

Audit: `python -m scripts.evaluate_refund_priority --audit`. Original contexts, actual user messages, raw fixed-candidate HTTP responses, fingerprints, tool audits, selection and freeze manifests are in results/refund-priority/v1.
