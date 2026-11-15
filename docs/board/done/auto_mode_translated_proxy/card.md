# Use the local auto-mode classifier on translated proxies

User-authorized November 15, 2026. Branch: `fix/auto-mode-translated-proxy`, based on `main` at `37422ee1`.

Shipped November 15, 2026 via [PR #299](https://github.com/hapa1i/multi-forge/pull/299) (`f10a66d3`).

Claude Code 2.1.278+ asks Anthropic's server to review auto-mode actions whenever `ANTHROPIC_BASE_URL` points at a
gateway. The request carries a `safeguards` body field and a `dangerous-tool-use-2026-09-03` beta; the review runs
in-band against the model's tool calls. Forge's translated proxy drops the unknown field and the non-Anthropic upstream
returns no review result. Interactive Claude Code 2.1.325 then stops with "Auto mode can't check actions in this
session" (`server_no_result` in the debug log) and asks the user to approve each checked action. The review cannot be
supplied by a translated route.

Forge-managed Claude launches on `openai_translated` and `openai_responses_passthrough` routes set
`CLAUDE_CODE_AUTO_MODE_SERVER=0` unless the user set it, so Claude Code sends its own classifier requests through the
proxy from the first action. A marker distinguishes Forge's value from the user's so nested direct, passthrough, and
unknown-shape launches drop the inherited default. Launches print one stderr line naming the predicted judge model.

Behavior change: on translated routes a non-Claude model (normally the sonnet tier) becomes the auto-mode judge, and
each classified action is a separate request through the proxy (about 140,000 prompt characters in a 2.1.325 probe). The
proxy guide documents keeping a Claude judge on OpenRouter.

Sources checked November 15, 2026:

- [Server-side classifier review](https://code.claude.com/docs/en/permission-modes#server-side-classifier-review)
- [Default and chosen classifier model](https://code.claude.com/docs/en/permission-modes#default-classifier-model)
- Local fake-endpoint probes of Claude Code 2.1.325 (default, server off, server off with
  `CLAUDE_CODE_ATTRIBUTION_HEADER=0`, and a `CLAUDE_CODE_AUTO_MODE_MODEL` slug override)
