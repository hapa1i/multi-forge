"""Tests for check-file-limits glob pattern matching and rule evaluation."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# ruff: noqa: E402
import importlib

mod = importlib.import_module("check-file-limits")
match_pattern = mod.match_pattern
get_limits = mod.get_limits
get_token_methods = mod.get_token_methods
resolve_config_path = mod.resolve_config_path
check_file = mod.check_file
check_files = mod.check_files
count_tokens_many = mod.count_tokens_many
limit_for_family = mod.limit_for_family
DEFAULT_TOKEN_METHODS = mod.DEFAULT_TOKEN_METHODS


# -- match_pattern tests --


class TestMatchPatternFilenameOnly:
    """Patterns without '/' match against filename only."""

    def test_extension_glob_matches(self):
        assert match_pattern("src/foo.py", "*.py")

    def test_extension_glob_bare_filename(self):
        assert match_pattern("foo.py", "*.py")

    def test_extension_glob_rejects_wrong_ext(self):
        assert not match_pattern("foo.txt", "*.py")

    def test_prefix_glob_matches_nested(self):
        assert match_pattern("src/test_bar.py", "test_*.py")

    def test_prefix_glob_matches_bare(self):
        assert match_pattern("test_bar.py", "test_*.py")

    def test_prefix_glob_rejects_non_match(self):
        assert not match_pattern("src/bar.py", "test_*.py")

    def test_no_false_match_through_directory(self):
        """test_*.py should NOT match tests/module.py (would if matched against full path)."""
        assert not match_pattern("tests/module.py", "test_*.py")


class TestMatchPatternWithPath:
    """Patterns with '/' match against the full relative path."""

    def test_dir_glob_matches(self):
        assert match_pattern("docs/readme.md", "docs/*.md")

    def test_dir_glob_rejects_subdirectory(self):
        assert not match_pattern("docs/sub/readme.md", "docs/*.md")

    def test_dir_glob_rejects_different_dir(self):
        assert not match_pattern("src/docs/readme.md", "docs/*.md")

    def test_nested_dir_pattern(self):
        assert match_pattern("src/tests/test_foo.py", "src/tests/*.py")


# -- get_limits tests --


RULES_CONFIG = {
    "rules": [
        {"pattern": "test_*.py", "max_lines": 5000, "max_tokens": 50000},
        {"pattern": "*.py", "max_lines": 2500, "max_tokens": 25000},
        {"pattern": "*.md", "max_lines": 2000, "max_tokens": 25000},
    ]
}

SKIP_CONFIG = {
    "rules": [
        {"pattern": "docs/*.md", "skip": True},
        {"pattern": "*.md", "max_lines": 2000, "max_tokens": 25000},
    ]
}


class TestGetLimits:
    def test_first_match_wins(self):
        limits = get_limits("test_foo.py", RULES_CONFIG)
        assert limits["max_lines"] == 5000

    def test_falls_through_to_later_rule(self):
        limits = get_limits("foo.py", RULES_CONFIG)
        assert limits["max_lines"] == 2500

    def test_no_match_returns_none(self):
        assert get_limits("foo.rs", RULES_CONFIG) is None

    def test_empty_rules_returns_none(self):
        assert get_limits("foo.py", {"rules": []}) is None

    def test_skip_returns_none(self):
        assert get_limits("docs/readme.md", SKIP_CONFIG) is None

    def test_skip_does_not_affect_non_match(self):
        limits = get_limits("notes.md", SKIP_CONFIG)
        assert limits is not None
        assert limits["max_lines"] == 2000


# -- get_token_methods tests --


class TestGetTokenMethods:
    def test_reads_configured_chain(self):
        config = {"token_count": {"methods": ["claude-opus-5", "gemini-2.5-flash", "local-tiktoken"]}}
        assert get_token_methods(config) == ["claude-opus-5", "gemini-2.5-flash", "local-tiktoken"]

    def test_single_method_chain(self):
        assert get_token_methods({"token_count": {"methods": ["local-tiktoken"]}}) == ["local-tiktoken"]

    def test_missing_section_uses_default(self):
        assert get_token_methods({}) == DEFAULT_TOKEN_METHODS

    def test_missing_methods_key_uses_default(self):
        assert get_token_methods({"token_count": {}}) == DEFAULT_TOKEN_METHODS

    def test_empty_list_uses_default(self):
        assert get_token_methods({"token_count": {"methods": []}}) == DEFAULT_TOKEN_METHODS

    def test_non_list_uses_default(self):
        assert get_token_methods({"token_count": {"methods": "local-tiktoken"}}) == DEFAULT_TOKEN_METHODS

    def test_blank_entries_dropped(self):
        config = {"token_count": {"methods": ["  claude-opus-5  ", "", "  ", "local-tiktoken"]}}
        assert get_token_methods(config) == ["claude-opus-5", "local-tiktoken"]

    def test_default_is_not_mutated_by_caller(self):
        returned = get_token_methods({})
        returned.append("mutated")
        assert get_token_methods({}) == DEFAULT_TOKEN_METHODS

    def test_shipped_config_chain(self):
        """The checked-in config must keep a local fallback last."""
        config_path = REPO_ROOT / ".file-size-limits.json"
        config = json.loads(config_path.read_text())
        chain = get_token_methods(config)
        assert chain[0] == "claude-opus-5"
        assert chain[-1] == "local-tiktoken"


class TestConfigResolution:
    def test_explicit_config_wins(self, monkeypatch, tmp_path):
        explicit = tmp_path / "explicit.json"
        explicit.write_text("{}")
        monkeypatch.setattr(mod, "get_git_root", lambda: tmp_path / "repo")
        assert resolve_config_path(explicit) == explicit.resolve()

    def test_repository_config_precedes_personal_fallback(self, monkeypatch, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        policy = repo / ".file-size-limits.json"
        policy.write_text("{}")
        monkeypatch.setattr(mod, "get_git_root", lambda: repo)
        assert resolve_config_path() == policy

    def test_missing_discovered_policy_uses_checkout_root_policy(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "get_git_root", lambda: tmp_path)
        assert resolve_config_path() == REPO_ROOT / ".file-size-limits.json"

    def test_done_checklists_receive_only_the_ratified_historical_exception(self):
        config = json.loads((REPO_ROOT / ".file-size-limits.json").read_text())
        done = get_limits("docs/board/done/runtime_abstraction/checklist.md", config)
        living = get_limits("docs/design.md", config)
        assert done["max_tokens"] == {"anthropic": 40000, "tiktoken": 20000}
        assert living["target_tokens"] == {"anthropic": 25000, "tiktoken": 12000}
        assert living["max_tokens"] == {"anthropic": 30000, "tiktoken": 15000}


class TestLimitForFamily:
    def test_selects_only_the_family_that_ran(self):
        limits = {"anthropic": 30000, "tiktoken": 15000}
        assert limit_for_family(limits, "anthropic") == 30000
        assert limit_for_family(limits, "tiktoken") == 15000
        assert limit_for_family(limits, "gemini") is None

    def test_scalar_limit_remains_compatible(self):
        assert limit_for_family(30000, "anthropic") == 30000
        assert limit_for_family(30000, "tiktoken") == 30000

    def test_rejects_boolean_and_malformed_limits(self):
        assert limit_for_family(True, "tiktoken") is None
        assert limit_for_family({"tiktoken": True}, "tiktoken") is None
        assert limit_for_family({"tiktoken": "many"}, "tiktoken") is None


class TestTargetsAndFamilies:
    @staticmethod
    def _config(**rule):
        return {
            "token_count": {"methods": ["claude-opus-5", "local-tiktoken"]},
            "rules": [
                {
                    "pattern": "*.md",
                    "max_lines": 100,
                    "max_tokens": {"anthropic": 30000, "tiktoken": 15000},
                    **rule,
                }
            ],
        }

    def test_target_is_warning_not_failure(self, monkeypatch, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text("text\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            mod,
            "count_tokens",
            lambda _path, methods: (
                (16000, "tiktoken local (cl100k_base)", "tiktoken")
                if methods == ["local-tiktoken"]
                else (26000, "anthropic API (claude-opus-5)", "anthropic")
            ),
        )
        errors, warnings = check_file(
            "doc.md",
            self._config(
                target_tokens={"anthropic": 25000, "tiktoken": 12000},
            ),
        )
        assert errors == []
        assert "26,000 tokens exceeds target" in warnings[0]

    def test_large_fallback_uses_the_conservative_local_limit(self, monkeypatch, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text("text\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            mod,
            "count_tokens",
            lambda _path, _methods: (16000, "fallback wording can change", "tiktoken"),
        )
        errors, _ = check_file("doc.md", self._config())
        assert "16,000 tokens exceeds limit of 15,000" in errors[0]

    def test_near_target_fallback_is_visible_as_a_local_warning(self, monkeypatch, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text("text\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            mod,
            "count_tokens",
            lambda _path, _methods: (13000, "fallback", "tiktoken"),
        )
        errors, warnings = check_file(
            "doc.md",
            self._config(
                target_tokens={"anthropic": 25000, "tiktoken": 12000},
            ),
        )
        assert errors == []
        assert "13,000 tokens exceeds target of 12,000" in warnings[0]

    def test_unconfigured_family_warns_instead_of_silently_passing(self, monkeypatch, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text("text\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            mod,
            "count_tokens",
            lambda _path, methods: (
                (16000, "local", "tiktoken") if methods == ["local-tiktoken"] else (26000, "gemini", "gemini")
            ),
        )
        errors, warnings = check_file("doc.md", self._config())
        assert errors == []
        assert "no max_tokens configured for the 'gemini' tokenizer" in warnings[0]

    def test_local_only_chain_counts_once(self, monkeypatch, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text("text\n")
        monkeypatch.chdir(tmp_path)
        calls = []
        monkeypatch.setattr(
            mod,
            "count_tokens",
            lambda _path, methods: calls.append(methods) or (100, "local", "tiktoken"),
        )

        check_file("doc.md", self._config(token_methods=["local-tiktoken"]))

        assert calls == [["local-tiktoken"]]


class TestBatchCounting:
    def test_count_tokens_many_uses_one_per_file_process(self, monkeypatch):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            seen["kwargs"] = kwargs
            return mod.subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '{"path":"one.md","tokens":11,"method":"local","family":"tiktoken"}\n'
                    '{"path":"two.md","tokens":22,"method":"local","family":"tiktoken"}\n'
                ),
                stderr="",
            )

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        counts = count_tokens_many(["one.md", "two.md"], ["local-tiktoken"])

        assert seen["command"][-4:] == ["--per-file", "--json", "one.md", "two.md"]
        assert seen["kwargs"] == {"capture_output": True, "text": True}
        assert counts == {
            "one.md": (11, "local", "tiktoken"),
            "two.md": (22, "local", "tiktoken"),
        }

    def test_check_files_batches_local_counts_and_only_probes_large_docs(self, monkeypatch, tmp_path):
        small = tmp_path / "small.md"
        large = tmp_path / "large.md"
        small.write_text("small\n")
        large.write_text("large\n")
        monkeypatch.chdir(tmp_path)
        calls = []

        def fake_count_many(paths, methods):
            calls.append((paths, methods))
            if methods == ["local-tiktoken"]:
                return {
                    "small.md": (1000, "local", "tiktoken"),
                    "large.md": (16000, "local", "tiktoken"),
                }
            return {"large.md": (26000, "anthropic API (claude-opus-5)", "anthropic")}

        monkeypatch.setattr(mod, "count_tokens_many", fake_count_many)
        config = {
            "token_count": {"methods": ["claude-opus-5", "local-tiktoken"]},
            "rules": [
                {
                    "pattern": "*.md",
                    "max_lines": 100,
                    "target_tokens": {"anthropic": 25000, "tiktoken": 12000},
                    "max_tokens": {"anthropic": 30000, "tiktoken": 15000},
                }
            ],
        }

        errors, warnings = check_files(["small.md", "large.md"], config)

        assert errors == []
        assert len(warnings) == 1
        assert "large.md: 26,000 tokens exceeds target" in warnings[0]
        assert calls == [
            (["small.md", "large.md"], ["local-tiktoken"]),
            (["large.md"], ["claude-opus-5", "local-tiktoken"]),
        ]


def test_shipped_policy_covers_every_reachable_tokenizer_family():
    config = json.loads((REPO_ROOT / ".file-size-limits.json").read_text())
    for rule in config["rules"]:
        methods = get_token_methods(config, rule)
        reachable = {"tiktoken" if method == "local-tiktoken" else "anthropic" for method in methods}
        configured = set(rule["max_tokens"])
        assert reachable <= configured, f"{rule['pattern']} lacks limits for {reachable - configured}"


def test_shipped_prose_fallback_limits_preserve_a_two_x_safety_ratio():
    config = json.loads((REPO_ROOT / ".file-size-limits.json").read_text())
    for rule in config["rules"]:
        max_tokens = rule["max_tokens"]
        if "anthropic" not in max_tokens:
            continue
        assert max_tokens["tiktoken"] * 2 <= max_tokens["anthropic"]
        target_tokens = rule.get("target_tokens")
        if target_tokens:
            assert target_tokens["tiktoken"] * 2 <= target_tokens["anthropic"]


def test_shipped_policy_has_no_stale_probe_knobs():
    config = json.loads((REPO_ROOT / ".file-size-limits.json").read_text())
    for rule in config["rules"]:
        assert "provider_probe_local_tokens" not in rule
        assert "authoritative_required_local_tokens" not in rule
