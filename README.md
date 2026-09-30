# SkillForge

[简体中文](README.zh-CN.md) | **English**

Turn tool-use trajectories into executable skills with explicit applicability boundaries, and evaluate whether those skills and their training data improve a model's action decisions.

SkillForge is a local research system for skill learning in a synthetic ecommerce environment. It includes a persistent workbench, three verified skill families, isolated datasets, real-model baselines, QLoRA SFT and DPO adapters, and full-system plus decision-level evaluation. It preserves failed experiments alongside successful ones.

**Current status:** the main-v3 SFT model has passed the six original HTTP acceptance cases and browser checks. It achieved **68/78** on a fresh-instance test set, with **10 remaining failures**. A subsequent decision-guidance candidate was **rejected** because it reduced validation decision accuracy. The deployed configuration was not replaced.

Repository: [ZHANGzhile/SkillForge](https://github.com/ZHANGzhile/SkillForge). Read the [English research overview](docs/en/RESEARCH_OVERVIEW.md) for architecture, experiment interpretation, and evidence links. Detailed historical reports and the interview trace are currently in Chinese; those links are identified below.

## Results at a glance

These are separate experiments. Do not combine scores across datasets or protocols.

| Experiment | Result | Interpretation |
|---|---|---|
| main-v2, original 78-task test | Base **35/78**, SFT **57/78**, DPO **55/78** | Same-protocol post-training comparison; all three scored **0/9** on composite tasks. |
| main-v3 recovery training | Validation **69/69**; on the same fresh 78 instances, old DPO **57/78**, new SFT **68/78** | A net gain of **14.1 percentage points**, with 13 improvements and 2 regressions. Training data and training compute both changed. |
| Same main-v3 weights, retrospective ablation | No-Skill B0 **69/78**; Skill/Gate B3 **68/78** | B3 used **48.75% fewer model calls** and **44.43% fewer tokens**, but **19.11% more tool calls**. No success-rate gain was demonstrated. |
| Fixed-program boundary-source study | Gate false allowance: A **4/16**, B/C/D **0/16**, normal coverage **8/8** each. Autonomous EOC: A **19/24**, B **20/24**, C **21/24**, D **21/24** | Gate refinement improves this positive-only baseline, but normal autonomous EOC falls **8/8 → 7/8**, failing the joint constraint. C=D; repeated-input output variation limits single-run interpretation. [Full bilingual evidence](docs/en/BOUNDARY_STUDY_RESULTS.md). |
| Boundary repeatability diagnostic, 142 executions | Normal-task repetitions: A **24/24**, B **21/24**, C **24/24**. The B refund regression repeats **0/3**, with **10/10** immediate refusals on its exact first input. | Each group still represents **8 scenarios**, repeated three times. Both historical divergent inputs vary again (**7:3**, **9:1**); underlying cause remains unidentified. Original scores are preserved. [Full bilingual evidence](docs/en/BOUNDARY_REPEATABILITY_RESULTS.md). |
| Refund boundary representation intervention, 128 executions | With execution B unchanged, a model-view transformation changes the target refund **0/3 → 3/3** and overall EOC **18/24 → 21/24**; other scenario success counts do not change. | Normal refund EOC **9/12 → 12/12**, but HIGH risk + FAILED payment remains **0/3**. Target repair uses primitive tools; total calls/tokens/tools increase. Local representation sensitivity, **not a deployment update**. [Full bilingual evidence](docs/en/BOUNDARY_REPRESENTATION_RESULTS.md). |
| Bounded adaptation to two changed policy worlds | Stale → learned false allowance: **6/54 → 0/54** and **8/56 → 0/56**, preserving all **18** and **16** applicable cases. | Same finite learner discovers two different conditions from current-version train probes. Matches complete manual policy; queries **144 → 216** per world. Controlled CPU procedures, **not model EOC or open-world learning**. [Full bilingual evidence](docs/en/BOUNDARY_ADAPTATION_RESULTS.md). |
| Refund outcome priority, rejected v1 | Boundary validation EOC **22/23 → 21/23**; fixed decisions **15/23 → 14/23**, normal EOC **8/8** in both arms. | Adding the clarification to every refund caused a LOW+FAILED escalation error and a normal-refund decision regression. Stopped after **92** records; no diagnostic continuation or deployment. [Failure report](docs/en/REFUND_PRIORITY_RESULTS.md). |
| HIGH-observation-scoped refund priority, v2 | Refund validation EOC **8/8** and fixed decisions **5/8** in both arms. Diagnostic EOC **21/24 → 24/24**; HIGH+FAILED target **0/3 → 3/3**. | **128** real-model records, including 8 previously seen refund scenarios repeated three times. Normal EOC **12/12 → 12/12**; fixed decisions **12/24 → 15/24**. Manual policy-display repair, not a boundary-learning gain or deployment. [Full evidence](docs/en/REFUND_PRIORITY_SCOPED_RESULTS.md). |
| Observed-use action counterfactuals, 15 matched contexts | Skill **15/15**; primitive **15/15** | Continuation model calls **30 → 15**, tokens **96,925 → 51,895**, tools **35 → 67**. Conditional NTR **0/15**; population NTR remains unknown. [Protocol and results](docs/en/ACTION_COUNTERFACTUAL_RESULTS.md). |
| Decision-guidance candidate, validation only | System outcome **69/69**; decision accuracy **41/45 → 38/45** | Rejected by the predeclared admission rule. Fresh test evaluation was not run. |

Actual policy violations were zero in these reported comparisons. This does **not** mean the models never attempted disallowed actions: the same-weight B0 ablation contained eight blocked writes, while B3 contained none. Permission-read failures and automatic Gate attempts are reported separately.

The main-v3 fresh test breakdown is address changes **27/30**, cancellation **15/15**, refunds **17/18**, composite workflows **3/9**, tickets **3/3**, and shipment investigations **3/3**. Fixed-candidate decision accuracy was **44/48**. Passing six product acceptance cases does not imply success on arbitrary inputs.

Latest engineering verification: **148 tests passed, 1 skipped**, with two upstream deprecation warnings; Windows/Linux CPU CI and actual desktop/mobile browser checks passed. The refund-priority follow-ups also pass offline independent-copy audits and actual desktop/mobile table checks. See the [audit receipt](results/boundary-study/v1/report-audit.json); earlier published artifacts retain their independent download receipts.

## What is implemented

- **Executable Skill Contracts:** a bounded DSL with `call`, `assert`, and `finish`, at most 12 nodes, and an allowlist of tools. No arbitrary code execution or general-purpose programming language.
- **Three-state applicability:** `APPLICABLE`, `INAPPLICABLE`, and `UNKNOWN`. The Gate performs no I/O. The runtime uses fixed read mappings to obtain missing facts; Gate and internal skill tool calls are included in costs.
- **Mutation safety:** idempotency keys and authorization/policy checks inside SQLite transactions, including safe retries after a committed write loses its response.
- **Expected Outcome Contracts:** `completed`, `refused`, and `escalated` are evaluated against the task's expected state and required evidence. A refusal or escalation is not automatically a success.
- **Boundary learning:** the compiler combines successful train trajectories, failed train trajectories, and business policy, with recorded provenance.
- **Lifecycle isolation:** train data supplies learning evidence; validation governs skill verification and revision. Memory, SFT, and DPO do not accept test data. Registry versions are immutable.
- **Training:** action-level SFT filtering, executed same-context/same-snapshot preference evidence for DPO, resumable NF4 QLoRA training, and a local trained Student service.
- **Dual evaluation:** full-system business outcomes and fixed-candidate skill/refusal/escalation probes. Model violation attempts, automatic Gate attempts, and actual environment violations are distinct.
- **Auditable experiments:** model/config/data/source identity checks, per-task checkpoints, continuous tool-state audits, preserved failures, and explicit infrastructure-error handling.

The minimal executor and Student compatibility smoke test preceded formal training. Real B0–B3 baselines were also completed before post-training. A smoke test is a compatibility check, not evidence of model quality.

## Download the repository and artifacts

Install Git and Git LFS, then:

```powershell
git lfs install
git clone https://github.com/ZHANGzhile/SkillForge.git
cd SkillForge
git lfs pull
git lfs fsck
```

Adapters, optimizer checkpoints, and SQLite artifacts use Git LFS. JSON/JSONL/CSV evidence is stored directly in Git. For a source-only clone, set `GIT_LFS_SKIP_SMUDGE=1` before cloning and pull LFS objects later when needed. LFS pointer text is not a usable model file.

The third-party Qwen base model is not redistributed in this repository. GPU training and inference require the base model and a compatible CUDA environment. Machine-specific environments, credentials, PID files, and caches are excluded. Historical artifact manifests describe their recorded commits; they are not rewritten to describe later repository states.

## Quick start: engineering checks and workbench

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m skillforge.cli demo
.\.venv\Scripts\python -m uvicorn skillforge.api:app --host 127.0.0.1 --port 8080
```

If your environment sets `PIP_NO_INDEX=1`, set `$env:PIP_NO_INDEX='0'` before installing from an accessible package index.

Open `http://127.0.0.1:8080` for the workbench and `/docs` for API documentation. The `demo` command uses an explicitly scripted engineering policy; its results are **not real-model performance**. Launching the web server does not provision a trained model automatically.

On the already configured development machine, double-click `启动项目.cmd` (the project launcher) to start the signed-off model and workbench. A new machine must first provision its model service and local configuration. The legacy skill demonstration is at `/skill-demo`; engineering checks are at `/engineering`. The workbench UI is currently primarily Chinese; this English README does not imply that the UI has been localized.

The workbench supports dataset and custom tasks, live trajectories, persistent history, skill contracts, experiment reports, cancellation, isolated retries, and trajectory/database downloads. Custom tasks specify their request, parameters, initial business state, and Expected Outcome Contract; expected outcomes are not guessed from free text.

### Persistence and cancellation

Jobs and events are stored in `results/workbench/jobs.sqlite`; each run has its own business database and trajectory. Cancellation takes effect after an active model request returns and before the next action/tool operation. Committed mutations are not rolled back.

After a service interruption, queued jobs can resume, while previously running jobs become `interrupted` and require an explicit isolated retry. Submission supports `Idempotency-Key`; reusing a key with different parameters returns HTTP 409. Queued jobs refuse an unrecorded switch in model configuration or source identity.

Use **one worker**, not multiple Uvicorn workers. Relevant environment variables include `SKILLFORGE_JOB_ROOT`, `SKILLFORGE_DATASET`, and `SKILLFORGE_BUNDLE`. This is a localhost, single-user research application. Legacy `/tasks` and `/benchmark/run` endpoints do not provide the persistent queue's recovery guarantees.

## Connect a real Student model

The Student is the model being evaluated or trained to choose the next action. It is separate from the web application and business tools.

```powershell
$env:SKILLFORGE_MODEL_URL='http://localhost:8001/v1'
$env:SKILLFORGE_MODEL_NAME='your-model-name'
$env:SKILLFORGE_API_KEY='local'
.\.venv\Scripts\python -m skillforge.cli model-smoke
.\.venv\Scripts\python -m skillforge.cli benchmark
```

`.env.example` is a configuration example; the application reads process environment variables and does not automatically load `.env`. The smoke test checks the chat endpoint and JSON Action compatibility, not training readiness or task competence. The client bypasses system HTTP proxies; proxy-based deployments need additional configuration.

Use `python -m skillforge.cli benchmark --scripted` for engineering-only checks. Without `--scripted`, the benchmark uses the configured real model.

## Reproduce the isolated engineering pipeline

The original experiment dataset contains **216 tasks: 69 train, 69 validation, and 78 test**. Task instances, orders, and template content are separated across splits. The three-branch composite structure is reserved for test. Manifests bind file hashes and isolation checks.

```powershell
.\.venv\Scripts\python -m skillforge.cli dataset --output data/experiment-v1 --instances 3
$collected = .\.venv\Scripts\python -m skillforge.cli collect --dataset data/experiment-v1 --output results/sources --scripted --failure-fixtures | ConvertFrom-Json
.\.venv\Scripts\python -m skillforge.cli prepare --dataset data/experiment-v1 --source $collected.source_path --output results/frozen --scripted
.\.venv\Scripts\python -m skillforge.cli compare --dataset data/experiment-v1 --bundle results/frozen/frozen.json --output results/comparisons --scripted --ablation --repeats 3
```

`--failure-fixtures` intentionally executes incorrect actions only in explicit engineering mode to test verification. For real-model collection, configure the endpoint, remove `--scripted` and `--failure-fixtures`, and use new frozen output directories. Missing successful or business-failure train evidence must be collected from train; test examples cannot fill that gap.

`prepare` checks source tasks, initial states, content fingerprints, and deterministic verdicts. Relabeling a trajectory's split is insufficient. B2 uses a success-only Naive Skill; B3 uses success, failure, and policy evidence followed by validation. Tampered bundles or bundles from a different dataset are rejected.

`--ablation` adds B3 without the Gate. Repeated-run success is descriptive stability, not pass@k or a significance test. Scripted comparisons validate the framework, not algorithmic gains.

## Refunds and bounded skill revision

The compiler supports address changes, cancellation, and refunds. Use `--families modify_address cancel_order` to select a subset. Refund applicability checks a positive integer amount against the remaining balance using known observations and inputs only. The executor freezes the expected cumulative refund before mutation and verifies it afterward with `get_payment`.

Candidate validation can trigger at most two revisions. Supported repairs restore the boundary or procedure from train-plus-policy evidence; validation selects the repair, rather than supplying training trajectories. Exhausted budgets, unsupported repairs, or persistent infrastructure failures result in rejection. Original candidates and all attempts remain available.

```powershell
.\.venv\Scripts\python -m skillforge.cli refine --dataset data/experiment-v1 --source PATH_TO_TRAIN_JSONL --candidate PATH_TO_CANDIDATE_JSON --output results/new-repair-run --scripted --max-refinements 2
```

`--max-refinements 0` validates without repair. Remove `--scripted` when using real-model sources.

## Training and experiment artifacts

Formal main-v2 SFT/DPO adapters are in `results/training/main-v2/{sft,dpo}/adapter`. The main-v3 recovery run used 1,267 deduplicated action targets and 318 optimizer updates. Its teacher trajectories are explicitly deterministic and are not counted as Student achievements. Injected distractor reads provide history but are excluded as SFT targets.

Training progress is available through `/api/v1/training` and [the training log (Chinese)](docs/TRAINING_LIVE.md). See [training and recovery instructions (Chinese)](docs/TRAINING.md) for environment setup and resume commands. Do not start a second GPU training pipeline while one is active.

Completed experimental reports can be regenerated with the matching frozen source, configuration, data, and artifacts:

```powershell
.\.venv\Scripts\python -m scripts.report_reuse_ablation
.\.venv\Scripts\python -m scripts.report_decision_guidance
```

The latter is a read-only audit/report command; it does not override the rejected guidance candidate's admission decision or launch its unrun test arms.

## Scope and limitations

The environment is synthetic and bounded: SQLite persistence, simplified fields, one payment and shipment per order, and a string-length address-validity rule. Cancellation does not automatically authorize a refund.

The compiler performs constrained domain induction and up to two revisions. There is no open-domain LLM skill synthesis, recursive skill composition, or embedding retrieval. Raw Memory uses lexical similarity and family ranking. Composite tasks currently require the runtime's action policy to choose primitive operations.

Fresh instances still come from known generators and structural families. Validation has been inspected repeatedly. Whole-system Skill/Gate ablations change visible state and later contexts; their paired regressions are not same-context causal negative transfer. **Causal NTR remains `null` where the required counterfactual experiment has not been performed.**

Docker configuration is provided (`docker compose up --build`), but container execution has not passed acceptance on the development machine. Windows/Linux CPU CI has passed; this does not establish GPU portability or production readiness.

## Documentation and evidence

| Resource | Language / purpose |
|---|---|
| [Research overview](docs/en/RESEARCH_OVERVIEW.md) | English architecture, results, failures, and interpretation |
| [Chinese README](README.zh-CN.md) | Chinese project entry point |
| [Implementation progress](docs/PROGRESS.md) | Chinese implementation and acceptance history |
| [Issues and resolutions](docs/ISSUES.md) | Chinese difficulties, remedies, and verification |
| [Interview trace](docs/PROJECT_INTERVIEW_TRACE.md) | Chinese detailed rationale and technical questions |
| [Recovery results](docs/RECOVERY_RESULTS.md) | Chinese main-v3 outcomes and remaining failures |
| [Same-weight ablation](docs/REUSE_ABLATION_RESULTS.md) | Chinese paired outcomes and safety/cost breakdown |
| [Rejected guidance experiment](docs/DECISION_GUIDANCE_RESULTS.md) | Chinese validation results and seven decision errors |
| [GitHub publication](docs/GITHUB_PUBLICATION.md) | Chinese download, artifact, and publication history |
| [main-v3 publication receipt](results/recovery-github-publication.json) | Machine-readable artifact verification |
| [Ablation publication receipt](results/reuse-ablation-publication.json) | Machine-readable artifact verification |
| [Guidance publication receipt](results/decision-guidance-publication.json) | Machine-readable artifact verification |
