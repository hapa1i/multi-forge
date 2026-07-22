# Unmanaged Skill Packages: Detection and Cleanup

**Lane**: `doing/`

**Origin**: 2026-07-19 stale-Codex-skill incident. A pre-merge test run on the cross-runtime-skills branch leaked five
pre-fix compiled packages into the real `$HOME/.agents/skills` (the HOME-isolation gap later closed by
`tests/conftest.py::isolate_home` in `d2a94bf7`). Tracking for that run went to an isolated `FORGE_HOME` and was
discarded, so the packages were untracked. No Forge surface reported them for two days while Codex loaded the stale
`understand` package (dynamic model-family lookup resolving `anthropic` instead of the fixed static `openai`). Diagnosis
required manual mtime/tracking forensics; remediation was manual removal plus re-enable.

## Problem

Runtime skill targets are discovery surfaces that runtimes read directly. Forge currently reports only packages claimed
by valid `installed.json` tracking rows. A package entry in a runtime target that no row owns can therefore be:

- invisible to `forge extension status`, because the existing package states (`present`, `missing`, `duplicate`, and
  `invalid-target`) are projections of tracking rows
- invisible to `forge extension doctor`, which intentionally does not own runtime-package health
- outside `forge clean`, whose detectors do not inspect runtime skill targets
- loaded by a runtime while blocking a fresh install of the same name, because duplicate safety correctly refuses to
  overwrite a path that Forge cannot prove it owns

The incident is one instance of a wider partial-write boundary: a failed first enable can leave compiled output on disk
before tracking commits. Duplicate safety must remain fail-closed, but Forge needs a read surface for those entries and
a deletion path only when Forge provenance and the absence of user content are both provable.

## Decisions

1. Detect unmanaged entries independently of tracked-package health. Do **not** add `unmanaged` to
   `SkillPackageStatus.state`; that type continues to describe one tracked package.
2. Classify ownership and collision separately. An entry can be unmanaged and also collide with the same skill in
   another visible root.
3. Add a deterministic `.forge-package.json` sentinel to every newly compiled runtime package. Install the sentinel as a
   regular copied file in both copy and symlink modes so provenance survives loss of the compiled cache.
4. Report unmarked, malformed-marker, newer-marker, modified, and unsafe-path entries, but never offer them to
   `forge clean`. This includes pre-marker packages from the motivating incident. A marked package whose only missing
   payload is structurally proven, cache-contained dangling symlinks after a Forge-home reset remains cleanup-eligible.
5. Keep duplicate installation behavior unchanged: no adoption, overwrite, implicit tracking repair, or automatic
   removal. Change its recovery rendering: a provable Forge orphan names the matching `forge clean` preview/apply and
   retry sequence, while an unknown or modified package retains remove-or-rename guidance.

## Terms and path model

### Forge-writable targets

These are the only roots in which this feature may classify an entry as cleanup-eligible:

| Runtime | Install scope    | Writable target         |
| ------- | ---------------- | ----------------------- |
| Claude  | user             | `$CLAUDE_HOME/skills`   |
| Claude  | project or local | `<root>/.claude/skills` |
| Codex   | user             | `$HOME/.agents/skills`  |
| Codex   | project          | `<root>/.agents/skills` |

Codex local scope remains unsupported and must not be mapped onto the shared project target.

The scanner also reuses Codex's existing visibility roots for collision reporting: applicable ancestor `.agents/skills`
directories and `/etc/codex/skills`. An ancestor that is not the selected Forge root and the admin root are
`visibility-only`: they can explain a collision but are never cleanup candidates. This card does not introduce a
filesystem-wide search.

### Identity and classification

- A **managed** entry is an exact canonical target claimed by a coherent schema-v2 `skill_packages` row and its file
  ledger. Canonicalization resolves parent components while preserving the final path entry, matching existing runtime
  skill planning.
- An **unmanaged** entry is an observed direct child of a scanned target for which no valid row in any scope claims that
  exact target.
- A **collision** exists when the same runtime/skill name is present in another runtime-visible root. Collision is an
  observation, not an ownership state.
- An **observed entry** is a direct child whose name is in Forge's skill-name universe or whose real directory contains
  `.forge-package.json`. Name matching includes files, root symlinks, and partial directories so that blockers without a
  usable `SKILL.md` remain visible. Such unsafe shapes are always report-only.

The skill-name universe is the union of current shipped/locally compilable skill names and an append-only
`FORGE_SKILL_NAME_HISTORY`. The history is initialized with all names shipped before this feature and retains renamed or
retired names. A test pins the immutable pre-feature baseline as a required subset of history, while a separate test
requires every current candidate name to be represented by the union. A valid sentinel is reported regardless of whether
its name remains in the registry; an unknown unmarked name is treated as user content and ignored.

## Provenance sentinel

The compiler writes canonical UTF-8 JSON at `<package>/.forge-package.json`:

```json
{
  "schema_version": 1,
  "producer": "multi-forge",
  "runtime": "codex",
  "skill": "understand",
  "files": [
    {
      "path": "SKILL.md",
      "sha256": "<lowercase hex digest>",
      "mode": 420
    }
  ]
}
```

The `files` array is sorted by relative POSIX path and covers every emitted leaf file other than the sentinel itself;
parent directories are implied by those paths. Paths must be normalized, relative, unique, nonempty, and free of `.` or
`..` components. Each row records the compiled file's SHA-256 digest and permission bits. The payload contains no
timestamps, absolute paths, cache locations, Forge version, or source paths, so equal compiler output remains
reproducible. Unknown fields, invalid shapes, and schema versions newer than the reader are report-only rather than
guessed.

The sentinel is itself an emitted file: it participates in the compiled-cache digest, install file ledger, tracking
checksum, sync, and disable. It is excluded only from its own `files` array to avoid a self-hash. At the installed
target the sentinel is always copied as a regular file, even when payload files use symlink mode; the file ledger
records that per-file mode honestly. This exception keeps provenance readable after the compiled cache is reset. Both
Claude and Codex package validation must be exercised with the extra hidden file. Existing cache digests changing once
is an intentional clean break and must be called out in the changelog.

The marker is local provenance, not authentication against another process running as the same user. Cleanup proof
requires all of the following at scan time and again immediately before deletion:

1. The sentinel is a regular file that parses strictly, has a supported schema, names the expected runtime and final
   directory name, and has `producer: multi-forge`.
2. The observed tree has exactly the leaf entries listed by the sentinel plus the sentinel itself and only their implied
   parent directories; no unlisted files or directories are present.
3. Every regular payload file has the recorded bytes and permission bits. A live symlink leaf is accepted only when its
   target is a regular file inside the current Forge compiled-skill cache and its resolved content and mode match the
   manifest. A dangling symlink is accepted for cleanup only when its target is lexically inside that cache namespace,
   stripping each manifest-relative suffix reconstructs one common package-cache directory for every symlink leaf, and
   the sentinel plus exact tree prove that no unlisted entry exists. This narrow reset case proves safe removal without
   pretending the missing bytes were verified. A dangling or live link outside the cache is report-only.
4. The writable target root, package root, and descendant directories are real directories rather than symlinks, and the
   final package path remains the exact direct child of the expected runtime root.
5. No coherent tracking row claims the exact path.

Any mismatch sets `cleanup_eligible: false` and supplies a concrete reason. It does not downgrade the entry to
user-owned or make a best-effort subset deletable.

## Detection operation and status contract

Add one UI-agnostic install/core operation shared by installer planning, status, and GC. It reads tracking once, derives
exact managed paths from validated rows, scans only the selected roots' direct children with `lstat`-first path checks,
and returns immutable records. Each unmanaged record has a fixed structured shape:

```text
runtime
skill
target_dir
target_scopes            # sorted install scopes mapping to this root; empty for visibility-only roots
root_kind                # forge-writable | visibility-only
shape                    # complete | partial | invalid-target
provenance               # marked | unmarked | invalid-marker | unsupported-marker | modified
collision_dirs
cleanup_eligible
cleanup_reason
cleanup_scope            # project | all | null
recovery                 # string | null
```

`target_scopes` is an array because Claude project and local installs share one physical target; the scanner must not
invent which scope produced an untracked path. `complete` means a real package directory with a usable `SKILL.md`,
`partial` means the expected package entry is incomplete (including a reset package whose payload links now dangle), and
`invalid-target` covers blocking files and unsafe path types. `collision_dirs` is sorted and excludes the record's own
path. `cleanup_scope` names the narrowest clean scope that can mutate the target (`all` for a user target); it is `null`
when cleanup is not safe. `recovery` is a rendered human string or `null`; it names the exact path and distinguishes a
safe `forge clean` candidate from a report-only remove-or-rename decision. Machine-readable cleanup state remains in
`cleanup_eligible`, `cleanup_reason`, and `cleanup_scope`. Human rendering uses the same records.

Tracking failure is a no-scan boundary. A missing manifest means there are no managed rows, but a corrupt, unsupported,
or unreadable manifest must propagate the existing state error; it must never be treated as empty tracking. This matches
GC's existing fail-closed behavior when durable references cannot be built.

### Enable and sync recovery

Installer planning consumes the same unmanaged records before reducing a runtime package to a conflict or automatic
skip. Every selected package blocked or skipped by an untracked same-name entry carries a per-package recovery string
through the `SkillPackagePlan` and human conflict renderer:

- For a marked orphan with `cleanup_eligible: true`, name the exact path, preview command, apply command, and retry:
  user targets use `forge clean --scope all --verbose`; project targets use
  `cd <root> && forge clean --scope project --verbose`. Applying adds `--yes`, and the user then reruns the original
  `forge extension enable` or `sync` command.
- For an unmarked, modified, malformed, unsupported-marker, visibility-only, or unsafe entry, name the exact path and
  retain remove-or-rename guidance. Never suggest `forge clean` for a record that its current scope would not list.

The recovery improvement does not weaken the no-write boundary and does not make `--force` adopt or overwrite a package.
Multiple conflicts retain per-package recovery so mixed safe and unknown entries are not collapsed into one misleading
global tip.

`forge extension status` shows a separate **Unmanaged runtime skill packages** section even when the selected scope has
no installation row. Existing tracked packages retain their four current states. The read-only status scan follows these
boundaries:

- `--scope user` scans the two fixed user targets.
- `--scope project|local [--root ...]` scans that resolved root's supported writable targets. Codex's other visible
  roots contribute collision evidence only.
- `--all` scans user plus supported project/local targets for the effective current root, matching status's current
  meaning; it does not enumerate every project recorded on the machine.
- Auto-detection scans whichever status scopes it would display. If no project root can be resolved, only fixed user
  targets are available.

The current JSON top level is a bare installation array and therefore cannot represent an unmanaged-only scope without
inventing a fake installation. This card intentionally replaces it with a documented versioned object:

```json
{
  "schema_version": 2,
  "installations": [],
  "unmanaged_skill_packages": []
}
```

`installations` retains the existing installation-record shape and `skill_packages` fields. The unmanaged array always
exists and uses the fixed record shape above; absent values are JSON `null`, not omitted fields. This research-preview
clean break requires CLI reference, changelog, and contract-test updates. Diagnostics and recovery remain on stderr; the
JSON document remains the only stdout content.

`forge extension doctor` remains unchanged: runtime-package health stays owned by `extension status`.

## Cleanup contract

Add `unmanaged_skill_packages` to `OrphanCategory`. The category contains only entries that passed the sentinel,
content-or-reset-link, path, ownership, and scope checks; report-only observations remain exclusive to
`extension status`. The existing `forge clean --yes` behavior is report-wide: it removes eligible items from every
category in the preview, and there is no per-path selector within `unmanaged_skill_packages`. `forge clean --verbose`
prints exact paths, JSON uses the existing category shape, and `%clean` inherits the same read-only report.

Cleanup scope is based on the roots already resolved by GC:

| `forge clean --scope` | Runtime skill targets scanned                                                                 |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `project`             | Claude and Codex project/local targets for the current `ctx.forge_root`; never user targets   |
| `workspace`           | Project/local targets for GC-known roots in the current logical workspace; never user targets |
| `all`                 | Project/local targets for every GC-known root, plus both fixed user targets                   |

Missing target roots are skipped. Project and local scopes may map to the same physical runtime root; paths are
canonicalized and deduplicated before counting. User targets are global even though they may shadow every project, so
they mutate only under `--scope all`.

The new category is project-owned for project/local paths and global for user paths. `_project_owner` must handle it
explicitly, so existing project compatibility checks can refuse project-owned deletion while global entries remain
independent. Matching current GC behavior, a compatibility refusal remains in the preview category/count, is also
rendered through `skipped_project_compatibility`, and is excluded from apply.

`run_clean` must perform a fresh scan rather than trust the preliminary CLI report. A candidate that becomes managed
before that scan is omitted from apply and left untouched without an apply failure. Each candidate returned by the fresh
scan is revalidated immediately before removal. Any ownership, marker, contents, path type, containment, or
compatibility drift after the scan records a failure, leaves the entry untouched, and produces a nonzero apply result
through the existing `CleanResult` contract. It removes only the exact validated package directory; directory traversal
never follows symlinked roots or subdirectories.

### Tracking-reset recovery

The durable-state recovery guidance already allows deleting a corrupt `installed.json` or performing a full global
Forge-home reset. Once tracking is absent, every otherwise-unmodified post-marker package in a scanned writable target
is correctly unowned Forge output. Forge does not adopt it; the sanctioned order is cleanup, then fresh enable:

1. Finish the tracking repair/reset first. A corrupt or unreadable manifest remains a no-scan boundary. If
   `forge clean --yes` removes a corrupt `installed.json`, invoke clean again to detect the packages that have now
   become unclaimed.
2. Preview the affected roots. Use `forge clean --scope all --verbose` for fixed user targets and every project root GC
   can still resolve; from any additional affected project, use `cd <root> && forge clean --scope project --verbose`.
3. Review the entire clean report, then repeat the chosen command with `--yes`. Apply processes every eligible category
   in that report, while all package entries in `unmanaged_skill_packages` form one batch with no per-path selector. Use
   the narrower project scope or manual remove/rename if the complete report should not be applied.
4. Re-run `forge extension enable` with the intended scope, profile, mode, and runtime selection for each installation
   being recreated. Lost tracking cannot reconstruct those choices.

Deleting only `installed.json` preserves the compiled cache and any roots still known through other GC state. A full
`$FORGE_HOME` reset also deletes the compiled cache and global root indexes. The always-copied sentinel plus the narrow
cache-contained dangling-link rule keeps symlink-mode packages in fixed user and currently visited project targets
cleanable when Forge is recreated at the same home path. A changed `FORGE_HOME` makes the old cache links external and
report-only. Forge also cannot rediscover arbitrary project roots after their only global references were erased. Those
roots require an explicit visit; `--scope all` does not imply a filesystem crawl.

## Non-goals

- Adopting unmanaged output into tracking
- Overwriting or repairing an unmanaged package during enable/sync
- Deleting unmarked packages, even when their name or bytes resemble current Forge output
- Crawling `$HOME`, arbitrary repositories, ancestor directories, or `/etc` for cleanup candidates
- Treating cache digest equality as provenance; the incident cache may no longer exist
- Repairing a stale valid tracking row whose source skill was removed; existing status/sync behavior remains
  authoritative
- Moving runtime-package health into `forge extension doctor`

## Acceptance matrix

| Scenario                                                                                       | `extension status`                                                                  | `forge clean` preview/apply                                                |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Original incident: no tracking, unmarked current Forge name, valid `SKILL.md`                  | Unmanaged, unmarked, exact remove-or-rename recovery                                | Never listed or deleted                                                    |
| Newly compiled marked copy package, tracking lost, tree unchanged                              | Unmanaged, marked, cleanup eligible                                                 | Listed in the matching scope and removed only with `--yes`                 |
| Marked symlink package after cache loss; sentinel is regular and links match one cache package | Unmanaged, partial reset state, cleanup eligible                                    | Listed in the matching scope; removes links without following them         |
| Marked package has an edited or extra file                                                     | Unmanaged, modified, mismatch reason                                                | Never listed or deleted                                                    |
| Marker is malformed or from a newer schema                                                     | Unmanaged, invalid/unsupported marker                                               | Never listed or deleted                                                    |
| Unmarked or invalid-marker known-name directory is partial or lacks `SKILL.md`                 | Unmanaged, partial                                                                  | Never listed or deleted                                                    |
| Package root, target root, or descendant directory is a symlink                                | Unmanaged, invalid target                                                           | Never listed or traversed                                                  |
| Payload link is external or dangling links do not reconstruct one cache package                | Unmanaged, invalid target                                                           | Never listed or followed                                                   |
| Exact target is claimed by coherent tracking                                                   | Existing tracked package status only                                                | Not an unmanaged candidate                                                 |
| Unmanaged target also collides with another visible package                                    | Ownership unmanaged plus collision dirs                                             | Eligibility depends only on marker/scope proof, not collision state        |
| Unknown unmarked user-authored skill                                                           | Omitted                                                                             | Never listed or deleted                                                    |
| User-authored skill uses a historical Forge name                                               | Unmanaged, unmarked warning                                                         | Never listed or deleted                                                    |
| Corrupt, unsupported, or unreadable tracking                                                   | Existing state error; no unmanaged scan                                             | Fail closed; no package candidates                                         |
| `installed.json` removed while other GC state/cache survives                                   | Unmanaged scan runs with no claims                                                  | All unchanged marked entries in still-known roots form the previewed batch |
| Full `$FORGE_HOME` reset                                                                       | Fixed user and current project roots are visible; erased project references are not | User/current marked output can be listed; other projects require a visit   |
| Marked user orphan                                                                             | Shown under user/`--all` as cleanup eligible                                        | Excluded from `project`/`workspace`; listed and removable under `all`      |
| Project marked orphan fails project compatibility                                              | Unmanaged with recovery                                                             | Compatibility skip; never deleted                                          |
| Candidate becomes managed before `run_clean`'s fresh scan                                      | Updated status on next read                                                         | Omitted from apply; path preserved without a package failure               |
| Candidate changes after fresh scan but before deletion                                         | Updated status on next read                                                         | Pre-delete revalidation fails, preserves path, exits nonzero               |
| `/etc/codex/skills` or non-owned ancestor collision                                            | Visibility-only collision evidence                                                  | Never listed or deleted                                                    |

Installer recovery has its own acceptance contract:

| Enable/sync conflict or automatic skip                               | Required recovery                                                                            |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Marked, cleanup-eligible user orphan                                 | Exact path; preview/apply `forge clean --scope all`; rerun original command                  |
| Marked, cleanup-eligible project orphan                              | Exact path; preview/apply `cd <root> && forge clean --scope project`; rerun original command |
| Unmarked, modified, malformed, unsupported-marker, or unsafe package | Exact path and remove-or-rename; never suggest clean                                         |
| Mixed safe and unknown package conflicts                             | Per-package recovery; no single global clean tip                                             |

## Verification and documentation

- Compiler/cache/tracking tests in `tests/src/install/test_cross_runtime_skills.py` cover canonical marker bytes, cache
  invalidation, the always-copied sentinel in copy and symlink installs, sync/disable ledgers, and both runtime
  validators.
- New focused scanner tests cover the ownership/collision cross-product, historical names, partial entries, strict
  marker parsing, modified trees, canonical identity, live and dangling cache links, and `lstat`/symlink containment.
- `tests/src/cli/test_extension_enable.py` and `tests/src/install/test_cross_runtime_skills.py` pin the human status
  section, installer clean-vs-remove recovery, and the complete schema-v2 JSON shape, including the no-installation
  incident.
- `tests/src/core/ops/test_gc.py` and `tests/src/cli/test_gc.py` cover all three clean scopes, `%clean`, JSON counts,
  project compatibility, rescan drift, category-wide apply, missing-manifest second pass, lost-root boundaries, and
  failure exit behavior.
- Add a regression fixture for the discarded-`FORGE_HOME`/real-`HOME` incident and retain the existing global
  `tests/conftest.py::isolate_home` guard.
- Targeted Docker installer coverage verifies a wheel-installed marker, copy/symlink cache reset, and user/project
  cleanup/re-enable path because editable source and cache paths can hide packaging errors.

Implementation must update the normative runtime-skill ownership and partial-write sections in `docs/design.md` and
`docs/design_appendix.md`, the `extension status --json` and `clean` contracts in `docs/cli_reference.md`, the relevant
Day 1 extension guide and durable-state reset sequence under `docs/end-user/`, and board change/implementation notes at
closeout.

## Related

- [Cross-runtime skills](../../done/cross_runtime_skills/card.md) — duplicate safety, schema-v2 package tracking, and
  the compiled cache
- [`tests/conftest.py::isolate_home`](../../../../tests/conftest.py) — the leak-vector fix that motivated this card
- [`core/ops/gc.py`](../../../../src/forge/core/ops/gc.py) — existing cleanup report, scope, and compatibility seam
- [`skill_planning.py`](../../../../src/forge/install/skill_planning.py) — runtime target mapping and canonical path
  rules
