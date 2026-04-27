## 20. Cleanup

### 20.1 Cleanup Test Artifacts

<!-- auto -->

<!-- destructive -->

```bash
# Clean up test sessions and artifacts, but preserve the QA state mount
rm -rf .forge/sessions/ .forge/artifacts/ .forge/prev_sessions/ .forge/search-index/

# Remove shell profile backup (optional)
rm -f ~/.zshrc.forge-uninstall-backup

# Remove test repo entirely (optional)
# cd .. && rm -rf manual-testing/walkthrough/test-repo
```

- [ ] `.forge/sessions/` removed (or did not exist)
- [ ] `.forge/qa/` preserved (QA state mount -- do NOT delete)
- [ ] Shell profile backup removed (if existed)

---
