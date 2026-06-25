## 20. Cleanup

### 20.1 Cleanup Test Artifacts

<!-- auto -->

<!-- destructive -->

```bash
# Clean up test sessions and artifacts, but preserve the QA state mount
rm -rf .forge/sessions/ .forge/artifacts/ .forge/prev_sessions/ .forge/search-index/

# Remove shell profile backups (optional)
rm -f \
  ~/.bashrc.forge-uninstall-backup \
  ~/.bash_profile.forge-uninstall-backup \
  ~/.zshrc.forge-uninstall-backup \
  ~/.config/fish/config.fish.forge-uninstall-backup

# Remove QA cost fixture logs (safe: only QA-owned fixture names)
rm -f ~/.forge/costs/requests/qa-fixture_*.jsonl
rm -f ~/.forge/telemetry/downstream/*_qa-cap-seed.jsonl

# Remove QA usage/status-line fixtures from metric-evidence checks.
rm -f ~/.forge/usage/events/qa-usage-fixture_*.jsonl
rm -f ~/.forge/usage/events/qa-forgecost_*.jsonl
rm -f ~/.forge/cache/statusline/fcost-*.json

# Remove test repo entirely (optional)
# cd .. && rm -rf manual-testing/walkthrough/test-repo
```

- [ ] `.forge/sessions/` removed (or did not exist)
- [ ] `.forge/qa/` preserved (QA state mount -- do NOT delete)
- [ ] Shell profile backup removed (if existed)
- [ ] QA cost fixture logs removed from `~/.forge/costs/requests/` (no `qa-fixture_*.jsonl`)
- [ ] QA cap seed logs removed from `~/.forge/telemetry/downstream/` (no `*_qa-cap-seed.jsonl`)

---
