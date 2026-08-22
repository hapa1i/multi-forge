#!/usr/bin/env -S uv run --group provider-check python
"""Count tokens in documents.

Counting runs an ordered chain of methods and takes the first one that works,
so an unavailable provider degrades instead of failing.

A method is either a model name (provider inferred from its prefix) or the
literal ``local-tiktoken``:
    claude-*         -> Anthropic count_tokens (free, rate-limited; needs ANTHROPIC_API_KEY)
    gemini-*         -> Gemini count_tokens (free, rate-limited; needs GEMINI_API_KEY)
    gpt-*, o1-*, ... -> tiktoken (local, no key needed)
    local-tiktoken   -> tiktoken cl100k_base (local, deterministic, offline)
    (unknown)        -> skipped, falls through to the next method

The Anthropic and Gemini count_tokens endpoints are free of charge (you are not
billed for the tokens counted), but both are RPM rate-limited per usage tier.
API keys come from the environment first (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN,
GEMINI_API_KEY); when those are unset, the key is read from ~/.keys/<provider>_api_key
(--key-file overrides the Anthropic one). When a key or SDK is missing, a rate
limit is hit, or tiktoken cannot load an encoding offline, that method is skipped
and the next one in the chain runs.

Usage:
    count-tokens docs/design.md                        # default: claude-opus-5 -> local-tiktoken
    count-tokens --model gemini-2.5-flash file.md      # gemini-2.5-flash -> local-tiktoken
    count-tokens --model gpt-4 file.md                 # tiktoken (local)
    count-tokens --methods claude-opus-5,gemini-2.5-flash,local-tiktoken file.md
    count-tokens --local file.md                       # tiktoken only, no API calls
    count-tokens --local --model gpt-4o file.md        # tiktoken only, via o200k_base
    cat file.txt | count-tokens                        # stdin
    count-tokens -q file.txt                           # quiet: number only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"

# Sentinel method name for offline tiktoken counting, usable anywhere in a chain.
LOCAL_METHOD = "local-tiktoken"

# Encoding used when tiktoken has no model-specific one (e.g. for Claude models).
FALLBACK_ENCODING = "cl100k_base"

# Key files consulted only when the matching environment variable is unset. The
# environment always wins, so an exported or direnv-loaded key keeps working
# unchanged; these make the API path also work where the profile is never
# sourced (git hooks invoked by a GUI client, cron, editor-spawned shells).
DEFAULT_ANTHROPIC_KEY_FILE = Path.home() / ".keys" / "anthropic_api_key"
DEFAULT_GEMINI_KEY_FILE = Path.home() / ".keys" / "gemini_api_key"


def _read_key_file(path: str | Path | None) -> str | None:
    """Read an API key from a file.

    Returns None when the file is missing, empty, or unreadable -- a key file is
    a convenience fallback, never a hard requirement, so a bad path must degrade
    to the next method rather than raise.
    """
    if not path:
        return None
    try:
        key = Path(path).expanduser().read_text().strip()
    except OSError:
        return None
    return key or None


def _detect_provider(model: str) -> str:
    """Detect provider from model name prefix."""
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("gemini-"):
        return "gemini"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return "openai"
    return "unknown"


# Short timeout so a stalled provider API can never hang a caller (e.g. a
# git pre-commit hook). Anthropic takes seconds; Gemini takes milliseconds.
_ANTHROPIC_TIMEOUT_S = 10.0
_GEMINI_TIMEOUT_MS = 10_000


def _count_anthropic(
    text: str,
    model: str,
    key_file: str | Path | None = DEFAULT_ANTHROPIC_KEY_FILE,
) -> int | None:
    """Count tokens via Anthropic API (free endpoint). Returns None on failure."""
    try:
        import anthropic
    except ImportError:
        return None
    # Pre-check credentials: with no key the SDK raises a bare TypeError
    # ("could not resolve authentication method"), which we deliberately do NOT
    # catch below (it overlaps with genuine bugs). Mirrors the GEMINI_API_KEY
    # check in _count_gemini.
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        # Let the SDK resolve the environment itself: ANTHROPIC_AUTH_TOKEN is a
        # bearer token, not an api_key, so forcing it into api_key would break it.
        client = anthropic.Anthropic(timeout=_ANTHROPIC_TIMEOUT_S)
    else:
        key = _read_key_file(key_file)
        if not key:
            return None
        client = anthropic.Anthropic(timeout=_ANTHROPIC_TIMEOUT_S, api_key=key)
    try:
        result = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return result.input_tokens
    except anthropic.AnthropicError:
        # Missing/invalid key, rate limit (429), connection, or timeout.
        # Programming errors (e.g. AttributeError) are NOT caught here.
        return None


def _count_gemini(
    text: str,
    model: str,
    key_file: str | Path | None = DEFAULT_GEMINI_KEY_FILE,
) -> int | None:
    """Count tokens via Gemini API (free endpoint). Returns None on failure."""
    try:
        import httpx
        from google import genai
        from google.genai import errors
    except ImportError:
        return None
    key = os.environ.get("GEMINI_API_KEY") or _read_key_file(key_file)
    if not key:
        return None
    try:
        client = genai.Client(api_key=key, http_options={"timeout": _GEMINI_TIMEOUT_MS})
        result = client.models.count_tokens(model=model, contents=text)
        return result.total_tokens
    except (errors.APIError, httpx.HTTPError):
        # API error (auth, 429, bad request) or network/timeout. Programming
        # errors propagate so real bugs are not masked as a silent fallback.
        return None


def _load_encoding(model: str | None):
    """Load the tiktoken encoding for ``model``, or the default encoding.

    Returns None when no encoding could be loaded, so the caller can fall
    through to the next method instead of aborting. tiktoken downloads BPE data
    on first use of an encoding, so this legitimately fails on an offline
    machine whose cache lacks that particular encoding.
    """
    try:
        import tiktoken
    except ImportError:
        return None

    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            # Not a tiktoken model; use the default encoding below.
            pass
        except Exception:
            # tiktoken surfaces whatever its HTTP layer raises when it cannot
            # fetch BPE data, with no stable public exception type to match on.
            # Do NOT silently substitute the default encoding here: the caller
            # asked for this model's tokenizer, so report unavailable instead.
            return None
    try:
        return tiktoken.get_encoding(FALLBACK_ENCODING)
    except Exception:
        return None


def _count_tiktoken(text: str, model: str | None = None) -> tuple[int, str] | None:
    """Count tokens locally with tiktoken.

    Returns (count, encoding_name) so callers can report the tokenizer that
    actually ran, or None when no encoding is available. Only the encoding load
    is guarded -- a failure inside encode() is a real bug and still raises.
    """
    encoding = _load_encoding(model)
    if encoding is None:
        return None
    return len(encoding.encode(text)), encoding.name


def parse_methods(spec: str) -> list[str]:
    """Parse a comma-separated method chain into an ordered list."""
    return [m.strip() for m in spec.split(",") if m.strip()]


def resolve_methods(model: str, local: bool = False, methods: str | list[str] | None = None) -> list[str]:
    """Build the ordered method chain from the CLI flags.

    --local wins over everything (a deliberate, deterministic override),
    then an explicit --methods chain, then the implicit `<model> -> local` chain.
    """
    if local:
        return [LOCAL_METHOD]
    if methods:
        chain = parse_methods(methods) if isinstance(methods, str) else list(methods)
        if chain:
            return chain
    return [model, LOCAL_METHOD]


def _count_one(
    text: str,
    method: str,
    local_model: str | None = None,
    key_file: str | Path | None = None,
    gemini_key_file: str | Path | None = None,
) -> tuple[int, str] | None:
    """Run a single method. Returns None when it is unavailable, so the caller
    can move to the next link in the chain.

    ``local_model`` is set only by --local, where the user named the tokenizer
    via --model; a bare local-tiktoken step in a chain stays generic.
    ``key_file`` / ``gemini_key_file`` override the per-provider key files;
    None keeps the default. There is no OpenAI equivalent: that branch runs
    tiktoken locally and never authenticates.
    """
    if method == LOCAL_METHOD:
        local_result = _count_tiktoken(text, local_model)
        return (local_result[0], f"tiktoken local ({local_result[1]})") if local_result is not None else None

    provider = _detect_provider(method)

    if provider == "anthropic":
        provider_count = _count_anthropic(text, method, key_file or DEFAULT_ANTHROPIC_KEY_FILE)
        return (provider_count, f"anthropic API ({method})") if provider_count is not None else None
    if provider == "gemini":
        provider_count = _count_gemini(text, method, gemini_key_file or DEFAULT_GEMINI_KEY_FILE)
        return (provider_count, f"gemini API ({method})") if provider_count is not None else None
    if provider == "openai":
        # tiktoken is the real tokenizer for these models, not an approximation.
        local_result = _count_tiktoken(text, method)
        return (local_result[0], f"tiktoken ({method} / {local_result[1]})") if local_result is not None else None

    # Unrecognised model name: skip rather than guess, and let the chain continue.
    return None


def count_tokens(
    text: str,
    model: str = DEFAULT_MODEL,
    local: bool = False,
    methods: str | list[str] | None = None,
    key_file: str | Path | None = None,
    gemini_key_file: str | Path | None = None,
) -> tuple[int, str]:
    """Count tokens by walking the method chain; first success wins.

    Returns (count, method_description).

    When ``local`` is True, always uses tiktoken and never touches a provider
    API, still honouring ``model``'s own tokenizer when tiktoken knows it (e.g.
    gpt-4o -> o200k_base). This makes the count deterministic and offline
    regardless of which keys happen to be in the environment -- the right choice
    for gates where reproducible pass/fail matters more than provider parity.

    An exhausted chain still tries tiktoken rather than failing, so a
    misconfigured chain degrades instead of blocking a caller.
    """
    local_model = model if local else None

    for method in resolve_methods(model, local=local, methods=methods):
        result = _count_one(
            text,
            method,
            local_model=local_model,
            key_file=key_file,
            gemini_key_file=gemini_key_file,
        )
        if result is not None:
            return result

    fallback = _count_tiktoken(text)
    if fallback is None:
        print(
            "Error: no token counting method available (tiktoken missing, or its "
            "encoding data could not be loaded). Run: uv sync",
            file=sys.stderr,
        )
        sys.exit(1)
    return fallback[0], f"tiktoken ({fallback[1]} fallback)"


def _read_input(files: list[str]) -> tuple[str, str]:
    """Read input from files or stdin. Returns (text, source_description)."""
    if not files or files == ["-"]:
        return sys.stdin.read(), "stdin"

    all_text = []
    sources = []
    for file_path in files:
        path = Path(file_path)
        if not path.exists():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        all_text.append(path.read_text())
        sources.append(path.name)

    return "\n".join(all_text), ", ".join(sources)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count tokens for documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=["-"],
        help="Files to count (default: stdin)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Model for token counting (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--key-file",
        default=str(DEFAULT_ANTHROPIC_KEY_FILE),
        help=(
            "File holding the Anthropic API key, read only when ANTHROPIC_API_KEY and "
            f"ANTHROPIC_AUTH_TOKEN are both unset (default: {DEFAULT_ANTHROPIC_KEY_FILE})"
        ),
    )
    parser.add_argument(
        "--gemini-key-file",
        default=str(DEFAULT_GEMINI_KEY_FILE),
        help=(
            "File holding the Gemini API key, read only when GEMINI_API_KEY is unset "
            f"(default: {DEFAULT_GEMINI_KEY_FILE}). OpenAI models need no key: they are "
            "counted locally with tiktoken, OpenAI's own tokenizer"
        ),
    )
    parser.add_argument(
        "--methods",
        help=(
            "Comma-separated fallback chain, tried in order; first one that works wins "
            f"(e.g. claude-opus-5,gemini-2.5-flash,{LOCAL_METHOD}). "
            "Overrides --model; overridden by --local"
        ),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help=(
            "Force local tiktoken counting (no provider API calls); deterministic and offline. "
            "Uses --model's own tokenizer when tiktoken knows it, else " + FALLBACK_ENCODING
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable object with tokens and the method that ran",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Output only the number (the method is still reported on stderr)",
    )

    args = parser.parse_args()
    text, _ = _read_input(args.files)

    if not text.strip():
        if args.quiet:
            print("0")
        else:
            print("0 tokens (empty input)")
        return

    token_count, method = count_tokens(
        text,
        args.model,
        local=args.local,
        methods=args.methods,
        key_file=args.key_file,
        gemini_key_file=args.gemini_key_file,
    )

    if args.json:
        print(json.dumps({"tokens": token_count, "method": method}, separators=(",", ":")))
    elif args.quiet:
        print(token_count)
        # Method goes to stderr so the count on stdout stays machine-parseable,
        # but the method is never invisible (estimate vs exact is always known).
        print(f"method: {method}", file=sys.stderr)
    else:
        chars = len(text)
        lines = text.count("\n") + 1
        print(f"{token_count:,} tokens | {chars:,} chars | {lines:,} lines")
        print(f"  method: {method}")


if __name__ == "__main__":
    main()
