"""Status-line acquisition, formatting, and rendering package.

``forge.cli.status_line`` owns only the Click/stdin/source/terminal boundary.
Sibling modules own neutral facts, lazy source acquisition, segment planning,
presentation, and final layout without importing the command.

Note the spelling: this package is ``statusline`` (no underscore); the command
module is ``status_line`` (with underscore). They do not collide.
"""
