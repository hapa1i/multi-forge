# Bounded diagnostic capture review

Prepared on 2026-10-18 from the [completed human review](diagnostic-review-2026-10-18-batch-6.json) and the
user-selected [two-arm plan](bounded-feasibility-plan.md). This packet freezes the proposed requests and limits for
review. On 2026-10-18 the user explicitly authorized implementation, fixture verification and the paid calls needed for
this bounded study. Execution follows the offline checks and remains limited to these bodies, slots and stop rules. The
preparation tool has no live mode, and the manifest itself cannot grant spending authority.

The [2026-10-18 capture](bounded-diagnostic-2026-10-18/README.md) consumed this allowance: 38 requests, with Jev stopped
after two and Opus completing 36. Both failed the frozen screen. Reported cost was $1.029230756 with no unknown attempt
costs. The remaining 34 slots cannot be reused.

## What would be sent

The [manifest](bounded-capture-manifest.json) contains 24 exact request bodies: one per case and arm. Its 72 ordered
slots reference those bodies by identity and wire digest, repeating each body three times. Stage 1 contains 24 slots;
Stage 2 contains 48. Both arms receive the same 12 synthetic actions, host scope facts, reviewed target annotations,
transformations, question bindings and 95 Choice questions. Labels, reviewer notes, provenance and transformation
results stay outside provider bodies. No native actions, repository history or conversations are included.

Arm J uses Jev through OpenRouter Decisions with ZDR required. Arm R uses Opus 5.5 through OpenRouter Chat, restricted
to `google-vertex/global`, with fallback disabled, ZDR required and data collection denied. R requests a strict JSON
object mapping question IDs to allowed option keys, medium reasoning, non-streaming output and a 4,096-token completion
limit. It requests no rationale, tools, plugins or response healing.

The API envelopes differ. J retains the exact instruction guard on every question. R places that same guard once in its
system message, applying it to every question, and removes only the identical prefix from each question's instructions.
Offline checks reconstruct every full instruction and compare all criteria and evidence with J. This keeps the
mixed-target request within the existing byte screen without changing the reviewed questions or removing annotations. It
does not make the two models' serialized prompts identical.

The largest frozen bodies are 28,840 bytes for J and 28,458 for R. Their byte-plus-allowance input estimates are 30,888
and 30,506 respectively. The longest compact reference answer object is 713 bytes; fitting the visible answer does not
prove that 4,096 tokens will provide enough reasoning for this task.

## Limits and accounting

| Limit                 | Value                                                          |
| --------------------- | -------------------------------------------------------------- |
| Physical requests     | At most 72; 36 per arm                                         |
| Question observations | At most 285 per arm                                            |
| Exact request body    | At most 30,000 UTF-8 bytes                                     |
| Local input screen    | Encoded bytes plus 2,048 tokens of allowance, at most 32,000   |
| Completion            | J uses the existing Decisions contract; R at most 4,096 tokens |
| Request deadlines     | J 30 seconds; R 45 seconds                                     |
| Whole run             | 50 minutes                                                     |
| Response / journal    | 256,000 bytes / 32 MiB                                         |
| Retries or resume     | None                                                           |
| Planning allowance    | $8; full-envelope calculation $7.940160                        |

The byte-based input screen is a conservative local estimate with an explicit allowance for provider formatting, not a
provider token count or a proof of the invoice. The manifest records its per-payload estimates. The approved-plan
calculation reserves 32,000 input tokens per Jev question and per reference request: $0.383040 for J and $7.557120 for
R. Using the frozen payload estimates and the full reference output allowance gives $5.667168858, comprising
$0.226860858 for J and $5.440308000 for R. This is a planning estimate, not an expected observed spend. Reported cost
remains authoritative; missing cost, excess tokens or a per-request price-bound violation stops the study. A response
can exceed an estimate before the stop takes effect, and unknown outcomes may still be billed.

The [frozen catalog projection](bounded-catalog-2026-10-18.json) retains the exact selected endpoint and ZDR objects,
retrieval times and hashes of the complete public responses. Unrelated endpoint rows are omitted. Both catalogs agree on
selected route identity, prices and supported parameters. Availability and those stable fields must be refreshed before
dispatch; volatile uptime fields are not model identities.

OpenRouter's [reasoning documentation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) and
Anthropic's
[adaptive-thinking contract](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost) support a
combined thinking-and-visible-output limit. This is documentation evidence, not a successful live trial of this route. A
length finish, empty or invalid answer, or reported token overrun must end the study. Excluding reasoning text does not
remove its billed tokens.

J requires the previously observed dated response identity. R permits only its requested alias or the dated catalog
identity, recording alias-only responses as unresolved snapshot identity. The executor must freeze the first observed
identity per arm and stop on changes; permitted identities cannot be mixed across repetitions. Neither a response name
nor a catalog snapshot proves immutable server weights.

## Review and execution boundary

The manifest expands every sentinel and critical case/question key, local human answer, injection comparison, slot,
deadline and cost bound. The plan's semantic stop remains two non-correct observations on the same sentinel for one arm.
Technical failures stop the entire study. Undispatched slots remain missing; stopped-arm slots cannot be transferred.

The offline validator checks the frozen proposal by rebuilding it from the reviewed ledger, catalog and current
formatter source. The separate `diagnostic_capture.py` runner enforces durable pre-dispatch reservation, no retries or
resume, both stop paths, bounded persistence, isolated `FORGE_HOME`, telemetry joins and exact wire equality. Its source
and helpers are bound in the regenerated manifest. Implementation metadata changes must preserve the approved provider
bodies, slots, scoring and limits; changes to those study inputs require renewed review. The study's quality and runtime
gates stay open.

The 50-minute deadline cancels an in-flight HTTP call and prohibits further dispatch. Small synchronous evidence writes
may finish afterward; their duration is recorded separately. Keeping those writes synchronous prevents a late telemetry
worker from writing into the restored ambient Forge home. A finalization overrun stops the study without relabeling an
already admitted response or silently changing its emitted accounting.

Reproduce and validate locally, with no credentials or network calls:

```bash
uv run python scripts/experiments/jev/diagnostic_manifest.py \
  --review docs/board/doing/jev_rule_pack/evidence/diagnostic-review-2026-10-18-batch-6.json \
  --catalog docs/board/doing/jev_rule_pack/evidence/bounded-catalog-2026-10-18.json \
  > /tmp/jev-bounded-manifest.json
uv run python scripts/experiments/jev/diagnostic_manifest.py \
  --review docs/board/doing/jev_rule_pack/evidence/diagnostic-review-2026-10-18-batch-6.json \
  --catalog docs/board/doing/jev_rule_pack/evidence/bounded-catalog-2026-10-18.json \
  --validate docs/board/doing/jev_rule_pack/evidence/bounded-capture-manifest.json
```
