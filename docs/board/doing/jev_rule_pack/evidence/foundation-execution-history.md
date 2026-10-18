# A2 foundation execution evidence

2026-10-14: `make deps` passed. A1 now accepts `judge(run_identity=...)`, retaining the environment fallback for
existing callers. The client suite passed 53 offline tests. The required no-`.env` integration command,
`PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/core/judgments/test_observability.py`, passed
five tests, including two evaluations in one interactive run: four distinct attempts, two verb invocations, unchanged
environment and retained parent/root ancestry. The harness warned about missing `GEMINI_API_KEY`; these five tests use
an injected transport and passed without it. A2 child-run creation and cache behavior remain pending.

The explicit-identity change was originally committed as `e0d02ed4`; full `make pre-commit` passed before committing.
Consent helpers now bind the existing bundle-config acknowledgment to the session instance and settings without a
manifest schema bump. The raw override guards cover parent objects, bundle/config writes, wildcard expansion, effective
activation and resets that would uncover old intent. Disabling through raw overrides revokes both grant layers. These
are preparatory guards; the validating activation command, rule registry and dispatch remain unimplemented.

The consent foundation was originally committed as `1a029213`. The independent Claude permission fix began at `a281be33`
and later merged through [PR #269](https://github.com/hapa1i/multi-forge/pull/269) as `e9c144eb`. On 2026-10-15 the user
selected broader wrappers and chose to skip paid native testing. Human labels and quality gates remain open; neither the
A2 draft nor the merged permission fix establishes native delivery.

The focused consent/override/CLI tests and inheritance/direct-command regressions passed 165 tests. Docker integration
passed all six derivation paths (same-directory fork, new worktree, existing worktree, native resume, transfer resume
and relaunch), plus four policy CLI contract tests. The first integration run exposed a missing project-enrollment step
in the existing-worktree fixture; a later run caught an import cycle introduced while moving a consent import. Both were
fixed, and the final ten-test run passed. Rewind-specific orchestration and native delivery remain open acceptance
items.

Aggregate checks for this consent foundation passed: `make test-unit` (10,947 passed, 117 integration tests deselected),
`make test-regression` (1,855 passed), and the existing policy hook integrations (28 passed). Combined with the five
judgment-observability and ten lifecycle/CLI integrations above, 43 selected integration tests passed with no live
inference. These results do not satisfy the remaining rule-quality or native-delivery gates.

2026-10-15: the user selected broader wrappers and declined the paid Claude native trial. The revised evidence contract
separates compatibility retention from required boundary behavior, admits module/method/callback/alias candidates, and
requires attributed surface/exception facts. No local-helper-only restriction or safe-deletion claim remains.

The offline preparation harness validates 14 constructed cases in nine source families (nine calibration, five
held-out), all unadjudicated. It keeps labels outside model state, rejects split leakage and stale rule/evidence
annotations, preserves complete supplied inputs or rejects oversized requests, and has no live mode.
`uv run pytest tests/src/scripts/test_jev_rule_pack_eval.py tests/src/scripts/test_jev_probe.py -q` passed 32 tests. The
[preparation report](wrapper-preparation.json) records request hashes and sizes with zero dispatches and quality
acceptance false. Host-owned fact resolution, human labels, numeric gates, prediction/metric evaluation and hook wiring
remain unimplemented.

Full `make pre-commit`, the reproducible offline preparation report and `git diff --check` pass for this update. No
runtime policy code changed in this update; the aggregate and integration results above apply to the foundations.

2026-10-15 rebase: all six A2 commits rebased without conflicts onto `main` at `18b5670e`, including the merged Claude
permission fix and its closeout. The A2 diff under `src/`, `tests/` and `scripts/` is byte-for-byte unchanged from the
previous PR head, `f5d57f1d`. The focused consent, override, judgment, feedback and probe suites passed 318 tests. The
no-`.env` integration rerun passed all 43 selected judgment-observability, session-derivation, policy CLI and
policy-hook tests, using injected responses and fixture runtimes. Full `make pre-commit` passed, and the offline
preparation report reproduced exactly. The follow-up reconciles prerequisite links and status; no paid/native test ran,
and quality and native-delivery gates remain open.

2026-10-15 review corrections: all policy disable entry points now revoke both acknowledgment layers, including repeated
raw disable. Terminal disable also removes a conflicting enabled override. Raw set/reset still cannot activate Jev;
refusals now name the working disable-then-reset recovery. The consent record's trusted-writer boundary is documented.

The revised corpus has 17 constructed, unadjudicated cases across seven source families: 12 calibration and five
held-out. Related module/multi-file variants share their calibration family. Required callback and validation adapters
carry supplied consumer contracts, alongside redundant-validation and return-shape counterexamples. Reviewer scope notes
no longer enter model input. The applicability table resolves four cases on the host and prepares 13 model inputs; these
counts are preparation coverage, not a quality result. Annotation identity retains semantic criteria and evidence while
instruction wording has a separate prompt hash. Per-question human answers are supported but remain unset.

Validation: the 300 focused consent/override tests and 38 harness/leakage tests passed. The selected Docker suites
covered 46 distinct tests with injected responses and fixture runtimes. The initial run passed 44 and exposed two
recovery-test assertions that compared Rich-wrapped command text literally; after comparing and executing parsed argv,
all three disable/recovery cases passed the targeted rerun. No runtime correction was needed for those two assertions.
The runner reported the expected missing-Gemini-key warning; these tests make no paid inference requests.

The integrated review corrections passed `make test-unit` (11,001 passed; 117 integration tests deselected) and
`make test-regression` (1,889 passed). Full `make pre-commit`, `git diff --check` and both file/diff forms of
`forge policy check --bundle coding_standards` passed. The offline preparation report reproduces byte-for-byte. The
telemetry document's required provider token-count cache was refreshed; no paid model evaluation or native trial ran.
