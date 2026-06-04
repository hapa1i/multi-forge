"""Status-line rendering support package.

Sibling modules to ``forge.cli.status_line`` (the Click command + format_*
helpers). Split out so the registry, render context, throttle cache, and the
neutral segment-name constants don't bloat the single-file command module.

Note the spelling: this package is ``statusline`` (no underscore); the command
module is ``status_line`` (with underscore). They do not collide.
"""
