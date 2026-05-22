# Usability Issues

Small product and CLI friction points discovered while dogfooding Forge.

## Open

### Auto-create local suggested memory docs

- **Context**: Project status docs can use a gitignored shadow doc such as `.forge/memory/suggested_impl_notes.md`
  with `strategy=suggested` and `--shadows docs/status/impl_notes.md`.
- **Current behavior**: `forge session memory add-doc` requires the shadow doc to already exist, so setup needs:

```bash
mkdir -p .forge/memory
touch .forge/memory/suggested_impl_notes.md
```

- **Usability issue**: This is unnecessary friction for a Forge-owned, gitignored scratch path. The CLI already knows the
  desired path and can create an empty shadow doc safely when it is under `.forge/memory/`.
- **Desired behavior**: `forge session memory add-doc .forge/memory/suggested_impl_notes.md --strategy suggested --shadows docs/status/impl_notes.md`
  creates the parent directory and empty shadow doc automatically if missing.
- **Constraints**: Keep the current no-file-creation rule for tracked project docs such as `docs/status/change_log.md` and
  official `--shadows` targets. Auto-create only local shadow/proposal docs in Forge-owned scratch space.
