# HIGH-observation-scoped refund priority, v2

[中文](../REFUND_PRIORITY_SCOPED_RESULTS.md)

Completed and audited 128 real-model records; refund research admission passed. HIGH+FAILED target: full EOC 0/3→3/3; fixed decision 0/3→3/3. Target full-system calls 3→3, tokens 6999→7293, tools 6→9, Gate queries 6→6. 

The v1 clarification was appended to every refund input and was rejected: validation EOC 22/23→21/23 and fixed decisions 15/23→14/23. V2 is a new candidate designed after that failure. It adds the same text only when authorized observations already contain HIGH risk and the family is refund. Both arms retain the allowlist view and execute unchanged B.

| Stage | Arm | System EOC | Normal EOC | Fixed decision | Model attempts | Actual violations | Blocked writes | Skill attempts | System LLM calls | System tokens | System tools | Gate tools | Decision tokens | Decision setup read equivalents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| validation | control | 8/8 | 4/4 | 5/8 | 0 | 0 | 0 | 2 | 23 | 64442 | 36 | 14 | 21963 | 24 |
| validation | priority | 8/8 | 4/4 | 5/8 | 0 | 0 | 0 | 2 | 23 | 64537 | 36 | 14 | 22056 | 24 |

| Stage | Arm | System EOC | Normal EOC | Fixed decision | Model attempts | Actual violations | Blocked writes | Skill attempts | System LLM calls | System tokens | System tools | Gate tools | Decision tokens | Decision setup read equivalents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| diagnostic | control | 21/24 | 12/12 | 12/24 | 0 | 0 | 0 | 6 | 68 | 191493 | 110 | 42 | 66009 | 72 |
| diagnostic | priority | 24/24 | 12/12 | 15/24 | 0 | 0 | 0 | 6 | 66 | 186706 | 111 | 42 | 66861 | 72 |

| diagnostic scenario | Control EOC | Priority EOC | Control decision | Priority decision | Priority outcomes |
|---|---|---|---|---|---|
| refund:normal_low | 3/3 | 3/3 | 3/3 | 3/3 | {'completed': 3} |
| refund:partial_payment | 3/3 | 3/3 | 0/3 | 0/3 | {'completed': 3} |
| refund:normal_medium | 3/3 | 3/3 | 0/3 | 0/3 | {'completed': 3} |
| refund:shipped_partial | 3/3 | 3/3 | 0/3 | 0/3 | {'completed': 3} |
| refund:risk_failed | 0/3 | 3/3 | 0/3 | 3/3 | {'escalated': 3} |
| refund:risk_over | 3/3 | 3/3 | 3/3 | 3/3 | {'escalated': 3} |
| refund:zero_amount | 3/3 | 3/3 | 3/3 | 3/3 | {'refused': 3} |
| refund:high_risk | 3/3 | 3/3 | 3/3 | 3/3 | {'escalated': 3} |

| Stage | Metric | Independent scenarios | Paired delta | 95% scenario bootstrap | Improved | Regressed |
|---|---|---|---|---|---|---|
| validation | success | 8 | 0.0 | [0.0, 0.0] | 0 | 0 |
| validation | correct | 8 | 0.0 | [0.0, 0.0] | 0 | 0 |
| diagnostic | success | 8 | 0.125 | [0.0, 0.375] | 1 | 0 |
| diagnostic | correct | 8 | 0.125 | [0.0, 0.375] | 1 | 0 |

## Scope and attribution

V2 validates all eight refund validation scenarios, yielding 32 records across two arms and evaluation levels. This denominator differs from v1's 23 scenarios; their aggregate scores are not directly comparable. Both arms make new requests. Of 175 enumerated combinations, only five activate the clarification; of 185 original v1 contexts, 181 remain byte-identical and four activate it. Other task families have no new model regression scores; input identity proves only that the display intervention does not touch them.

Full tasks are checked against EOC and state chains. Fixed candidates measure constrained Skill/refuse/escalate selection. Setup read equivalents allocate the frozen authorized-read audit per input; HTTP replay does not execute these tools. They are not added to actual system tool calls. Normal completion, decisions, violation attempts, costs and every scenario regression are retained. Bootstrap resamples eight business scenarios, not 24 independent repetitions; an interval including zero cannot support a reliable population improvement.

Total model calls fell 68→66 and tokens 191493→186706, but both fewer calls came from zero_amount (11→9), where the clarification never activates. This does not establish prompt-induced efficiency. The HIGH+FAILED target itself used 3→3 calls, tokens6999→7293 and tools6→9: three additional, required escalation writes. All three HIGH scenarios incur additional prompt tokens. Total system tools were110→111 and Gate queries42 in both arms. Execution-length variation in an unchanged-input scenario preserves the earlier repeatability limitation.

This is a conditional display repair of manually known policy, not a learned new rule. Gate and model Actions are unchanged; the real model still selects escalation. Previously seen test cases provide diagnostics, not independent generalization evidence. Main-v3 deployment, its ten held-out failures and the PENDING-address read loop are not replaced or resolved by this experiment. It does not substitute for the main 69-case validation and 78-case test product gate.

Audit: `python -m scripts.evaluate_refund_priority_scoped --audit`. Evidence is isolated in results/refund-priority/v2; all rejected v1 evidence remains available.
