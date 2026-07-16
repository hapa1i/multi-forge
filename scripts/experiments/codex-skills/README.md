# Codex skills probe

This harness pins the Codex facts used by the `cross_runtime_skills` installer and compiler. Documentation is a lead;
the installed binary is the authority. The current research pin is **codex-cli 0.144.5** (2026-07-16).

## Questions and stages

| Stage                    | Question                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------- |
| `00-preflight`           | Is the expected Codex CLI available and can an isolated `CODEX_HOME` reuse copied auth?               |
| `10-user-discovery`      | Does `$HOME/.agents/skills` discover and explicitly invoke a skill?                                   |
| `20-project-discovery`   | Does a nested CWD discover `.agents/skills` on the path to the repository root?                       |
| `30-duplicate-discovery` | What happens when the same name exists at user and project discovery levels?                          |
| `40-invocation-policy`   | Does `allow_implicit_invocation: false` block implicit use while preserving `$skill`?                 |
| `50-script-resolution`   | Is a packaged script anchored to the skill root or process CWD, and is a skill-root variable exposed? |
| `60-symlink-reload`      | Are symlinked packages discovered and re-read on a new headless invocation?                           |

## Run

```bash
./reproduce.sh             # all stages
./reproduce.sh 00 50       # selected stages
```

Each model turn uses a short oracle prompt. Captures land outside the repository at
`${CODEX_SKILLS_CAPTURE_DIR:-~/.cache/forge-codex-skills-probe}`. Raw JSONL, stderr, and last messages stay there; only
reviewed, secret-free verdict summaries belong under `verdicts/`.

## Safety

- Every stage creates a disposable `HOME`, `CODEX_HOME`, and git project. User skills never touch the real
  `$HOME/.agents/skills`.
- The real Codex auth file is copied mode `0600` into the disposable home and deleted with that home. The harness never
  prints or commits it.
- Turns use `--ignore-user-config`, `--ephemeral`, and `--sandbox read-only`. Stage setup writes only inside the
  disposable tree and the external capture directory.
- Do not commit raw captures. Before promoting a verdict, inspect it for paths, usernames, tokens, and auth material.

## Verdict vocabulary

- Discovery stages: `PASS` only when the hidden marker from the selected skill reaches the last message.
- Duplicate discovery records `USER`, `PROJECT`, `AMBIGUOUS`, or `INCONCLUSIVE`; it is evidence for Forge's own
  duplicate policy, not permission to delete either package.
- Invocation policy: both the implicit block and explicit success must hold.
- Script resolution: the literal relative command must demonstrate CWD anchoring, and the skill-root instruction must
  execute the installed package's marker. Environment inspection separately records whether a `*SKILL*` variable exists.
- Symlink/reload: a fresh invocation must observe both the original and updated marker through the same symlink.
