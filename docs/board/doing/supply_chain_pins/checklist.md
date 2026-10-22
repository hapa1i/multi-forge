# Supply-chain pinning checklist

Current focus: review [PR #280](https://github.com/hapa1i/multi-forge/pull/280) with the verified refusal fixes,
hash-based wheel recipe and separate consumer-compatibility check.

## Implementation

- [x] Inspect the existing lock, build, CI, installer and Docker boundaries; create a dedicated execution branch.
- [x] Export runtime/build requirements from `uv.lock`, pin the build backend, and reject stale exports.
- [x] Build distributions with hashed build constraints; standard repository commands reject stale lockfiles.
- [x] Pin CI Actions and uv bootstrap; use locked Python hook environments.
- [x] Refuse missing source revisions and dirty updates; constrain the global editable installation.
- [x] Pin Docker base/uv inputs and default client versions; retain explicit latest compatibility runs.
- [x] Sync installation design, end-user and developer guidance with actual guarantees and residual boundaries.
- [x] Validate fetched source candidates before changing the active editable checkout.
- [x] Select a supported Python for build preflight; keep runtime overrides out of unit-test collection.
- [x] Scope Docker build constraints to Forge commands.
- [x] Verify the hash-based global wheel recipe and refusal paths from its documented commands.
- [x] Verify the separate scheduled/manual unconstrained wheel check in a clean environment.

## Acceptance matrix

| Check             | Fixture                                        | Assertion                                           |
| ----------------- | ---------------------------------------------- | --------------------------------------------------- |
| Source selection  | Missing requested tag; existing dirty checkout | No fallback or destructive update                   |
| Dependency drift  | Modified export or build requirement           | Check fails before release                          |
| Global tool       | Isolated home, tools and bin directories       | Installed graph matches runtime constraints         |
| Package build     | Empty build environment                        | Only hashed build dependencies admitted             |
| Runtime selection | No host CLI; explicit latest override          | Default uses matrix; override stays explicit        |
| Docker install    | Disposable container and Forge home            | CLI/resources/hooks work from hardened image        |
| Candidate refusal | Real Git revision with missing/stale pins      | Active source, environment and launcher stay intact |
| Build interpreter | System Python without tomllib                  | Supported Python checks pins before building        |
| Unit collection   | Empty/inexact runtime environment overrides    | Collection succeeds; Docker use still refuses       |
| Container builds  | Unrelated local backend conflicting with Forge | Own project resolves independently                  |
| Verified wheel    | Wrong wheel/runtime hashes; occupied paths     | Refusal preserves previous global launcher          |

## Verification and delivery

- [x] Run focused unit/regression tests and negative fixtures.
- [x] Build wheel/sdist and run clean-wheel local proxy health/stop verification.
- [x] Verify constrained global tool installation and read-only extension doctor in isolated tool/state directories.
- [x] Verify the complete setup script and user/project extension enable in a disposable container.
- [x] Rerun aggregate unit/regression tests for review fixes and record
  [verification evidence](evidence/verification.md).
- [x] Refresh the installation design count after review edits and pass full pre-commit checks.
- [x] Rerun targeted installer/QA tests and unrelated-project builds against the updated Docker image.
- [x] Update evidence and remaining limitations for review.
- [ ] After merge, record closeout, move this card to done and update links.
