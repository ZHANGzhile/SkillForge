# Interview Sprint — real new Skill closed-loop experiment

Status: **COMPLETE**. Exploratory fixed-domain evidence; no statistical significance claim.

The original Stage 1 had zero useful opportunities: short 3–4-decision tasks did not cover the frozen four-decision discovery/execution cost. This experiment tests whether independently declared five-category evidence collection yields a useful reusable program with fixed main-v3 weights.

EOC compares full customer/order/payment/shipment returns and the complete item list with initial SQLite facts, checks ownership and unchanged state. Negative tasks require an actual denial followed by refusal. Candidates cannot define correctness. This does not evaluate generated dossier prose.

The existing Opportunity Miner and TraceCompiler consume audited real learn trajectories; at least three independent source groups and at least one estimated saved model decision are required. No family-specific tool sequence, new model training, or test-driven threshold change is used.

Candidates: 1; Program Admission: True; Agent Admission: False; activation/deployment: false.

| Phase | Method | EOC | Autonomous EOC | Model calls | Tokens | Tools | Search/load | Skill successful/selected |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| learn | StaticLibrary | 6/6 | 6/6 | 36 | 97968 | 30 | 0/0 | 0/0 |
| agent-validation | PrimitiveOnly | 8/8 | 8/8 | 43 | 114790 | 35 | 0/0 | 0/0 |
| agent-validation | StaticLibrary | 8/8 | 8/8 | 43 | 114833 | 35 | 0/0 | 0/0 |
| agent-validation | ExperienceEvolution | 8/8 | 8/8 | 43 | 114962 | 35 | 0/0 | 0/0 |
| heldout | PrimitiveOnly | 11/11 | 11/11 | 53 | 140879 | 42 | 0/0 | 0/0 |
| heldout | StaticLibrary | 11/11 | 11/11 | 53 | 140932 | 42 | 0/0 | 0/0 |
| heldout | ExperienceEvolution | 11/11 | 11/11 | 53 | 141091 | 42 | 0/0 | 0/0 |

Costs including unsuccessful or incomplete collection: `{"charged_tokens": 865455, "model_calls": 324, "tool_calls": 261, "wall_seconds": 231.44131610001205, "gpu_utilization_hours": "UNMEASURED", "static_coverage_tool_calls": 339, "recorded_response_audit_tool_calls": 261, "program_validation_tool_calls": 31, "program_admission_replay_tool_calls": 31}`.

Raw paired effects (including failure costs, regressions and joint-success eligibility), per-variant results, exact model messages, tool receipts, source group ownership, candidate nodes and version identities are stored alongside this report. Source groups, not arms or tool events, are independent units. Confidence is limited by the small sample and shared task template.

Failures/limitations: None. Rejected programs and no-benefit outcomes retain the parent library. Scripted static coverage, program checks and recorded-response audits are CPU engineering evidence and are not additional autonomous learning samples.

Interview trade-offs: conservative discovery-inclusive utility, exact public-input parameter binding, provenance per node, fail-closed safety, program/Agent admission separation, held-out ownership, and preservation of negative outcomes. Scope is restricted procedural Skill learning and reuse.
