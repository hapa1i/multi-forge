# Forge QA Checklist

<!-- checklist: index -->

<!-- version: 1.0.23 -->

<!-- test-count: 535 -->

<!-- last-updated: 2026-06-06 -->

<!-- aligned-with: v0.1.0 -->

**Test Repo**: `$FORGE_TEST_REPO`

**Last updated**: 2026-06-06 (clean-break tombstone purge: removed the `forge usage`->`forge activity` rename probe (old
§7.14) along with the CLI tombstone commands themselves; `forge proxy costs reset` telemetry-wipe coverage renumbered to
7.14. Earlier: cost CLI is now a group: `forge proxy costs` -> `forge proxy costs show`; metric-evidence cost-honesty
coverage: `forge activity` cost footnotes/`~` marker (7.12), cost provenance reported-vs-`unavailable` split (7.13), the
`forge_cost`/`forge +$Y` status-line segment with harness exclusion (8.5), session-end `~` marker (5.21), and the §3.4
secret-vs-non-secret masking fix (OPENROUTER_BASE_URL shown in full); earlier: renamed the per-session command to
`forge activity` (7.12/5.21), status-line customization checks (§8.4), the workflow worker/verb double-count assertion
(7.12), non-interactive docker-exec fixes, policy `--session` targeting, memory 16.4 re-track)

---

## Sections

- [0. Enable Forge (New User Flow)](checklist/0-enable.md)

<!-- section: 0 checklist/0-enable.md -->

- [1. Pre-Flight for Extension Tests](checklist/1-preflight.md)

<!-- section: 1 checklist/1-preflight.md -->

- [2. Claude Code Extensions (`forge extension`)](checklist/2-extension.md)

<!-- section: 2 checklist/2-extension.md -->

- [3. Authentication (`forge authentication`)](checklist/3-authentication.md)

<!-- section: 3 checklist/3-authentication.md -->

- [4. Proxy Management (`forge proxy`)](checklist/4-proxy.md)

<!-- section: 4 checklist/4-proxy.md -->

- [5. Session Management (`forge session`)](checklist/5-session.md)

<!-- section: 5 checklist/5-session.md -->

- [6. Hooks (`forge hook`)](checklist/6-hook.md)

<!-- section: 6 checklist/6-hook.md -->

- [7. Cost Tracking & Spend Caps](checklist/7-costs.md)

<!-- section: 7 checklist/7-costs.md -->

- [8. Status Line](checklist/8-status-line.md)

<!-- section: 8 checklist/8-status-line.md -->

- [9. Direct Commands (% commands)](checklist/9-direct-commands.md)

<!-- section: 9 checklist/9-direct-commands.md -->

- [10. Session Resume (Phase 10 Feature)](checklist/10-resume.md)

<!-- section: 10 checklist/10-resume.md -->

- [11. Runtime Config + Claude Preset (`forge config`, `forge claude preset`)](checklist/11-config.md)

<!-- section: 11 checklist/11-config.md -->

- [12. Search (`forge search`)](checklist/12-search.md)

<!-- section: 12 checklist/12-search.md -->

- [13. Policy (`forge policy`)](checklist/13-policy.md)

<!-- section: 13 checklist/13-policy.md -->

- [14. Workflow Runners (`forge workflow`)](checklist/14-workflow.md)

<!-- section: 14 checklist/14-workflow.md -->

- [15. Skills (`/forge:review`, `/forge:understand`, `/forge:panel`, `/forge:consensus`)](checklist/15-skills.md)

<!-- section: 15 checklist/15-skills.md -->

- [16. Memory Writer](checklist/16-memory.md)

<!-- section: 16 checklist/16-memory.md -->

- [17. System Info](checklist/17-info.md)

<!-- section: 17 checklist/17-info.md -->

- [18. Uninstallation (Incremental)](checklist/18-disable.md)

<!-- section: 18 checklist/18-disable.md -->

- [19. Complete Uninstallation (setup.sh --uninstall)](checklist/19-uninstall.md)

<!-- section: 19 checklist/19-uninstall.md -->

- [20. Cleanup](checklist/20-cleanup.md)

<!-- section: 20 checklist/20-cleanup.md -->
