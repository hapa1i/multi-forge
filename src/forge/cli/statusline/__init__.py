"""Status-line rendering support package.

Sibling modules to ``forge.cli.status_line`` (the Click command + format_*
helpers). Lower source/type modules own neutral proxy, transcript, session, and
Git facts; rendering remains split across the command, registry, context,
palette, and throttle modules until the order-35 render extraction.

Note the spelling: this package is ``statusline`` (no underscore); the command
module is ``status_line`` (with underscore). They do not collide.
"""
