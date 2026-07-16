# Codex skills probe verdict -- codex-cli 0.144.5 -- 2026-07-16

Environment: macOS host, isolated temporary `HOME`, real authenticated `CODEX_HOME`, unrelated temporary repository CWD,
read-only sandbox, ephemeral `codex exec`.

## Discovery, duplicates, and invocation

- `$HOME/.agents/skills` discovered an explicitly invoked user skill.
- A nested CWD discovered a repository-root `.agents/skills` package.
- With the same skill name at user and project levels, explicit invocation selected the project package on this version.
  Forge still treats this as a duplicate scan-chain condition rather than relying on undocumented precedence silently.
- `agents/openai.yaml` with `policy.allow_implicit_invocation: false` prevented the hidden implicit oracle from loading;
  explicit `$skill` invocation still loaded it.

## Packaged script/root resolution

- Codex discovered `$HOME/.agents/skills/probe-skill` and loaded its `SKILL.md` by absolute path.
- A literal `bash scripts/marker.sh` ran from the repository CWD and failed with exit 127 because that relative path did
  not exist there.
- No environment variable with `SKILL` in its name was present.
- When the skill instructed Codex to resolve `scripts/marker.sh` relative to the loaded `SKILL.md` parent and execute
  the resolved absolute path, Codex ran the installed package's script and returned the expected marker.
- A read-only `resources/marker.md` reference resolved successfully when the skill explicitly anchored it to the loaded
  `SKILL.md` parent.

Decision: the Codex adapter must emit an explicit `SKILL.md`-parent resolution instruction for packaged executables.
Read-only resource references and executable invocation remain separate capabilities.

## Symlink and reload

- A package-directory symlink under `$HOME/.agents/skills` was discovered.
- After changing the symlink target's `SKILL.md`, a fresh `codex exec` invocation observed the updated marker.

Decision: a stable Forge-managed compiled-package cache is a valid symlink source; transient build directories are not.

Raw captures were intentionally not committed. Reproduce with `./reproduce.sh` and inspect the external capture
directory. All seven stages passed in the recorded run.
