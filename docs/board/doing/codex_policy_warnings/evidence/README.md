# B3 feedback evidence

Round: 2026-10-10. B3 implements bounded Codex model feedback, independent operator warnings, and the selected
`source-only` format. The product controls use registered, user-trusted Forge hooks and an independent Codex login. The
one real Claude review uses the maintainer's CLI-managed Max login with `auth_mode=subscription-only`; extra usage was
confirmed disabled. No paid API inference or Jev call was used.

## Results

The retained runtime is Codex **0.162.1**, model `gpt-6.1-sol`, effort `low`. Its executable SHA-256 is
`74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`. [Capture index](captures.json),
[assertion report](verification.json), and [environment/enrollment](environment.json) retain the exact identities,
budget, and selected evidence. The feature admits the separately measured versions 0.161.0 and 0.162.1. The general QA
ceiling remains 0.161.0, release pin 0.149.1, and proxy floor 0.141.0; shared QA revision/date fields were not changed.

| Control                       | Observation                                                                                                                                   | Evidence                                                                                                                                     |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Trusted permissive TDD        | Bare `additionalContext` reached a native developer message tagged `hooks.additional_context`; edit landed                                    | [TDD](trusted-v1-tdd.json)                                                                                                                   |
| Trusted stub reviewer         | Private reviewer nonce reached that message and the model's answer; edit landed                                                               | [Stub](trusted-v1-stub.json)                                                                                                                 |
| Feedback off, fresh thread    | Operator wire and audit survived; nonce and injected warning absent from native turn; model answered `NONE`                                   | [Off](off-headless.json)                                                                                                                     |
| Source-only, exact quote      | Model consumed the private source marker; reviewer nonce absent from model fields/native turn                                                 | [Source](source.json)                                                                                                                        |
| Source changed after snapshot | Verified quotation still identified the reviewed snapshot, despite the stub replacing the on-disk plan                                        | [Snapshot](source-changed.json)                                                                                                              |
| Fabricated quote              | Warning remained allowed with fixed missing-quote text; no reviewer prose fallback                                                            | [Invalid quote](source-invalid.json)                                                                                                         |
| Fabricated quote on a denial  | Existing confidence/citation block threshold remained unchanged; fixed stop-and-ask guidance; no edit                                         | [Source deny](source-deny.json)                                                                                                              |
| Multiple files                | One response included both attributed implementation warnings after a clean documentation file                                                | [Multiple files](multi.json)                                                                                                                 |
| Warning plus denial           | Entire patch blocked; deny wire contained only the blocker; warning remained in audit                                                         | [Mixed](mixed.json)                                                                                                                          |
| Admitted sleeping reviewer    | Dispatch-start marker preceded timeout; allowed edit was described as unreviewed; attempt/status/activity retained timeout                    | [Timeout](timeout.json), [status](timeout-status.json)                                                                                       |
| TUI operator-only             | Inline `Hook ·` warning showed the private nonce; native model turn lacked it and answered `NONE`                                             | [TUI off](tui-off-final.json)                                                                                                                |
| TUI combined channels         | Operator warning appeared and model consumed its separately injected context under schema-2 process admission                                 | [TUI combined](tui-review-final.json)                                                                                                        |
| Model-only control            | Instrumentation removed only `systemMessage`; original product wire retained; model consumed the nonce                                        | [Instrumented control](model-only.json)                                                                                                      |
| Final clean wheel             | Source-only warning, feedback-off, and deny passed with wheel imports, no `FORGE_DEV`, and unchanged registration/trust bytes                 | [Source](wheel-review-source.json), [off](wheel-review-off.json), [deny](wheel-review-deny.json), [artifact](wheel-review-verification.json) |
| Real Claude quote quality     | One `claude-sonnet-5-5` review returned two exact quotations; Forge retained source digest and offsets; usage classified `subscription_quota` | [Real review](real-claude-authenticated.json)                                                                                                |

Every selected Codex action used exactly one `apply_patch` through the native `exec` tool, with no other tool call or
evidence read. Source/reviewer nonces were absent from the executor task and private plans were outside the checkout.
The assertion report checks the latest native turn, not merely the final answer. Full reviewer evidence remains readable
in workspace/session records; source-only limits Forge's hook fields and does not provide access isolation or prompt
injection immunity. The model-only control is explicitly instrumented and does not replace the unmodified product
integration.

The current report selects 12 historical captures and four review replays. The replays exercise the corrected
process-bound admission; older schema-1 captures retain their original identities. See the
[initial report](verification-initial.json) and [review validation](validation.md#pr-review-corrections) for the source
revisions, restored blocking guidance, shim regressions, and failed TUI setup retained before the passing retry.

On 0.162.1, operator warnings appeared inline as `Hook ·`; F2 opened a separate startup-warning panel. B2's 0.161.0 TUI
label was `Hook notice`. These results establish the observed TUI surface, not headless event-stream visibility or every
future version. B3 did not rerun 0.161.0's combined response; its historical separate-channel evidence remains qualified
by B2's publication audit.

## Verification

- `make test-unit`: final result recorded in [validation](validation.md).
- `COLUMNS=200 make test-regression`: final result recorded in [validation](validation.md).
- Targeted Docker hook/manual-policy/auth-isolation/old-reviewer tests: final result in [validation](validation.md).
- Dedicated trusted `tests/integration/core/test_codex_policy_feedback.py`: **2 passed**, with the explicit independent
  fixture restored after pytest's normal home isolation.
- `make build` and a clean install outside `uv.lock`: built and exercised the final candidate wheel.
- `make pre-commit`: full hook suite, including types, Markdown links, sizes, and secrets; final result in
  [validation](validation.md).
- Manual `coding_standards` checks on `if TYPE_CHECKING: ...`, through both `--file` and piped `--diff --json`, returned
  the expected denial/exit 1 with JSON results: [file](manual-file.json), [diff](manual-diff.json).

The quote-quality run exposed a current-login compatibility issue in B1's guard: Claude 2.1.294 omitted
`oauthAccount.organizationType` while auth status explicitly reported a personal Max subscription. B3 now admits that
verified status while retaining legacy personal metadata support and refusing unknown, conflicting, API-backed, or
managed routes. Regression tests cover both metadata generations; Docker tests retain auth-setting isolation and
no-inference refusal. The real call passed after the user logged in and this compatibility fix landed.

## Reproduction and limits

See [validation and provenance](validation.md) before replaying. The private round lives at `$ROUND`; exported paths use
`$ROUND` and `$CHECKOUT`. Do not copy host auth or reset an enrolled home. Each live rerun needs a new case label; the
quota wrapper reserves failed attempts too. The retained package must remain complete and unchanged.

The extended round reserved **32 of 32 Codex turns**, including enrollment, seed starts, failed TUI attempts, and all
three wheel sets. Exactly **one real Claude inference** was dispatched; earlier local configuration/auth refusals made
no model call. Runtime-reported token/cost fields are telemetry, not proof of an invoice or exact quota decrement.
Subscription exhaustion did not happen naturally and remains unverified. The scope does not include B4 Stop review, B5
native forks, or any Jev inference.

Fixture-owned process sweeps left no survivors, and isolated enrollment stayed unchanged. Host `config.toml` differs
from the initial round hash; its modification time predates the review replays, and the cause is not established. Both
hashes are retained in the report; `hooks.json` remains absent. Normal Codex auth was never copied, which does not prove
host refresh-token validity. The user refreshed their own Claude login during the round. Keep the independent Codex
login and retained artifacts until review/merge; post-merge closeout owns their teardown and the board lane move.
