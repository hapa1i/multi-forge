# Start the managed LiteLLM gateway from a project with a local Python module

The fix shipped on `main` in `fee340c7`. The launcher now passes Python's `-P` flag before `-m` to keep the caller's
directory out of the default import search path. [Completed checklist](checklist.md)

## Original failure

The launcher introduced in `ae188cb6` runs the pricing module with `python -m`. Starting the backend from a directory
containing `litellm.py` can import that file in place of the installed package. The gateway exits during import and
`forge model backend start` times out waiting for its health check.
