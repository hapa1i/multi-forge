# Supply-chain pinning checklist

Current focus: finish verification and open a draft PR while the Docker-space and document-count approvals are pending.

## Implementation

- [x] Inspect the existing lock, build, CI, installer and Docker boundaries; create a dedicated execution branch.
- [x] Export runtime/build requirements from `uv.lock`, pin the build backend, and reject stale exports.
- [x] Build distributions with hashed build constraints; standard repository commands reject stale lockfiles.
- [x] Pin CI Actions and uv bootstrap; use locked Python hook environments.
- [x] Refuse missing source revisions and dirty updates; constrain the global editable installation.
- [x] Pin Docker base/uv inputs and default client versions; retain explicit latest compatibility runs.
- [x] Sync installation design, end-user and developer guidance with actual guarantees and residual boundaries.

## Acceptance matrix

| Check             | Fixture                                        | Assertion                                    |
| ----------------- | ---------------------------------------------- | -------------------------------------------- |
| Source selection  | Missing requested tag; existing dirty checkout | No fallback or destructive update            |
| Dependency drift  | Modified export or build requirement           | Check fails before release                   |
| Global tool       | Isolated home, tools and bin directories       | Installed graph matches runtime constraints  |
| Package build     | Empty build environment                        | Only hashed build dependencies admitted      |
| Runtime selection | No host CLI; explicit latest override          | Default uses matrix; override stays explicit |
| Docker install    | Disposable container and Forge home            | CLI/resources/hooks work from hardened image |

## Verification and delivery

- [x] Run focused unit/regression tests and negative fixtures.
- [x] Build wheel/sdist and run clean-wheel local proxy health/stop verification.
- [x] Verify constrained global tool installation and read-only extension doctor in isolated tool/state directories.
- [x] Verify the complete setup script and user/project extension enable in a disposable container.
- [x] Run aggregate unit/regression tests and record results in [verification evidence](evidence/verification.md).
- [ ] Refresh the approved document count and pass full unit/pre-commit checks.
- [ ] Complete tests against the hardened Docker image after resolving disk space.
- [x] Record evidence and remaining limitations for draft review.
- [ ] After merge, record closeout, move this card to done and update links.
