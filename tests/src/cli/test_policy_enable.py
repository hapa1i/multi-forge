"""Tests for `forge policy enable` CLI behavior (A3: fail loud on no bundle)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch, fixture

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state


@fixture
def runner():
    return CliRunner()


class TestEnableRequiresBundle:
    def test_bare_enable_fails_loud(self, runner: CliRunner) -> None:
        """Bare `policy enable` is a loud stderr error, not a silent stdout no-op.

        A3: the old behavior printed a warning on stdout and exited 0. Both the terminal
        and interactive surfaces now require explicit bundles; the terminal form writes
        intent, while `%policy enable` writes overrides.
        """
        result = runner.invoke(main, ["policy", "enable"])
        err = " ".join(result.stderr.split())

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "No policy bundles specified." in err
        # The recovery tip must name BOTH bundles, not degrade to one.
        assert "Tip:" in err
        assert "--bundle tdd" in err
        assert "coding_standards" in err

    def test_help_lists_bundle_choices(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["policy", "enable", "--help"])

        assert result.exit_code == 0
        assert "--bundle" in result.output
        assert "tdd" in result.output
        assert "coding_standards" in result.output


class TestPolicyTargetCompatibility:
    @staticmethod
    def _seed_target(tmp_path: Path, monkeypatch: MonkeyPatch) -> tuple[Path, Path, SessionStore]:
        caller = tmp_path / "caller"
        target = tmp_path / "target"
        for root in (caller, target):
            (root / ".git").mkdir(parents=True)
            (root / ".forge").mkdir()
        monkeypatch.chdir(caller)

        state = create_session_state("worker", worktree_path=str(target))
        state.forge_root = str(target)
        store = SessionStore(str(target), "worker")
        store.write(state)
        IndexStore().add_session(
            name="worker",
            worktree_path=str(target),
            project_root=str(caller),
            forge_root=str(target),
            checkout_root=str(target),
            relative_path=".",
        )
        return caller, target, store

    def test_enable_refuses_incompatible_target_without_mutation(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        _caller, target, store = self._seed_target(tmp_path, monkeypatch)
        before = store.manifest_path.read_bytes()
        (target / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(main, ["policy", "enable", "--bundle", "tdd", "--session", "worker"])

        assert result.exit_code == 1
        assert "requires Forge" in result.output
        assert store.manifest_path.read_bytes() == before

    def test_enable_uses_compatible_target_despite_incompatible_caller(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        caller, _target, store = self._seed_target(tmp_path, monkeypatch)
        (caller / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(main, ["policy", "enable", "--bundle", "tdd", "--session", "worker"])

        assert result.exit_code == 0, result.output
        policy = store.read().intent.policy
        assert policy is not None
        assert policy.enabled is True
