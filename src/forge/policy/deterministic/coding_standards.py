"""Coding standards bundle policies.

Enforces coding conventions from docs/developer/coding_standards.md:
- no-TYPE_CHECKING: Block TYPE_CHECKING import workarounds
- no-backward-compat: Block backward compatibility hacks
- no-emoji: Block colorful emoji in code files (monospace matters)
"""

from __future__ import annotations

from forge.policy.deterministic.base import DeterministicPolicy
from forge.policy.types import ActionContext, PolicyDecision, Violation

# Patterns indicating TYPE_CHECKING workarounds
TYPE_CHECKING_PATTERNS = [
    r"if\s+TYPE_CHECKING\s*:",
    r"from\s+typing\s+import.*TYPE_CHECKING",
]

# Patterns indicating backward compatibility hacks
BACKWARD_COMPAT_PATTERNS = [
    r"#\s*backward\s*compat",
    r"#\s*backwards?\s*compat",
    r"#\s*legacy\b",
    r"#\s*deprecated\b",
    r"#\s*TODO.*remove.*later",
    r"#\s*for\s+backward",
    r"#\s*DEPRECATED\b",
    r"#\s*LEGACY\b",
    r"#\s*compat(?:ibility)?\s*(?:layer|shim|wrapper)",
]


class NoTypeCheckingPolicy(DeterministicPolicy):
    """Block TYPE_CHECKING import workarounds.

    From coding_standards.md:
    > No TYPE_CHECKING workarounds: Fix circular imports architecturally
    > instead of using `if TYPE_CHECKING:` blocks

    TYPE_CHECKING blocks are a symptom of circular imports that should be
    fixed by restructuring the code (e.g., moving types to a separate module).
    """

    @property
    def policy_id(self) -> str:
        return "coding_standards.no-type-checking"

    @property
    def description(self) -> str:
        return "Block TYPE_CHECKING workarounds (fix circular imports architecturally)"

    @property
    def intent(self) -> str:
        return (
            "Circular imports indicate an architectural problem. TYPE_CHECKING blocks "
            "hide the symptom instead of fixing the dependency structure. This policy "
            "ensures clean module boundaries."
        )

    def applies_to(self, context: ActionContext) -> bool:
        """Apply to Write/Edit on Python files with content."""
        if context.tool_name not in ("Write", "Edit"):
            return False

        if context.new_content is None:
            return False

        # Only check Python files
        path = context.target_path
        return path is not None and path.endswith(".py")

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        """Check for TYPE_CHECKING patterns."""
        matched = self._matches_any_pattern(context.new_content, TYPE_CHECKING_PATTERNS)

        if matched:
            violations = [
                Violation(
                    rule_id=self.policy_id,
                    message="TYPE_CHECKING blocks are not allowed",
                    severity="medium",
                    evidence=f"Found TYPE_CHECKING pattern(s): {', '.join(matched)}",
                    suggested_fix=(
                        "Fix circular imports architecturally by:\n"
                        "1. Moving shared types to a separate types.py module\n"
                        "2. Using dependency injection\n"
                        "3. Restructuring the module hierarchy"
                    ),
                )
            ]
            return self._deny(violations)

        return self._allow()


class NoBackwardCompatPolicy(DeterministicPolicy):
    """Block backward compatibility hacks.

    From coding_standards.md:
    > No Backward Compatibility Wrappers: Update callers directly, don't create adapters
    > Clean Refactoring: Fix underlying issues over compatibility layers
    > No Fallback Logic: When replacing a component, remove the old one completely

    This policy detects common backward-compat patterns in comments and code.
    """

    @property
    def policy_id(self) -> str:
        return "coding_standards.no-backward-compat"

    @property
    def description(self) -> str:
        return "Block backward compatibility hacks (update callers directly)"

    @property
    def intent(self) -> str:
        return (
            "Compatibility layers accumulate technical debt. This project prefers clean "
            "breaks: update all callers directly and remove old code completely rather "
            "than maintaining shims or fallback logic."
        )

    def applies_to(self, context: ActionContext) -> bool:
        """Apply to Write/Edit on Python files with content."""
        if context.tool_name not in ("Write", "Edit"):
            return False

        if context.new_content is None:
            return False

        # Only check Python files
        path = context.target_path
        return path is not None and path.endswith(".py")

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        """Check for backward compatibility patterns."""
        matched = self._matches_any_pattern(context.new_content, BACKWARD_COMPAT_PATTERNS)

        if matched:
            violations = [
                Violation(
                    rule_id=self.policy_id,
                    message="Backward compatibility patterns are not allowed",
                    severity="medium",
                    evidence=f"Found backward-compat pattern(s): {', '.join(matched)}",
                    suggested_fix=(
                        "Instead of compatibility layers:\n"
                        "1. Update all callers directly\n"
                        "2. Remove the old implementation completely\n"
                        "3. Delete obsolete tests (don't skip them)"
                    ),
                )
            ]
            return self._deny(violations)

        return self._allow()


# Colorful emoji ranges — double-width characters that break monospace rendering.
# Excludes text-safe dingbats (checkmark, cross, diamond, warning, arrows) that render
# properly in fixed-width terminals.
_EMOJI_RANGES = (
    (0x1F300, 0x1F5FF),  # Misc symbols & pictographs
    (0x1F600, 0x1F64F),  # Emoticons (faces)
    (0x1F680, 0x1F6FF),  # Transport & map symbols
    (0x1F700, 0x1F77F),  # Alchemical symbols
    (0x1F900, 0x1F9FF),  # Supplemental symbols & pictographs
    (0x1FA00, 0x1FAFF),  # Chess, extended-A symbols
)


def _is_colorful_emoji(ch: str) -> bool:
    """Return True if ch is a colorful emoji this policy blocks.

    Compares the code point against _EMOJI_RANGES directly rather than using a regex
    character class. A literal class with supplementary-plane range escapes reads as an
    ambiguous range to static analyzers: CodeQL's py/overly-large-range collapses astral
    code points to U+FFFD and reports phantom overlapping ranges. Explicit integer bounds
    carry the same intent without the ambiguity.
    """
    cp = ord(ch)
    if cp < 0x10000:  # Every blocked range is supplementary-plane; BMP text is always fine.
        return False
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".sh",
        ".bash",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".swift",
        ".kt",
        ".scala",
    }
)


class NoEmojiPolicy(DeterministicPolicy):
    """Block colorful emoji in code files.

    Monospace rendering matters in code. Double-width emoji characters break
    alignment in terminals, diffs, and code review tools. Text-safe symbols
    (checkmark, cross, arrows, warning) are allowed — only colorful pictographs
    are blocked.
    """

    @property
    def policy_id(self) -> str:
        return "coding_standards.no-emoji"

    @property
    def description(self) -> str:
        return "Block colorful emoji in code (monospace matters)"

    @property
    def intent(self) -> str:
        return (
            "Double-width emoji break alignment in terminals, diffs, and code review "
            "tools. Source code should stay ASCII-clean for consistent monospace "
            "rendering. This includes Unicode escapes that produce emoji at runtime."
        )

    def applies_to(self, context: ActionContext) -> bool:
        """Apply to Write/Edit on code files with content."""
        if context.tool_name not in ("Write", "Edit"):
            return False
        if context.new_content is None:
            return False
        path = context.target_path
        if path is None:
            return False
        for ext in _CODE_EXTENSIONS:
            if path.endswith(ext):
                return True
        return False

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        """Check for colorful emoji in content."""
        assert context.new_content is not None
        found = [ch for ch in context.new_content if _is_colorful_emoji(ch)]
        if found:
            unique = list(dict.fromkeys(found))  # dedupe, preserve order
            sample = " ".join(unique[:5])
            violations = [
                Violation(
                    rule_id=self.policy_id,
                    message=f"Emoji characters found in code: {sample}",
                    severity="low",
                    evidence=f"Found {len(found)} emoji character(s): {sample}",
                    suggested_fix="Use ASCII equivalents or text-safe symbols instead of colorful emoji.",
                )
            ]
            return self._deny(violations)
        return self._allow()
