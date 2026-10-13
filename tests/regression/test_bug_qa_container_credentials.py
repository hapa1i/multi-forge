"""Reusing QA must compare actual provider credentials without disclosing their values."""

import hashlib
import shlex

import pytest

from tests.src.skills.test_qa_start_container import (
    _fresh_container_docker,
    _run,
    _running_container_docker,
    _wheel,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("variable", ["CODEX_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"])
@pytest.mark.parametrize("changed", [False, True])
def test_credential_comparison_controls_container_reuse(tmp_path, variable, changed):
    wheel = _wheel(tmp_path)
    # Execute the real in-container comparison against either unchanged or stale environment.
    environment = f"{variable}=stale-synthetic-value " if changed else ""
    transport = (
        'if [[ "$*" == *"json.load(sys.stdin)"* ]]; then\n'
        '  for check in "$@"; do :; done\n'
        f'  exec env {environment}python3 -c "$check"\n'
        "fi\n" + _running_container_docker(wheel)
    )
    result = _run(tmp_path, ["--wheel", str(wheel)], transport)
    assert result.returncode == (3 if changed else 0), result.stderr
    if changed:
        assert "credentials or provider configuration changed" in result.stderr
        assert "--reset" in result.stderr
    assert "stale-synthetic-value" not in result.stderr + result.stdout
    assert "test-codex-key" not in result.stderr + result.stdout


@pytest.mark.parametrize("source_state", ["unchanged", "changed", "unrecorded"])
def test_explicit_auth_reuse_preserves_refresh_and_rejects_changed_source(tmp_path, source_state):
    wheel = _wheel(tmp_path)
    source = tmp_path / "selected-auth.json"
    source.write_text('{"tokens":{"refresh_token":"original-synthetic-token"}}')
    container_home = tmp_path / "container-codex"
    container_home.mkdir()
    auth = container_home / "auth.json"
    auth.write_text('{"tokens":{"refresh_token":"refreshed-synthetic-token"}}')
    if source_state != "unrecorded":
        (container_home / ".forge-qa-auth-source.sha256").write_text(hashlib.sha256(source.read_bytes()).hexdigest())
    if source_state == "changed":
        source.write_text('{"tokens":{"refresh_token":"different-account-token"}}')
    copied = tmp_path / "copied"
    transport = (
        'if [[ "$*" == *"json.load(sys.stdin)"* ]]; then\n'
        '  for check in "$@"; do :; done\n'
        f'  check="${{check//\\/root\\/\\.codex/{container_home}}}"\n'
        '  exec env -u CODEX_API_KEY python3 -c "$check"\n'
        "fi\n"
        f'if [[ "$1" == cp ]]; then touch {shlex.quote(str(copied))}; fi\n'
        + _running_container_docker(wheel, codex_auth_mode="explicit-file")
    )
    result = _run(tmp_path, ["--wheel", str(wheel), "--codex-auth", str(source)], transport)
    assert result.returncode == (0 if source_state == "unchanged" else 3), result.stderr
    assert not copied.exists(), "Reuse must retain refreshed credentials and cannot replace the selected account"
    assert "refreshed-synthetic-token" in auth.read_text()
    if source_state != "unchanged":
        assert "--reset" in result.stderr
    assert "synthetic-token" not in result.stderr + result.stdout


def test_fresh_explicit_auth_records_private_ingress_digest(tmp_path):
    wheel = _wheel(tmp_path)
    source = tmp_path / "selected-auth.json"
    source.write_text('{"tokens":{"refresh_token":"synthetic-token"}}')
    container_home = tmp_path / "container-codex"
    container_home.mkdir()
    transport = (
        f'if [[ "$1" == cp ]]; then cp "$2" {shlex.quote(str(container_home / "auth.json"))}; exit; fi\n'
        'if [[ "$*" == *"/opt/forge-qa/bin/python" && "$*" == *" -i "* ]]; then\n'
        '  check="$(cat)"\n'
        f'  check="${{check//\\/root\\/\\.codex/{container_home}}}"\n'
        '  exec python3 -c "$check"\n'
        "fi\n" + _fresh_container_docker(tmp_path / "docker.log")
    )
    result = _run(tmp_path, ["--wheel", str(wheel), "--codex-auth", str(source)], transport)
    assert result.returncode == 0, result.stderr
    marker = container_home / ".forge-qa-auth-source.sha256"
    assert marker.read_text() == hashlib.sha256(source.read_bytes()).hexdigest()
    assert marker.stat().st_mode & 0o777 == 0o600
    assert "synthetic-token" not in result.stderr + result.stdout
