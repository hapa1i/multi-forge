"""Tests for supervisor shadow sampling -- capture side (Slice 1).

Covers:
- should_sample(): determinism, rate boundaries (0 never / 1 always), threshold, seed sensitivity
- count_existing_candidates(): counts all lifecycle states, excludes the .plan.md sidecar
- capture_candidate(): raw-field freeze + plan copy, dedup across states, capture-time cap, lazy mkdir
- SupervisorConfig range validation + effective-path wrapping (Finding 4)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from forge.policy.semantic import shadow
from forge.policy.semantic.shadow import (
    candidate_hash,
    capture_candidate,
    count_existing_candidates,
    should_sample,
)
from forge.policy.types import ActionContext
from forge.session.effective import compute_effective_intent
from forge.session.exceptions import InvalidOverrideValueError
from forge.session.models import SupervisorConfig, create_session_state

# --- Fixtures ---


def _ctx(session: str = "sess", **kw: object) -> ActionContext:
    return ActionContext(
        origin="claude_code",
        event="PreToolUse.Write",
        tool_name=str(kw.get("tool_name", "Write")),
        tool_args=dict(kw.get("tool_args", {"file_path": "f.py", "content": "x"})),  # type: ignore[call-overload]
        repo_root="/repo",
        session_name=session,
        target_path=str(kw.get("target_path", "f.py")),
        new_content=kw.get("new_content", "x"),  # type: ignore[arg-type]
        raw_diff=kw.get("raw_diff"),  # type: ignore[arg-type]
    )


def _cfg(tmp_path: Path, **kw: object) -> SupervisorConfig:
    plan = tmp_path / "plan.md"
    if not plan.exists():
        plan.write_text("# Plan\nDo the thing.")
    defaults: dict[str, object] = {
        "resume_id": "rid",
        "forge_root": str(tmp_path),
        "plan_override_path": str(plan),
        "cascade": True,
        "shadow_sample_rate": 1.0,
        "shadow_max_per_session": 10,
    }
    defaults.update(kw)
    return SupervisorConfig(**defaults)  # type: ignore[arg-type]


def _bucket(seed: str, session: str, cache_key: str) -> float:
    key = f"{seed}|{session}|{cache_key}".encode()
    return int(hashlib.sha256(key).hexdigest()[:8], 16) / 0xFFFFFFFF


def _shadow_dir(tmp_path: Path, session: str = "sess") -> Path:
    return tmp_path / ".forge" / "artifacts" / session / "shadow"


# --- should_sample ---


class TestShouldSample:
    def test_determinism(self) -> None:
        c = SupervisorConfig(resume_id="r", shadow_sample_rate=0.5)
        ctx = _ctx()
        assert should_sample(c, ctx, "k") == should_sample(c, ctx, "k")

    def test_rate_zero_never(self) -> None:
        c = SupervisorConfig(resume_id="r", shadow_sample_rate=0.0)
        assert should_sample(c, _ctx(), "anything") is False

    def test_rate_one_always(self) -> None:
        c = SupervisorConfig(resume_id="r", shadow_sample_rate=1.0)
        assert should_sample(c, _ctx(), "anything") is True

    def test_threshold(self) -> None:
        # Find a cache_key whose bucket sits comfortably mid-range, then bracket it.
        key = next(k for k in (f"k{i}" for i in range(100)) if 0.2 < _bucket("", "sess", k) < 0.8)
        b = _bucket("", "sess", key)
        ctx = _ctx()
        assert should_sample(SupervisorConfig(resume_id="r", shadow_sample_rate=b + 1e-6), ctx, key) is True
        assert should_sample(SupervisorConfig(resume_id="r", shadow_sample_rate=b - 1e-6), ctx, key) is False

    def test_seed_changes_bucket(self) -> None:
        assert _bucket("seed-a", "sess", "k") != _bucket("seed-b", "sess", "k")

    def test_clamps_out_of_range_defensively(self) -> None:
        # __post_init__ rejects these, but should_sample must also be safe if one slips in via object.__setattr__.
        c = SupervisorConfig(resume_id="r")
        object.__setattr__(c, "shadow_sample_rate", 5.0)
        assert should_sample(c, _ctx(), "k") is True
        object.__setattr__(c, "shadow_sample_rate", -1.0)
        assert should_sample(c, _ctx(), "k") is False


# --- count_existing_candidates ---


class TestCountExisting:
    def test_empty_or_missing(self, tmp_path: Path) -> None:
        assert count_existing_candidates(tmp_path / "nope") == 0
        (tmp_path / "empty").mkdir()
        assert count_existing_candidates(tmp_path / "empty") == 0

    def test_counts_all_states_excludes_sidecar(self, tmp_path: Path) -> None:
        d = tmp_path / "shadow"
        d.mkdir()
        (d / "aaa.json").write_text("{}")  # pending
        (d / "bbb.processing").write_text("{}")  # claimed
        (d / "ccc.done").write_text("{}")  # terminal
        (d / "aaa.plan.md").write_text("plan")  # sidecar -- not a record
        (d / "bbb.plan.md").write_text("plan")  # sidecar -- not a record
        assert count_existing_candidates(d) == 3  # aaa, bbb, ccc -- not the .plan.md files

    def test_distinct_stems(self, tmp_path: Path) -> None:
        d = tmp_path / "shadow"
        d.mkdir()
        # same stem in two states should count once
        (d / "xxx.json").write_text("{}")
        (d / "xxx.processing").write_text("{}")
        assert count_existing_candidates(d) == 1


# --- capture_candidate ---


class TestCaptureCandidate:
    def test_freezes_raw_fields_and_plan(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        ctx = _ctx(new_content="print('hi')", raw_diff="@@ -1 +1 @@", tool_args={"a": 1})
        out = capture_candidate(
            cfg,
            ctx,
            cache_key="ck1",
            tier1_reason="looks aligned",
            checker_model="google/gemini-3.5-flash",
            checker_provider="openrouter",
            checker_budget_tokens=32000,
            checker_prompt_version=1,
        )
        assert out is not None and out.exists()
        data = json.loads(out.read_text())
        # raw replay inputs
        assert data["new_content"] == "print('hi')"
        assert data["raw_diff"] == "@@ -1 +1 @@"
        assert data["tool_args"] == {"a": 1}
        assert data["target_path"] == "f.py"
        # routing snapshot
        assert data["resume_id"] == "rid"
        assert data["direct"] is False
        assert data["fork_session"] is True
        assert data["supervisor_runtime"] is None  # v2 field always serialized; None == claude lane
        # dims + audit + lifecycle
        assert data["tier1_reason"] == "looks aligned"
        assert data["checker_model"] == "google/gemini-3.5-flash"
        assert data["checker_prompt_version"] == 1
        assert data["status"] == "pending"
        # frozen plan copied to sidecar
        assert data["plan_snapshot_hash"]
        sidecar = out.parent / data["plan_snapshot_file"]
        assert sidecar.exists() and "Do the thing." in sidecar.read_text()

    def test_idempotent_same_cache_key(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        first = capture_candidate(
            cfg,
            _ctx(),
            cache_key="dup",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        second = capture_candidate(
            cfg,
            _ctx(),
            cache_key="dup",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert first is not None
        assert second is None  # deduped
        assert count_existing_candidates(_shadow_dir(tmp_path)) == 1

    def test_dedup_across_processing_state(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        out = capture_candidate(
            cfg,
            _ctx(),
            cache_key="ck",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert out is not None
        # simulate the drain claiming it
        out.rename(out.with_suffix(".processing"))
        again = capture_candidate(
            cfg,
            _ctx(),
            cache_key="ck",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert again is None  # still deduped even though no .json exists

    def test_cap_enforced_at_capture(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path, shadow_max_per_session=2)
        made = []
        for i in range(5):
            p = capture_candidate(
                cfg,
                _ctx(),
                cache_key=f"ck{i}",
                tier1_reason="r",
                checker_model="m",
                checker_provider=None,
                checker_budget_tokens=1,
                checker_prompt_version=1,
            )
            if p is not None:
                made.append(p)
        assert len(made) == 2
        assert count_existing_candidates(_shadow_dir(tmp_path)) == 2

    def test_cap_counts_processing_state(self, tmp_path: Path) -> None:
        """A candidate mid-.processing still counts toward the cap (no undercount)."""
        cfg = _cfg(tmp_path, shadow_max_per_session=1)
        out = capture_candidate(
            cfg,
            _ctx(),
            cache_key="first",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert out is not None
        out.rename(out.with_suffix(".processing"))  # drain claims it
        # cap is 1 and one .processing exists -> a NEW distinct candidate must be refused
        blocked = capture_candidate(
            cfg,
            _ctx(),
            cache_key="second",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert blocked is None

    def test_relative_plan_path_resolved_against_forge_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative plan_override_path anchors at forge_root (mirrors load_plan_override),
        NOT the hook CWD -- otherwise the plan copy is silently skipped and the replay runs
        with no plan."""
        (tmp_path / "plans").mkdir()
        (tmp_path / "plans" / "plan.md").write_text("# Plan\nDo the thing.")
        # Capture from an UNRELATED cwd: a CWD-relative resolution would miss the plan.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        cfg = SupervisorConfig(
            resume_id="rid",
            forge_root=str(tmp_path),
            plan_override_path="plans/plan.md",  # relative
            cascade=True,
            shadow_sample_rate=1.0,
        )
        out = capture_candidate(
            cfg,
            _ctx(),
            cache_key="rel",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert out is not None
        data = json.loads(out.read_text())
        assert data["plan_snapshot_file"], "relative plan should still be copied"
        sidecar = out.parent / data["plan_snapshot_file"]
        assert sidecar.is_file() and "Do the thing." in sidecar.read_text()

    def test_lazy_mkdir(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        assert not _shadow_dir(tmp_path).exists()  # not created until a capture happens
        capture_candidate(
            cfg,
            _ctx(),
            cache_key="ck",
            tier1_reason="r",
            checker_model="m",
            checker_provider=None,
            checker_budget_tokens=1,
            checker_prompt_version=1,
        )
        assert _shadow_dir(tmp_path).is_dir()

    def test_no_forge_root_returns_none(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path, forge_root=None)
        assert (
            capture_candidate(
                cfg,
                _ctx(),
                cache_key="ck",
                tier1_reason="r",
                checker_model="m",
                checker_provider=None,
                checker_budget_tokens=1,
                checker_prompt_version=1,
            )
            is None
        )

    def test_candidate_hash_stable(self) -> None:
        assert candidate_hash("ck") == candidate_hash("ck")
        assert candidate_hash("ck") != candidate_hash("ck2")


# --- Config range validation (Finding 4) ---


class TestConfigValidation:
    @pytest.mark.parametrize("rate", [1.5, -0.1, 2.0])
    def test_bad_rate_rejected(self, rate: float) -> None:
        with pytest.raises(ValueError, match="shadow_sample_rate"):
            SupervisorConfig(resume_id="r", shadow_sample_rate=rate)

    @pytest.mark.parametrize("cap", [0, -1])
    def test_bad_cap_rejected(self, cap: int) -> None:
        with pytest.raises(ValueError, match="shadow_max_per_session"):
            SupervisorConfig(resume_id="r", shadow_max_per_session=cap)

    def test_valid_boundaries_accepted(self) -> None:
        SupervisorConfig(resume_id="r", shadow_sample_rate=0.0)
        SupervisorConfig(resume_id="r", shadow_sample_rate=1.0)
        SupervisorConfig(resume_id="r", shadow_max_per_session=1)

    def test_effective_path_wraps_to_typed_error(self) -> None:
        """A bad shadow rate set via override surfaces as InvalidOverrideValueError, not a raw ValueError."""
        manifest = create_session_state("test")
        manifest.overrides = {"policy": {"supervisor": {"shadow_sample_rate": 1.5}}}
        with pytest.raises(InvalidOverrideValueError):
            compute_effective_intent(manifest, strict=True, override_key="policy.supervisor.shadow_sample_rate")

    def test_schema_constant_present(self) -> None:
        # v2 (T4): ShadowCandidate gained supervisor_runtime so a codex session replays on the
        # codex lane. Old v1 records lack the field and reconstruct to None (claude) -- see
        # test_shadow_runner.test_config_absent_supervisor_runtime_defaults_to_none.
        assert shadow.SHADOW_SCHEMA_VERSION == 2
