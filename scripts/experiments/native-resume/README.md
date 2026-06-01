# native-resume experiment

A hands-on reproduction of the **native-relocate** hypothesis (Phase 3 of the `runtime_abstraction` card). It lets a
human refute or confirm the result on their own machine, independent of the pytest contract test
(`tests/integration/docker/test_native_relocate_contract.py`), which shares the same verdict vocabulary so the two are
directly comparable.

## The question

Claude Code stores a conversation at `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`, where `<encoded-cwd>` is the
absolute CWD with `/`, `.`, and `_` replaced by `-` (the underscore mapping is verified against Claude Code 2.1.158).
`claude --resume <uuid>` only looks in the *current* CWD's encoded dir.

The 2026-04-02 negative result (Claude Code 2.1.90 — see
[`src/forge/cli/session_fork.py`](../../../src/forge/cli/session_fork.py) and
[`docs/design.md` §3.9](../../../docs/design.md)) found that cross-CWD `--resume` fails with **"No conversation
found."** But that test never *relocated* the JSONL — it resumed from a foreign CWD while the file stayed put. "No
conversation found" is a **discovery** failure, not a signature/content failure.

**native-relocate** asks: if you first **copy** the parent JSONL into the child CWD's encoded dir, does Claude find it —
and does the tool-use *continuation* survive signed-thinking revalidation?

## Run it

```bash
ANTHROPIC_API_KEY=sk-... bash scripts/experiments/native-resume/reproduce.sh
```

Requirements:

- `ANTHROPIC_API_KEY` in the environment.
- Claude Code **>= 2.1.90** on `PATH` (the version that actually governs the result; the script asserts this).
- Optional: `FORGE_RELOCATE_MODEL` (default `claude-opus-4-6`) and `MAX_THINKING_TOKENS` (default `2048`) to tune the
  parent's signed-thinking turn.

The script runs entirely under an **isolated, disposable `HOME`** (`mktemp -d`, removed on exit), so it never reads or
writes your real `~/.claude` store.

## What it does

1. Pins a thinking-capable model + `MAX_THINKING_TOKENS` so the parent transcript carries a **signed** `thinking` block.
2. **Parent run** in dir A — forces a Read tool call; reports whether the JSONL contains a `signature`.
3. **Control** — resume from dir B *without* relocating (should reproduce "No conversation found").
4. **Experiment** — copy the JSONL into B's encoded dir (computed from `pwd -P` to match `encode_project_path`'s
   symlink-resolved path), then resume from B and force another tool call.
5. Re-hashes the relocated parent JSONL to confirm `--fork-session` did not mutate it.

## Verdicts

| Verdict            | Meaning                                                                 |
| ------------------ | ----------------------------------------------------------------------- |
| `[PASS]`           | Child resumed the relocated JSONL and completed a tool-use turn (signed block present). |
| `[INCONCLUSIVE]`   | Resumed cleanly, but the parent carried no signed thinking block to revalidate.         |
| `[DISCOVERY-FAIL]` | Claude could not find the relocated JSONL ("No conversation found").    |
| `[SIGNATURE-FAIL]` | Found, but the continuation was rejected (signature/thinking).          |
| `[UNCATEGORIZED]`  | Some other non-zero failure — read the child output and tighten triage. |

If the parent transcript carries **no** signature, the run is **inconclusive** for signature validation (it could not
exercise the thing under test), not a negative — adjust the model / `MAX_THINKING_TOKENS` and retry.

## If it passes

A `[PASS]` (with a signed parent block) is evidence the open question in `docs/design.md` §3.9 can be revisited for the
current Claude Code version. The product wiring (`--resume-mode native-relocate`) remains a separate, deferred follow-up
— this experiment and the contract test only settle the *mechanism*.
