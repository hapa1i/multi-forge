"""Tests for count-tokens method-chain resolution and fallback order."""

import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# ruff: noqa: E402
import importlib

import pytest

mod = importlib.import_module("count-tokens")
parse_methods = mod.parse_methods
resolve_methods = mod.resolve_methods
count_tokens = mod.count_tokens
LOCAL_METHOD = mod.LOCAL_METHOD
DEFAULT_MODEL = mod.DEFAULT_MODEL

SAMPLE = "hello world, this is a token counting test"

# Captured before the no_network fixture can patch it, so a test that needs the
# genuine credential-resolution path can restore it deliberately.
REAL_COUNT_ANTHROPIC = mod._count_anthropic
REAL_COUNT_GEMINI = mod._count_gemini


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if a test reaches a provider API without stubbing it."""
    monkeypatch.setattr(
        mod, "_count_anthropic", lambda text, model, key_file=None: pytest.fail("unexpected Anthropic call")
    )
    monkeypatch.setattr(mod, "_count_gemini", lambda text, model, key_file=None: pytest.fail("unexpected Gemini call"))


# -- parse_methods tests --


class TestParseMethods:
    def test_splits_on_comma(self):
        assert parse_methods("claude-opus-5,local-tiktoken") == ["claude-opus-5", "local-tiktoken"]

    def test_strips_whitespace(self):
        assert parse_methods(" claude-opus-5 , local-tiktoken ") == ["claude-opus-5", "local-tiktoken"]

    def test_drops_empty_segments(self):
        assert parse_methods("claude-opus-5,,local-tiktoken,") == ["claude-opus-5", "local-tiktoken"]

    def test_empty_string_is_empty_chain(self):
        assert parse_methods("") == []


# -- resolve_methods tests --


class TestResolveMethods:
    def test_default_appends_local_fallback(self):
        assert resolve_methods(DEFAULT_MODEL) == [DEFAULT_MODEL, LOCAL_METHOD]

    def test_default_model_is_opus_5(self):
        assert DEFAULT_MODEL == "claude-opus-5"

    def test_model_flag_builds_two_step_chain(self):
        assert resolve_methods("gemini-2.5-flash") == ["gemini-2.5-flash", LOCAL_METHOD]

    def test_methods_string_overrides_model(self):
        chain = resolve_methods("claude-opus-5", methods="gemini-2.5-flash,local-tiktoken")
        assert chain == ["gemini-2.5-flash", LOCAL_METHOD]

    def test_methods_list_accepted(self):
        assert resolve_methods("claude-opus-5", methods=["gpt-4"]) == ["gpt-4"]

    def test_local_beats_methods(self):
        chain = resolve_methods("claude-opus-5", local=True, methods="gemini-2.5-flash")
        assert chain == [LOCAL_METHOD]

    def test_blank_methods_falls_back_to_model_chain(self):
        assert resolve_methods("claude-opus-5", methods=" , ") == ["claude-opus-5", LOCAL_METHOD]


# -- count_tokens chain-walking tests --


class TestCountTokensChain:
    def test_first_working_method_wins(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: 123)
        count, method, _family = count_tokens(SAMPLE, methods=["claude-opus-5", LOCAL_METHOD])
        assert count == 123
        assert "anthropic API (claude-opus-5)" == method

    def test_falls_through_when_method_unavailable(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: None)
        count, method, _family = count_tokens(SAMPLE, methods=["claude-opus-5", LOCAL_METHOD])
        assert count > 0
        assert method == "tiktoken local (cl100k_base)"

    def test_openai_step_reports_the_encoding_it_used(self):
        count, method, _family = count_tokens(SAMPLE, methods=["gpt-4o"])
        assert count > 0
        assert method == "tiktoken (gpt-4o / o200k_base)"

    def test_walks_past_multiple_dead_methods(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: None)
        monkeypatch.setattr(mod, "_count_gemini", lambda text, model, key_file=None: 77)
        count, method, _family = count_tokens(SAMPLE, methods=["claude-opus-5", "gemini-2.5-flash", LOCAL_METHOD])
        assert count == 77
        assert "gemini API" in method

    def test_unknown_model_is_skipped_not_guessed(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: 55)
        count, _, _family = count_tokens(SAMPLE, methods=["mystery-model-9", "claude-opus-5"])
        assert count == 55

    def test_exhausted_chain_still_returns_a_count(self):
        """A chain with no usable method degrades to tiktoken rather than failing."""
        count, method, _family = count_tokens(SAMPLE, methods=["mystery-model-9"])
        assert count > 0
        assert "cl100k_base fallback" in method

    def test_local_flag_never_calls_provider(self):
        # The no_network fixture fails the test if a provider is reached.
        count, method, _family = count_tokens(SAMPLE, "claude-opus-5", local=True)
        assert count > 0
        assert method.startswith("tiktoken local")


# -- --local must still honour --model's tokenizer --


class TestLocalHonoursModel:
    def test_local_uses_model_specific_encoding(self):
        """--local --model gpt-4o must use o200k_base, not the generic fallback."""
        _, method, _family = count_tokens(SAMPLE, "gpt-4o", local=True)
        assert method == "tiktoken local (o200k_base)"

    def test_local_falls_back_for_non_tiktoken_model(self):
        _, method, _family = count_tokens(SAMPLE, "claude-opus-5", local=True)
        assert method == "tiktoken local (cl100k_base)"

    def test_bare_local_step_in_a_chain_stays_generic(self, monkeypatch):
        """--model only steers the local step under --local, not inside a chain."""
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: None)
        _, method, _family = count_tokens(SAMPLE, "gpt-4o", methods=["claude-opus-5", LOCAL_METHOD])
        assert method == "tiktoken local (cl100k_base)"


# -- an unloadable encoding must not abort the chain --


class TestEncodingLoadFailure:
    def test_fetch_failure_returns_none_instead_of_raising(self, monkeypatch):
        """tiktoken raises whatever its HTTP layer raises when offline."""
        import tiktoken

        def offline(model):
            raise ConnectionError("cannot fetch BPE data")

        monkeypatch.setattr(tiktoken, "encoding_for_model", offline)
        assert mod._load_encoding("gpt-4o") is None

    def test_unknown_model_still_uses_fallback_encoding(self):
        assert mod._load_encoding("claude-opus-5").name == "cl100k_base"

    def test_chain_continues_past_an_unloadable_encoding(self, monkeypatch):
        """Repro: gpt-4o's encoding cannot be fetched, local-tiktoken still works."""
        real_load = mod._load_encoding

        def flaky(model=None):
            return None if model == "gpt-4o" else real_load(model)

        monkeypatch.setattr(mod, "_load_encoding", flaky)
        count, method, _family = count_tokens(SAMPLE, methods=["gpt-4o", LOCAL_METHOD])
        assert count > 0
        assert method == "tiktoken local (cl100k_base)"

    def test_exits_cleanly_when_no_encoding_is_loadable(self, monkeypatch):
        monkeypatch.setattr(mod, "_load_encoding", lambda model=None: None)
        with pytest.raises(SystemExit):
            count_tokens(SAMPLE, methods=["mystery-model-9"])


# -- key file fallback --


class TestReadKeyFile:
    def test_reads_and_strips(self, tmp_path):
        f = tmp_path / "key"
        f.write_text("sk-secret-value\n")
        assert mod._read_key_file(f) == "sk-secret-value"

    def test_missing_file_is_none(self, tmp_path):
        assert mod._read_key_file(tmp_path / "absent") is None

    def test_empty_file_is_none(self, tmp_path):
        f = tmp_path / "key"
        f.write_text("   \n")
        assert mod._read_key_file(f) is None

    def test_none_path_is_none(self):
        assert mod._read_key_file(None) is None

    def test_directory_instead_of_file_is_none(self, tmp_path):
        """A bad path must degrade, not raise IsADirectoryError."""
        assert mod._read_key_file(tmp_path) is None

    def test_expands_user_tilde(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".keys").mkdir()
        (tmp_path / ".keys" / "anthropic_api_key").write_text("from-home\n")
        assert mod._read_key_file("~/.keys/anthropic_api_key") == "from-home"


class TestAnthropicCredentialResolution:
    """_count_anthropic picks a credential source; the SDK call itself is stubbed."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    @staticmethod
    def _capture(monkeypatch):
        """Replace anthropic.Anthropic so we can inspect the kwargs it receives."""
        seen = {}

        class FakeClient:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                self.messages = self

            def count_tokens(self, model, messages):
                return type("R", (), {"input_tokens": 999})()

        anthropic = types.ModuleType("anthropic")
        anthropic.Anthropic = FakeClient
        anthropic.errors = types.SimpleNamespace(APIError=type("APIError", (Exception,), {}))
        monkeypatch.setitem(sys.modules, "anthropic", anthropic)
        return seen

    def test_no_env_and_no_file_returns_none(self, monkeypatch, tmp_path):
        self._capture(monkeypatch)
        assert REAL_COUNT_ANTHROPIC(SAMPLE, "claude-opus-5", tmp_path / "absent") is None

    def test_falls_back_to_key_file(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        f = tmp_path / "key"
        f.write_text("sk-from-file\n")
        assert REAL_COUNT_ANTHROPIC(SAMPLE, "claude-opus-5", f) == 999
        assert seen["api_key"] == "sk-from-file"
        assert seen["max_retries"] == 1

    def test_env_var_wins_over_key_file(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        f = tmp_path / "key"
        f.write_text("sk-from-file\n")
        assert REAL_COUNT_ANTHROPIC(SAMPLE, "claude-opus-5", f) == 999
        # Env branch defers to the SDK's own resolution rather than forcing api_key.
        assert "api_key" not in seen

    def test_auth_token_is_not_forced_into_api_key(self, monkeypatch, tmp_path):
        """ANTHROPIC_AUTH_TOKEN is a bearer token; passing it as api_key breaks it."""
        seen = self._capture(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "bearer-token")
        f = tmp_path / "key"
        f.write_text("sk-from-file\n")
        assert REAL_COUNT_ANTHROPIC(SAMPLE, "claude-opus-5", f) == 999
        assert "api_key" not in seen

    def test_key_file_flows_through_the_chain(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        f = tmp_path / "key"
        f.write_text("sk-threaded\n")
        # Restore the real function over the autouse no_network stub: the SDK
        # client is faked above, so no request actually leaves the process.
        monkeypatch.setattr(mod, "_count_anthropic", REAL_COUNT_ANTHROPIC)
        count, method, _family = count_tokens(SAMPLE, methods=["claude-opus-5"], key_file=f)
        assert count == 999
        assert method == "anthropic API (claude-opus-5)"
        assert seen["api_key"] == "sk-threaded"


class TestGeminiCredentialResolution:
    """Same env-then-file precedence as Anthropic, via GEMINI_API_KEY."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    @staticmethod
    def _capture(monkeypatch):
        seen = {}

        class FakeClient:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                self.models = self

            def count_tokens(self, model, contents):
                return type("R", (), {"total_tokens": 42})()

        google = types.ModuleType("google")
        genai = types.ModuleType("google.genai")
        errors = types.ModuleType("google.genai.errors")
        errors.APIError = type("APIError", (Exception,), {})
        genai.Client = FakeClient
        genai.errors = errors
        google.genai = genai
        monkeypatch.setitem(sys.modules, "google", google)
        monkeypatch.setitem(sys.modules, "google.genai", genai)
        monkeypatch.setitem(sys.modules, "google.genai.errors", errors)
        return seen

    def test_no_env_and_no_file_returns_none(self, monkeypatch, tmp_path):
        self._capture(monkeypatch)
        assert REAL_COUNT_GEMINI(SAMPLE, "gemini-2.5-flash", tmp_path / "absent") is None

    def test_falls_back_to_key_file(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        f = tmp_path / "key"
        f.write_text("gem-from-file\n")
        assert REAL_COUNT_GEMINI(SAMPLE, "gemini-2.5-flash", f) == 42
        assert seen["api_key"] == "gem-from-file"
        assert seen["http_options"]["retry_options"] == {"attempts": 2}

    def test_env_var_wins_over_key_file(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "gem-from-env")
        f = tmp_path / "key"
        f.write_text("gem-from-file\n")
        assert REAL_COUNT_GEMINI(SAMPLE, "gemini-2.5-flash", f) == 42
        assert seen["api_key"] == "gem-from-env"

    def test_key_file_flows_through_the_chain(self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        f = tmp_path / "key"
        f.write_text("gem-threaded\n")
        monkeypatch.setattr(mod, "_count_gemini", REAL_COUNT_GEMINI)
        count, method, _family = count_tokens(SAMPLE, methods=["gemini-2.5-flash"], gemini_key_file=f)
        assert count == 42
        assert method == "gemini API (gemini-2.5-flash)"
        assert seen["api_key"] == "gem-threaded"


class TestOpenAINeedsNoKey:
    def test_openai_counts_without_any_credential(self, monkeypatch, tmp_path):
        """tiktoken is OpenAI's own tokenizer -- exact, local, and keyless.

        There is deliberately no --openai-key-file: OpenAI exposes no token
        counting endpoint, so a key would be dead configuration.
        """
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        count, method, _family = count_tokens(SAMPLE, methods=["gpt-4o"])
        assert count > 0
        assert method == "tiktoken (gpt-4o / o200k_base)"

    def test_no_openai_key_file_constant_exists(self):
        assert not hasattr(mod, "DEFAULT_OPENAI_KEY_FILE")


class TestTokenizerFamily:
    def test_local_step_reports_tiktoken(self):
        _, _, family = count_tokens(SAMPLE, methods=[LOCAL_METHOD])
        assert family == mod.FAMILY_TIKTOKEN

    def test_openai_step_reports_tiktoken(self):
        _, _, family = count_tokens(SAMPLE, methods=["gpt-4o"])
        assert family == mod.FAMILY_TIKTOKEN

    def test_anthropic_step_reports_anthropic(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: 42)
        _, _, family = count_tokens(SAMPLE, methods=["claude-opus-5"])
        assert family == mod.FAMILY_ANTHROPIC

    def test_gemini_step_reports_gemini(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_gemini", lambda text, model, key_file=None: 42)
        _, _, family = count_tokens(SAMPLE, methods=["gemini-2.5-flash"])
        assert family == mod.FAMILY_GEMINI

    def test_provider_fallback_reports_the_tokenizer_that_ran(self, monkeypatch):
        monkeypatch.setattr(mod, "_count_anthropic", lambda text, model, key_file=None: None)
        _, method, family = count_tokens(SAMPLE, methods=["claude-opus-5", LOCAL_METHOD])
        assert method.startswith("tiktoken")
        assert family == mod.FAMILY_TIKTOKEN


def test_json_cli_reports_count_method_and_family(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["count-tokens", "--json"])
    monkeypatch.setattr(mod, "_read_input", lambda files: (SAMPLE, "stdin"))
    monkeypatch.setattr(
        mod,
        "count_tokens",
        lambda *args, **kwargs: (17, "anthropic API (claude-opus-5)", mod.FAMILY_ANTHROPIC),
    )

    mod.main()

    assert json.loads(capsys.readouterr().out) == {
        "tokens": 17,
        "method": "anthropic API (claude-opus-5)",
        "family": "anthropic",
    }


@pytest.mark.parametrize("text", ["", "   \n\t  \n"])
def test_json_cli_stays_machine_readable_for_empty_input(monkeypatch, capsys, text):
    monkeypatch.setattr(sys, "argv", ["count-tokens", "--json"])
    monkeypatch.setattr(mod, "_read_input", lambda files: (text, "stdin"))

    mod.main()

    assert json.loads(capsys.readouterr().out) == {
        "tokens": 0,
        "method": "empty input",
        "family": "none",
    }


def test_per_file_json_counts_named_files_independently(monkeypatch, capsys, tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first input")
    second.write_text("")
    seen = []

    def fake_count(text, *args, **kwargs):
        seen.append(text)
        return 7, "tiktoken local (cl100k_base)", mod.FAMILY_TIKTOKEN

    monkeypatch.setattr(
        sys,
        "argv",
        ["count-tokens", "--per-file", "--json", str(first), str(second)],
    )
    monkeypatch.setattr(mod, "count_tokens", fake_count)

    mod.main()

    payloads = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert seen == ["first input"]
    assert payloads == [
        {
            "path": str(first),
            "tokens": 7,
            "method": "tiktoken local (cl100k_base)",
            "family": "tiktoken",
        },
        {"path": str(second), "tokens": 0, "method": "empty input", "family": "none"},
    ]


def test_per_file_rejects_stdin(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["count-tokens", "--per-file", "--json", "-"])

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 2


def test_provider_retry_budget_is_bounded_for_hook_latency():
    assert mod._API_MAX_RETRIES == 1
