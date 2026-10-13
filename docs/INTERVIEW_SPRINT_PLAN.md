# Interview Sprint — independently declared five-evidence Skill

Started 2026-10-13 09:06:38 UTC. Hard candidate cutoff 13:06:38 UTC; entire implementation/experiment cutoff 16:06:38 UTC. Branch: `codex/interview-real-skill-sprint-20261013`.

## Initial audit

Stage 1 formally recorded 18 real successful learn trajectories, zero useful opportunities/candidates, 54 successful final arms, and zero C−B benefit. Its short 3/4-decision workflows could not amortize four discovery/load/execute/stop decisions. Preserve that negative result. The P0–P12 revised implementation and original revised specification remain authoritative historical records.

Reviewed `skill_evolution/workflows.py`, `experience.py`, `compiler.py`, `validation.py`, `admission.py`, `runtime.py`, and `registry.py`. Reuse the actual existing SQLite business tools, public-only model worker, search/load Runtime, conservative Opportunity Miner, TraceCompiler, four-category program validation and paired gate. A versioned adapter binds the old function code to a new task schema/EOC; historical module globals and source bytes remain unchanged. The experiment-specific registration is an immutable exploratory record, not a claim that the old formal registry's provenance auditor supports this new task.

P11 Agent process 51252 was still running at audit, progressing through W6's last sequence; it owns the existing GPU lease. The sprint waits for release and never terminates P11. CPU development and the new source files are outside its frozen source list. Existing modified P11 logs are not part of sprint changes.

## Hypothesis and protocol

Human declares `order_investigation_dossier`: collect complete customer, order, item-list, payment and shipment evidence from a single owned order. No writes/tickets. EOC compares genuine FULL returned customer/payment rows as well as order/shipment/items with independently captured SQLite facts and unchanged state; a candidate cannot provide its own correctness predicate. This is an evidence dossier, not an evaluated narrative or investigation reasoning result.

Only the existing five reads plus optional discovery are exposed in the sprint; all three arms have the same capability restriction and unchanged ownership Guard. No model, tokenizer, safety-rule, DSL or training changes. The original main-v3 system prompt remains identical across arms. Unauthorized/missing held-out cases require a genuine denial followed by refusal; raw permission-denied attempt counters remain visible rather than being erased.

Before inference, freeze task IDs, seeds, source ownership, positive/boundary/negative/fault probes, validation and held-out instances, source bytes, static catalog, budgets and selection rule in `results/interview-sprint/20261013-v1/protocol.json`. Source ledger is independent of historical formal ledgers, with unique entity prefixes.

1. Six independently grouped real train tasks using the static library, with no injected execution sequence. Preserve all exact messages, tokens, checkpoints, tool receipts, failures and source groups.
2. Run existing miner/compiler with **at least three independent sources** and **at least one saved model decision**, charging four expected Skill decisions. Initially preserve observed order. If differing successful orders prevent support, diagnose real dependency and commutativity before any separately versioned normalization; never add unseen calls.
3. Static check and eight independent actual SQLite program probes (two each positive/boundary/negative/fault), with six-source minimum and stable coverage; independent replay before publication.
4. Eight paired validation sources (six primary plus two legacy read-only retention cases) × PrimitiveOnly/StaticLibrary/ExperienceEvolution. Rotate method order deterministically. Existing safety/zero-regression/cost gate; passing arithmetic alone does not certify Agent provenance.
5. Nine dossier held-out sources (instance/paraphrase/boundary/partially refunded/unauthorized/missing) plus two legacy retention sources × three arms. This is conditional on program admission, but independent of the validation gate result: evaluate the frozen candidate as a diagnostic even when it is rejected for activation. No test feedback enters the learner.
6. Report actual and autonomous EOC, selection/search/load/execution, source/node/version provenance, all model/tool/CPU validation/audit costs, paired effects/regressions, invalid reuse and limitations. No significance claim for this exploratory sample, even if the conservative gate passes. No production activation.

Budget: separate sprint maximum 4M tokens, at most seven wall-clock hours including implementation, queue wait and experiments; existing P11 budget and historical accounting are untouched. Each inference uses existing durable pre-inference ACK admission. Unknown approved work remains charged; no implicit retries or token refills.

## Milestones

- Initial CPU contract checks: 4 passed (full customer/payment evidence, boundary/denial, existing DSL/static check, write blocking). This is scripted engineering evidence only.
- Wider learning/governance/registry regression initially hit known sandbox hard-link/Windows long-path failures (33 failed, 29 passed); rerun uses an authorized short workspace temp directory. Preserve the diagnostic and report the actual rerun result separately.
- Real inference, candidate generation, program admission, Agent admission and research benefit are **not yet established** at this plan checkpoint.

If the fourth-hour cutoff arrives without a useful candidate, stop extension and produce NO_USEFUL_CANDIDATE with causes. No lowering thresholds, no family-templated program, no post-training, no overwriting old evidence.
