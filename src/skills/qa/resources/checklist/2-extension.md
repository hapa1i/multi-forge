<!-- prereq: 0.3, 1.1 -->

## 2. Runtime Extensions (`forge extension`)

### 2.1 Basic Installation (User Scope)

<!-- auto -->

```bash
# Install Forge extensions (full profile is required for the QA skill itself)
cd $FORGE_TEST_REPO
forge extension enable --scope user --symlink --profile full --runtime claude

# Optional: preview changes instead of applying
forge extension enable --scope user --dry-run

# Verify installation
ls -la $CLAUDE_HOME/skills/
cat $CLAUDE_HOME/settings.json | jq '.hooks'
cat $FORGE_HOME/installed.json | jq '.installations.user.modules_enabled'

# Confirm statusLine is not user-scoped; runtime hooks and permissions are
cat $CLAUDE_HOME/settings.json | jq '.statusLine'
cat $CLAUDE_HOME/settings.json | jq '.permissions'
```

- [ ] `modules_enabled` in `installed.json` lists `commands` and `agents` (directories created only if source has
  installable files)
- [ ] All eleven full-profile Claude skills are installed to `$CLAUDE_HOME/skills/`
- [ ] Runtime hooks configured in `$CLAUDE_HOME/settings.json`
- [ ] `statusLine` is absent from user scope
- [ ] `$FORGE_HOME/installed.json` tracking file created

### 2.2 Verify Installed Content

<!-- auto -->

```bash
# Check what was installed
cat $FORGE_HOME/installed.json | jq '.'

# Verify statusLine is not user-scoped
cat $CLAUDE_HOME/settings.json | jq '.statusLine'

# Verify user-scope permissions
cat $CLAUDE_HOME/settings.json | jq '.permissions'

# Verify skills are installed
ls $CLAUDE_HOME/skills/
```

- [ ] `installed.json` lists all installed files
- [ ] `statusLine` is absent at user scope
- [ ] Permissions include Forge-required entries
- [ ] Skills directory contains skill folders (analyze, debate, panel, review, review-docs, etc.)

### 2.3 Verify Pre-Existing Settings Preserved

<!-- auto -->

```bash
# Check that user's original settings survived installation
cat .claude/settings.local.json | jq '.'

# Verify original permissions still present (merged, not replaced)
cat .claude/settings.local.json | jq '.permissions.allow'
# Should include BOTH:
# - Original: "Bash(npm test)", "Bash(uv run pytest*)"
# - Forge-added permissions (if any added to local scope)

# Verify custom env var preserved
cat .claude/settings.local.json | jq '.env.MY_CUSTOM_VAR'
# Should show: "should-survive-forge"
```

- [ ] Original `permissions.allow` entries preserved
- [ ] `env.MY_CUSTOM_VAR` still present
- [ ] Forge merged settings, didn't replace

### 2.4 Install Local Scope

<!-- auto -->

```bash
# Install Forge extensions to LOCAL scope (this project only)
cd $FORGE_TEST_REPO
forge extension enable --scope local --runtime claude

# Verify local installation: statusLine yes, runtime hooks no
cat .claude/settings.local.json | jq '.statusLine'
cat .claude/settings.local.json | jq '.hooks'
LOCAL_KEY="local:$(cd "$FORGE_TEST_REPO" && pwd -P)"
cat $FORGE_HOME/installed.json | jq --arg key "$LOCAL_KEY" '.installations[$key].modules_enabled'
```

- [ ] `modules_enabled` for local installation lists `commands` and `agents` (directories created only if source has
  installable files)
- [ ] `statusLine` configured in `.claude/settings.local.json`
- [ ] Runtime hooks are absent from `.claude/settings.local.json`

### 2.5 Verify Both Installations Tracked

<!-- auto -->

```bash
# Check tracking file shows BOTH installations
LOCAL_KEY="local:$(cd "$FORGE_TEST_REPO" && pwd -P)"
cat $FORGE_HOME/installed.json | jq '.installations | keys'
printf 'Expected local key: %s\n' "$LOCAL_KEY"

# Show user installation
cat $FORGE_HOME/installed.json | jq '.installations.user.scope'
# Should show: "user"

# Show local installation (note the key format with path)
cat $FORGE_HOME/installed.json | jq --arg key "$LOCAL_KEY" '.installations[$key].scope'
# Should show: "local"

# Verify project_path is tracked
cat $FORGE_HOME/installed.json | jq --arg key "$LOCAL_KEY" '.installations[$key].project_path'
# Should show the resolved path part of LOCAL_KEY
```

- [ ] Tracking shows "user" key
- [ ] Tracking shows "local:/path/to/project" key
- [ ] Both installations tracked separately
- [ ] project_path field populated for local installation

### 2.6 Test Double-Install Prevention

<!-- auto -->

```bash
# Try to install local again to same project
forge extension enable --scope local --runtime claude

# Should either:
# - Say "already installed" and skip
# - Or update existing installation (idempotent)

# Verify only ONE local entry in tracking
cat $FORGE_HOME/installed.json | jq '.installations | keys | length'
# Should show 2 (user + 1 local), not 3
```

- [ ] Re-running `forge extension enable --scope local` is idempotent
- [ ] No duplicate entries in tracking

### 2.7 Check Install Status (Nearest Scope)

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Status for the nearest installation (auto-detects local/project/user)
forge extension status
```

- [ ] `forge extension status` succeeds
- [ ] Shows detected scope + profile/modules summary

### 2.8 Check Install Status (All Scopes)

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Show user + project + local scopes
forge extension status --all
```

- [ ] Shows all three scopes (user/project/local)
- [ ] Missing scopes are shown as "Not installed" (does not error)

### 2.9 Update Installation (Idempotent)

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Update the nearest installation (auto-detects)
forge extension sync
```

- [ ] Update completes (or reports already up to date)

### 2.10 Codex Hook Registration (codex-hooks module)

<!-- auto -->

```bash
# Enable with a fake codex binary on PATH + isolated CODEX_HOME
export CODEX_HOME=$(mktemp -d)
FAKE_BIN=$(mktemp -d) && printf '#!/bin/sh\nexit 0\n' > "$FAKE_BIN/codex" && chmod +x "$FAKE_BIN/codex"
PATH="$FAKE_BIN:$PATH" forge extension enable --scope user --runtime claude --force

cat "$CODEX_HOME/config.toml"
forge extension status --scope user

# Disable removes the managed block (file deleted when Forge created it)
PATH="$FAKE_BIN:$PATH" forge extension disable --scope user --yes
test ! -f "$CODEX_HOME/config.toml" && echo "BLOCK-REMOVED"
```

- [ ] Enable output shows a "Codex hooks (config.toml)" plan section and "Next steps (Codex hooks):" trust-ceremony
  guidance
- [ ] `$CODEX_HOME/config.toml` contains the `# >>> forge hooks >>>` block with `forge-hook codex-session-start` and
  `forge-hook codex-policy-check`
- [ ] `forge extension status` shows a `Codex:` line with the config path
- [ ] After disable, `BLOCK-REMOVED` is printed (Forge-created file removed)

### 2.11 Codex Hooks Skipped Without Binary

<!-- auto -->

```bash
# Re-enable with codex absent from PATH while keeping the installed Claude binary visible.
export CODEX_HOME=$(mktemp -d)
PATH="$HOME/.local/bin:/usr/bin:/bin" forge extension enable --scope user --runtime claude --force
test ! -f "$CODEX_HOME/config.toml" && echo "NO-CONFIG-WRITTEN"

# Restore: re-enable normally and clear the env override
forge extension enable --scope user --runtime claude --force
unset CODEX_HOME
```

- [ ] Enable prints "Codex hooks skipped: codex binary not found on PATH"
- [ ] `NO-CONFIG-WRITTEN` is printed (no Codex config created)

### 2.12 Migrate a Pre-User-Scope Hook Fixture

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Seed one exact pre-T5 direct hook beside the current local project settings.
tmp=$(mktemp)
jq '.hooks.SessionStart = ((.hooks.SessionStart // []) + [{"hooks":[{"type":"command","command":"forge hook session-start"}]}])' \
  .claude/settings.local.json > "$tmp" && mv "$tmp" .claude/settings.local.json

forge extension doctor --json | jq -e '.runtime_hooks.cleanup_required == true'
BEFORE=$(shasum -a 256 .claude/settings.local.json | cut -d' ' -f1)
forge extension cleanup-project --root "$FORGE_TEST_REPO" | tee /tmp/forge-hook-migration-preview.txt
AFTER=$(shasum -a 256 .claude/settings.local.json | cut -d' ' -f1)
test "$BEFORE" = "$AFTER" && echo "PREVIEW-UNCHANGED"

forge extension cleanup-project --root "$FORGE_TEST_REPO" --yes
! rg -q '"command": "forge hook ' .claude/settings.local.json
rg -q 'forge-hook session-start' "$CLAUDE_HOME/settings.json"
forge extension doctor --json \
  | jq -e '.runtime_hooks.cleanup_required == false and .runtime_hooks.double_fire_risk == false'
find .claude -name '.settings.local.json.forge.backup.*' -print -quit | grep -q .
```

- [ ] Doctor detects the seeded cleanup state, and preview prints `PREVIEW-UNCHANGED`
- [ ] Preview identifies the selected settings path and a known-legacy removal
- [ ] Apply removes the direct project hook while leaving the user dispatcher registration present
- [ ] Doctor reports neither cleanup-required nor double-fire after migration
- [ ] A project settings backup exists

### 2.13 Runtime-Aware Skill Packages

<!-- prereq: 2.1, 2.4 -->

<!-- auto -->

Exercise the Codex user target only here, inside Docker's isolated `$HOME`. Then restore the user installation to
Claude-only and keep the Codex project target for later status, disable, and uninstall checks.

```bash
cd "$FORGE_TEST_REPO"

# Make Codex selectable without depending on a real Codex binary in the QA image.
QA_RUNTIME_BIN=/tmp/forge-qa-runtime-bin
mkdir -p "$QA_RUNTIME_BIN"
printf '#!/bin/sh\nexit 0\n' > "$QA_RUNTIME_BIN/codex"
chmod +x "$QA_RUNTIME_BIN/codex"

# User target: Docker QA is the only manual flow allowed to touch $HOME/.agents.
PATH="$QA_RUNTIME_BIN:$PATH" forge extension enable --scope user --symlink --profile full --runtime all --force
printf '%s\n' challenge review review-docs smoke-test understand > /tmp/forge-portable-skills.expected
find "$HOME/.agents/skills" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort \
  | diff -u /tmp/forge-portable-skills.expected -
jq -e '([.installations.user.skill_packages[] | select(.runtime == "claude_code")] | length == 11)
  and ([.installations.user.skill_packages[] | select(.runtime == "codex")] | length == 5)' \
  "$FORGE_HOME/installed.json"

# Automatic re-enable retains tracked Codex packages when Codex is temporarily absent.
USER_SKILLS_BEFORE=$(jq -c \
  '[.installations.user.skill_packages[] | [.runtime, .skill]] | sort' "$FORGE_HOME/installed.json")
QA_CLAUDE_ONLY_BIN=/tmp/forge-qa-claude-only-bin
mkdir -p "$QA_CLAUDE_ONLY_BIN"
printf '#!/bin/sh\nprintf "%%s\\n" "2.1.78 (Claude Code)"\n' > "$QA_CLAUDE_ONLY_BIN/claude"
chmod +x "$QA_CLAUDE_ONLY_BIN/claude"
PATH="$QA_CLAUDE_ONLY_BIN:/usr/bin:/bin" command -v claude >/dev/null
! PATH="$QA_CLAUDE_ONLY_BIN:/usr/bin:/bin" command -v codex >/dev/null 2>&1
PATH="$QA_CLAUDE_ONLY_BIN:/usr/bin:/bin" "$HOME/.local/bin/forge" extension enable \
  --scope user --symlink --profile full --force
USER_SKILLS_AFTER_AUTO=$(jq -c \
  '[.installations.user.skill_packages[] | [.runtime, .skill]] | sort' "$FORGE_HOME/installed.json")
test "$USER_SKILLS_AFTER_AUTO" = "$USER_SKILLS_BEFORE"
find "$HOME/.agents/skills" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort \
  | diff -u /tmp/forge-portable-skills.expected -

# Explicit runtime narrowing reports preservation and also leaves omitted tracked packages owned.
PATH="$QA_CLAUDE_ONLY_BIN:/usr/bin:/bin" "$HOME/.local/bin/forge" extension enable \
  --scope user --symlink --profile full --runtime claude --force \
  | tee /tmp/forge-explicit-runtime-preservation.txt
rg -q 'managed_runtime_preservation' /tmp/forge-explicit-runtime-preservation.txt
USER_SKILLS_AFTER_EXPLICIT=$(jq -c \
  '[.installations.user.skill_packages[] | [.runtime, .skill]] | sort' "$FORGE_HOME/installed.json")
test "$USER_SKILLS_AFTER_EXPLICIT" = "$USER_SKILLS_BEFORE"
find "$HOME/.agents/skills" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort \
  | diff -u /tmp/forge-portable-skills.expected -

# Remove the user Codex target and restore the Claude user installation used by later sections.
forge extension disable --scope user --yes
! find "$HOME/.agents/skills" -name SKILL.md -print -quit 2>/dev/null | grep -q .
forge extension enable --scope user --symlink --profile full --runtime claude
jq -e '(.installations.user.skill_packages | length == 11)
  and all(.installations.user.skill_packages[]; .runtime == "claude_code")' \
  "$FORGE_HOME/installed.json"

# Project target: portable Codex skills live in the repository, never under CODEX_HOME.
PATH="$QA_RUNTIME_BIN:$PATH" forge extension enable --scope project --root "$FORGE_TEST_REPO" \
  --profile minimal --with skills --without commands --runtime codex
find .agents/skills -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort \
  | diff -u /tmp/forge-portable-skills.expected -
test ! -d "${CODEX_HOME:-$HOME/.codex}/skills"

# An explicit Codex local/private request must fail and leave the existing local Claude runtime set unchanged.
LOCAL_KEY="local:$(pwd -P)"
LOCAL_BEFORE=$(jq -c --arg key "$LOCAL_KEY" \
  '[.installations[$key].skill_packages[].runtime] | unique' "$FORGE_HOME/installed.json")
if PATH="$QA_RUNTIME_BIN:$PATH" forge extension enable --scope local --runtime codex --force \
  >/tmp/forge-codex-local.txt 2>&1; then
  echo "ERROR: Codex local scope unexpectedly succeeded" >&2
  exit 1
fi
rg -q 'scope_unsupported' /tmp/forge-codex-local.txt
LOCAL_AFTER=$(jq -c --arg key "$LOCAL_KEY" \
  '[.installations[$key].skill_packages[].runtime] | unique' "$FORGE_HOME/installed.json")
test "$LOCAL_BEFORE" = '["claude_code"]' && test "$LOCAL_AFTER" = "$LOCAL_BEFORE"

# A user package would be visible inside every project. Refuse it even when the tracked project package is outside CWD.
if (cd "$HOME" && PATH="$QA_RUNTIME_BIN:$PATH" forge extension enable --scope user \
  --profile minimal --with skills --without commands --runtime codex \
  >/tmp/forge-codex-cross-scope.txt 2>&1); then
  echo "ERROR: user Codex package unexpectedly bypassed tracked project package" >&2
  exit 1
fi
rg -q 'forge_managed_scope_duplicate' /tmp/forge-codex-cross-scope.txt
! find "$HOME/.agents/skills" -name SKILL.md -print -quit 2>/dev/null | grep -q .

# Runtime selection is persisted: sync still owns Codex with a PATH that cannot find the fake binary.
PATH="/usr/bin:/bin" "$HOME/.local/bin/forge" extension sync --scope project
jq -e --arg root "$(pwd -P)" \
  '[.installations["project:" + $root].skill_packages[] | select(.runtime == "codex")] | length == 5' \
  "$FORGE_HOME/installed.json"

# A same-name user package is never overwritten, even with --force.
mkdir -p "$HOME/.agents/skills/challenge"
printf 'user-owned duplicate\n' > "$HOME/.agents/skills/challenge/SKILL.md"
DUPLICATE_BEFORE=$(shasum -a 256 "$HOME/.agents/skills/challenge/SKILL.md" | cut -d' ' -f1)
forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  | jq -e '.[0].skill_packages[] | select(.skill == "challenge")
    | .state == "duplicate" and (.duplicate_dirs | length == 1) and (.recovery | contains("Remove or rename"))'
if PATH="$QA_RUNTIME_BIN:$PATH" forge extension enable --scope project --root "$FORGE_TEST_REPO" \
  --profile minimal --with skills --without commands --runtime codex --force \
  >/tmp/forge-codex-duplicate.txt 2>&1; then
  echo "ERROR: explicit duplicate unexpectedly succeeded" >&2
  exit 1
fi
rg -q 'duplicate_scan_chain' /tmp/forge-codex-duplicate.txt
DUPLICATE_AFTER=$(shasum -a 256 "$HOME/.agents/skills/challenge/SKILL.md" | cut -d' ' -f1)
test "$DUPLICATE_BEFORE" = "$DUPLICATE_AFTER"

rm -rf "$HOME/.agents/skills/challenge"
forge extension sync --scope project

# Replacing a tracked package root with a symlink must invalidate it, not redirect disable into the sibling.
mv .agents/skills/review .agents/skills/review-sibling
ln -s review-sibling .agents/skills/review
forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  | jq -e '.[0].skill_packages[] | select(.skill == "review")
    | .state == "invalid-target" and .target_present == false
      and (.recovery | contains("unexpected package entry"))'
if forge extension disable --scope project --yes >/tmp/forge-codex-package-symlink.txt 2>&1; then
  echo "ERROR: disable followed a substituted Codex package directory" >&2
  exit 1
fi
rg -q 'security violation' /tmp/forge-codex-package-symlink.txt
test -f .agents/skills/review-sibling/SKILL.md
jq -e --arg root "$(pwd -P)" '.installations["project:" + $root] != null' "$FORGE_HOME/installed.json"
rm .agents/skills/review
mv .agents/skills/review-sibling .agents/skills/review
forge extension sync --scope project

forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  | jq -e '.[0].skill_packages | length == 5 and all(.[];
      .runtime == "codex" and .state == "present" and .target_present == true
      and .missing_file_paths == [] and .duplicate_dirs == [] and .recovery == null)'
```

- [ ] Full-profile user `all` tracks eleven Claude packages and exactly the five portable Codex packages
- [ ] Automatic re-enable retains all managed runtime packages when Codex is temporarily absent from `PATH`
- [ ] Explicit Claude re-enable reports runtime preservation and does not remove tracked Codex packages
- [ ] Disabling the user install removes its Codex packages; the restored user install tracks Claude packages only
- [ ] Project Codex target contains exactly the five portable skills under `.agents/skills`, not `CODEX_HOME`
- [ ] Explicit Codex local scope fails with `scope_unsupported` and leaves the local Claude package set unchanged
- [ ] User-scope Codex enable refuses tracked project packages outside its CWD and creates no global package
- [ ] Project sync preserves the recorded Codex runtime set when Codex is temporarily absent from `PATH`
- [ ] JSON status reports the injected same-name package as `duplicate` with its path and recovery guidance
- [ ] Explicit enable refuses the duplicate even with `--force`, and its checksum remains unchanged
- [ ] A substituted package-root symlink is `invalid-target`; disable preserves its sibling and tracking row
- [ ] After duplicate cleanup and sync, all five project Codex packages report healthy `present` state

---
