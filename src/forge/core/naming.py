"""Random name generation for human-friendly identifiers.

Provides consistent naming across Forge components using the coolname library.

Session names use default coolname (adjective-animal): 'spirited-coati'.
Proxy names use a custom color-fruit generator: 'teal-lemon'.

Usage:
    from forge.core.naming import generate_name, generate_unique_name
    from forge.core.naming import generate_proxy_name, generate_unique_proxy_name

    name = generate_name()                           # 'mottled-crab'
    unique = generate_unique_name(existing)           # Avoids collisions
    proxy = generate_proxy_name()                     # 'teal-lemon'
    unique_proxy = generate_unique_proxy_name(existing)
"""

from __future__ import annotations

import random
from typing import Literal

import coolname
from coolname import RandomGenerator

# Type alias for supported word counts
WordCount = Literal[2, 3, 4]

# Default word count for generated names
DEFAULT_WORDS: WordCount = 2


def generate_name(words: WordCount = DEFAULT_WORDS) -> str:
    """Generate a random human-friendly name.

    Args:
        words: Number of words in the name (2, 3, or 4).
            - 2: 'adjective-noun' (e.g., 'happy-fox') - ~10^5 combinations
            - 3: 'adjective-adjective-noun' (e.g., 'big-maize-lori') - ~10^8 combinations
            - 4: 'adjective-adjective-noun-of-noun' (e.g., 'military-diamond-tuatara-of-endeavor') - ~10^10 combinations

    Returns:
        A hyphenated lowercase name.

    Example:
        >>> name = generate_name()
        >>> '-' in name
        True
    """
    return coolname.generate_slug(words)


def generate_unique_name(
    existing_names: set[str],
    words: WordCount = DEFAULT_WORDS,
    max_attempts: int = 100,
) -> str:
    """Generate a random name that doesn't conflict with existing names.

    Args:
        existing_names: Set of names that already exist.
        words: Number of words in the name (2, 3, or 4).
        max_attempts: Maximum attempts before falling back to suffix strategy.

    Returns:
        A unique random name not in existing_names.

    Note:
        If max_attempts is exceeded, falls back to appending random suffixes
        until a unique name is found. With ~10^5 combinations for 2-word names,
        collisions are rare unless existing_names is very large.

    Example:
        >>> existing = {"happy-fox", "brave-wolf"}
        >>> name = generate_unique_name(existing)
        >>> name not in existing
        True
    """
    # Try generating names without suffix
    for _ in range(max_attempts):
        name = generate_name(words)
        if name not in existing_names:
            return name

    # Fallback: append random suffix, loop until unique
    while True:
        base = generate_name(words)
        suffix = random.randint(100, 9999)  # 4 digits for more entropy
        name = f"{base}-{suffix}"
        if name not in existing_names:
            return name


def generate_parts(words: WordCount = DEFAULT_WORDS) -> list[str]:
    """Generate name parts as a list (for custom formatting).

    Args:
        words: Number of words to generate (2, 3, or 4).

    Returns:
        List of name parts (e.g., ['happy', 'fox']).

    Example:
        >>> parts = generate_parts()
        >>> len(parts) == 2
        True
    """
    return coolname.generate(words)


# --- Proxy names: color-fruit pattern (visually distinct from session names) ---

_PROXY_COLORS = [
    "amber",
    "azure",
    "bronze",
    "cobalt",
    "copper",
    "coral",
    "crimson",
    "cyan",
    "ebony",
    "emerald",
    "garnet",
    "golden",
    "indigo",
    "ivory",
    "jade",
    "lavender",
    "magenta",
    "maroon",
    "navy",
    "ochre",
    "onyx",
    "ruby",
    "sage",
    "scarlet",
    "silver",
    "slate",
    "teal",
    "topaz",
    "turquoise",
    "violet",
]

_PROXY_FRUITS = [
    "apple",
    "apricot",
    "banana",
    "cherry",
    "citron",
    "coconut",
    "date",
    "fig",
    "grape",
    "guava",
    "kiwi",
    "lemon",
    "lime",
    "lychee",
    "mango",
    "melon",
    "olive",
    "orange",
    "papaya",
    "peach",
    "pear",
    "plum",
    "pomelo",
    "quince",
    "raisin",
    "sorbet",
    "tangerine",
    "walnut",
    "yuzu",
    "zest",
]

_proxy_generator = RandomGenerator(
    {
        "all": {"type": "cartesian", "lists": ["color", "fruit"]},
        "color": {"type": "words", "words": _PROXY_COLORS},
        "fruit": {"type": "words", "words": _PROXY_FRUITS},
    }
)


def generate_proxy_name() -> str:
    """Generate a color-fruit proxy name (e.g., 'teal-lemon')."""
    return _proxy_generator.generate_slug()


def generate_unique_proxy_name(
    existing_names: set[str],
    max_attempts: int = 100,
) -> str:
    """Generate a unique color-fruit proxy name.

    30 colors x 30 fruits = 900 combinations.
    Falls back to numeric suffix if exhausted.
    """
    for _ in range(max_attempts):
        name = generate_proxy_name()
        if name not in existing_names:
            return name

    while True:
        base = generate_proxy_name()
        suffix = random.randint(100, 9999)
        name = f"{base}-{suffix}"
        if name not in existing_names:
            return name
