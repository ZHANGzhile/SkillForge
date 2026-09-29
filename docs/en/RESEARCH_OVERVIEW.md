# SkillForge: architecture and research evidence

[English README](../../README.md) | [中文项目说明](../../README.zh-CN.md) | [中文详细复盘](../PROJECT_INTERVIEW_TRACE.md)

This overview describes the implementation and evidence available through September 27, 2026. It distinguishes framework correctness, model performance, product acceptance, and publication verification.

## Research question

Can tool-use experience become reusable, executable skills with reliable boundaries, and can those skills and their trajectories improve a Student model's action decisions?

The project tests this in a synthetic ecommerce environment with address changes, cancellations, refunds, tickets, shipment investigations, and composite requests. It does not claim open-domain business automation.

## Architecture and responsibility boundaries

| Component | Responsibility | Boundary |
|---|---|---|
| Student model | Select the next JSON Action: tool, skill, stop, refuse, or escalate | Receives visible observations and history, not the expected-outcome oracle |
| Runtime | Execute actions, maintain observations, handle bounded retries, and record trajectories | Does not treat missing observations as an observed `UNKNOWN` business state |
| Applicability Gate | Return `APPLICABLE`, `INAPPLICABLE`, or `UNKNOWN` from the contract and visible facts | No model calls or I/O; it is not another agent |
| State hydration | Read missing facts through fixed mappings | Calls are audited and included in Gate costs |
| Skill executor | Run bounded `call/assert/finish` procedures and verify postconditions | Allowlisted tools, at most 12 nodes, no arbitrary code |
| Business tools | Read or mutate SQLite state | Authorization and policy checked inside the tool; mutation idempotency enforced |
| Compiler and registry | Derive boundaries from successes, failures, and policy; validate and version contracts | Train-only learning evidence, validation-only acceptance, immutable versions |
| Expected Outcome verifier | Check the allowed outcome, expected state, preserved state, and required evidence | Refusal and escalation are not interchangeable or automatically successful |
| Workbench | Persist jobs/events, expose reports, support cancellation and isolated retries | Localhost, single-user operation; not a production multi-tenant service |

Mutations reuse the logical operation identity across primitive and skill retries. This handles the case where a write commits but its response is lost, without duplicating the effect. A repeated idempotency key with different arguments is rejected.

## Data and training lifecycle

The original isolated dataset has 69 train, 69 validation, and 78 test tasks. Instance IDs, order IDs, and template content are separated. Some composite structures and policy combinations are deliberately held out. Shared domain semantics remain a limitation despite this separation.

Skill boundaries use **successful trajectories + failed trajectories + business policy**. Business counterexamples can constrain applicability; transient timeouts alone do not create business prohibitions. Validation can select a bounded repair, but it cannot supply training examples. Up to two revisions are supported.

SFT uses action-level filtering. DPO pairs use executed alternatives with the same prompt/context and database snapshot. These are different from comparing two entire agent runs whose observations diverge.

The initial executor, compatibility smoke checks, and real-model B0–B3 baselines preceded formal post-training. The main-v3 recovery curriculum later executed 1,035 deterministic teacher trajectories and merged supervision into 1,267 deduplicated SFT action targets. Injected read distractions were excluded as targets. These counts describe training construction, not independent tasks or real-model successes.

## What the experiments actually show

### Original model and post-training comparisons

The initial real free-action baseline scored B0 35/78, B1 45/78, B2 38/78, B3 37/78, and no-Gate 38/78. Actual skill calls were zero, so these results did not demonstrate executable reuse benefits. That serving protocol must not be pooled with later HF post-training experiments.

In the main-v2 HF comparison on the original test set, Base/SFT/DPO achieved 35/78, 57/78, and 55/78, respectively. Fixed-candidate decision scores were 4/48, 44/48, and 44/48. All three scored 0/9 on composite workflows. DPO did not beat SFT on that test; the negative result is retained.

### Recovery SFT: main-v3

The recovery model completed 318 optimizer updates and passed validation at 69/69. On a separately frozen set of 78 fresh instances, the old DPO reference achieved 57/78 and new SFT 68/78: 13 paired improvements and 2 regressions, for a net gain of 14.1 percentage points. Decision accuracy was 45/48 for the old reference and 44/48 for the new model.

Both training content and compute changed, so the improvement cannot be attributed solely to the curriculum. The fresh tasks use known generators and structures, and validation has been inspected repeatedly.

The new model passed all six original HTTP acceptance cases, including the two refunds that had failed under the old deployment. Desktop/mobile, refresh recovery, history, and report checks passed. This is product acceptance on six defined cases, not a universal success guarantee.

### Same-weight Skill/Gate ablation

| Metric | B0: no Skill | B3: Skill/Gate |
|---|---:|---:|
| EOC-qualified tasks | 69/78 | 68/78 |
| Average model calls | 4.6282 | 2.3718 |
| Average tool calls | 4.0256 | 4.7949 |
| Average tokens | 11,971.77 | 6,653.26 |
| Skill calls | 0 | 15 |
| Blocked write attempts | 8 | 0 |
| Actual policy violations | 0 | 0 |

B3 reduced model calls by 48.75% and tokens by 44.43%, while increasing tool calls by 19.11%. There were zero paired success improvements and one regression. The result supports a system-level cost difference, not a success-rate improvement.

The one regression involved a refund request for 64,797 against a captured amount of 64,796. B0 attempted the invalid refund, the tool blocked it, and the model then correctly refused. B3 repeatedly read state until its 16-step budget expired. B3 did not call a skill in this case.

This illustrates why final EOC success and process compliance are distinct. A task can end correctly after an incorrect attempt is blocked. B0 had eight blocked writes and three permission-read failures; B3 had three automatic Gate permission-read failures. Both had zero actual violations.

The system regression rate was 1/78; conditional on B0 success, it was 1/69. Neither is same-context causal NTR: removing Skill availability also removes automatic Gate hydration and changes later contexts. B0 used HTTP and the B3 reference used direct HF, so strict latency attribution is also unsupported. The causal NTR field remains `null`.

### Rejected decision-guidance candidate

An independent candidate added policy-priority reminders, composite-workflow guidance, and arithmetic derived only from visible payment fields. It did not change weights, execute tools, access expected outcomes, or replace the model's actions.

The predeclared admission rule required validation 69/69, zero model violation attempts, zero actual violations, and at least 41 correct decisions. The candidate retained system 69/69 but scored only 38/45 on valid decision probes. Skill calls fell from 13 to 1; average tokens increased by 11.71%.

Of seven decision errors, four returned primitive tools outside the probe's allowed skill/refuse/escalate candidate set. The other three escalated LOW-risk, SHIPPED cases that required refusal. Paired decision changes were one improvement and four regressions. A primitive tool may be legal in free-action execution while still being incorrect under this specific probe; this is not evidence of an actual environment violation.

The candidate was rejected. Neither fresh-test arm ran, and deployment stayed unchanged. A frozen test dataset is not a test result. The experiment does not identify which individual guidance sentence or formatting change caused the regression.

## Remaining failures

Nine of the ten main-v3 test failures concern combinations absent from the original train and validation splits: three high-risk/shipped address cases, three invalid-address cancellation fallbacks, and three shipped-order human-escalation fallbacks. Their absence was intentional in the original split design; it is not automatically a data-pipeline defect.

The remaining excess-refund failure occurred despite related train and validation coverage. Therefore, lack of training coverage does not explain every failure. Future work needs explicit coverage and protocol decisions, not relabeling already inspected test examples as fresh evaluation.

## Single-action counterfactuals at observed uses

The September 29 experiment replays every eligible observed Skill call from the 78 frozen main-v3 trajectories: 15 contexts, with no exclusions. Each pair has the identical model context, complete SQLite dump, remaining fault queues and replay position. Only the next action is forced to Skill or its matching primitive mutation; subsequent actions come from the same pinned model, with Gate, candidate Skills and total budget unchanged.

Both arms passed **15/15** EOCs, with no actual violations. Skill continuation used **15 model calls / 51,895 tokens**, versus **30 / 96,925** for primitive; post-fork tool calls were **67 versus 35**. Observed-use conditional NTR was **0/15**. Population NTR is still null: the observed calls happen to originate from successful source trajectories, and these pairs do not cover Skills the model never selected. This retrospective experiment does not repair the ten main-v3 failures or justify a deployment change. See the [full English protocol and results](ACTION_COUNTERFACTUAL_RESULTS.md).

## Fixed-program boundary-source study

The original compiler audit found that removing failure evidence changed admission/provenance, while admitted contracts retained the same conditions. A separate bounded learner was therefore evaluated with identical procedures: positive constants (A), failure refinement (B), complete rules (C), and rules plus refinement (D). On 24 test scenarios, false allowance was **4/16 for A and 0/16 for B/C/D**; all retained **8/8 normal coverage**. B-A's scenario-cluster bootstrap interval for the false-allow difference was **[-50, -6.25] percentage points**. This is conditional synthetic-sample evidence, not a population guarantee.

Autonomous system outcomes: A **19/24**, B **20/24**, C **21/24**, D **21/24**. The study audited **216 actual / 288 logical runs**, including single-attempt Gate bypasses at preselected candidate points. Identical public C/D contracts use explicit evidence aliases, not independent repetitions. B failed the normal-system retention constraint (8/8 → 7/8). Two of 79 repeated exact-input clusters had divergent Actions under the same recorded settings, so single-run EOC differences do not establish stable causal gains. D=C does not establish benefits beyond complete policy. Training examples came from explicitly controlled executions, with human feature priors. See the [full results](BOUNDARY_STUDY_RESULTS.md).

CPU reproduction: `python -m scripts.audit_boundary_study`; bilingual report generation: `python -m scripts.report_boundary_study`. Both work through a strict relative-path resolver for the two absolute source paths in the unchanged original preparation manifest. Neither command requires GPU inference.

## Reproducibility and evidence

Each evaluation binds task, model, configuration, and source identities. Completed checkpoints are audited before reuse. Tool audits must form a continuous initial-to-final state chain, and EOC summaries are recomputed. Guidance experiments also preserve both the original runtime context and the actual model input.

Infrastructure failures are saved separately from model failures. The ablation resumed from 40 completed checkpoints after its processes had exited; those completed tasks were audited and reused rather than rerun to select better answers. Unrecorded interrupted requests are not included in reported logical-task costs, so those figures are not total operating costs.

Git LFS stores adapters, optimizer checkpoints, and SQLite files. The third-party base model and machine-specific caches are excluded. Independent remote downloads verified published artifact bytes and hashes. Publication verification establishes artifact availability and integrity, not model quality.

| Evidence | Location |
|---|---|
| main-v3 results and failures (Chinese) | [Recovery report](../RECOVERY_RESULTS.md) |
| Full same-weight ablation (Chinese) | [Ablation report](../REUSE_ABLATION_RESULTS.md) |
| Boundary coverage (Chinese) | [Coverage audit](../BOUNDARY_COVERAGE.md) |
| Rejected candidate (Chinese) | [Guidance report](../DECISION_GUIDANCE_RESULTS.md) |
| Detailed technical rationale (Chinese) | [Interview trace, including sections 32–35](../PROJECT_INTERVIEW_TRACE.md) |
| Per-task ablation evidence | [results/reuse-ablation/main-v3](../../results/reuse-ablation/main-v3) |
| Per-task guidance evidence | [results/decision-guidance/v1](../../results/decision-guidance/v1) |
| Recovery publication verification | [Receipt](../../results/recovery-github-publication.json) |
| Ablation publication verification | [Receipt](../../results/reuse-ablation-publication.json) |
| Guidance publication verification | [Receipt](../../results/decision-guidance-publication.json) |

The latest engineering regression recorded 123 passing tests and one skip. Windows/Linux CPU CI and browser checks passed. Docker runtime acceptance and general production readiness have not been established. The browser workbench and detailed historical logs are primarily Chinese; the English entry points cover the project and its research evidence.
