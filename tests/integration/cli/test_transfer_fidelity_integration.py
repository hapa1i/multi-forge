"""Exercise transfer regeneration, review and fresh launch with native tool-result shapes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

FORGE = (
    "cd /workspace && PYTHON_DOTENV_DISABLED=1 ANTHROPIC_API_KEY=sk-ant-fixture " "EDITOR=/tmp/fidelity-editor forge "
)


@pytest.mark.parametrize("strategy", ["structured", "full"])
def test_transfer_fidelity_reaches_reviewed_child(mock_claude_workspace: ContainerLike, strategy: str) -> None:
    workspace = mock_claude_workspace
    transcript = (Path(__file__).resolve().parents[2] / "fixtures" / "transcript_delegation.jsonl").read_text()
    written = workspace.write_file("/workspace/delegation.jsonl", transcript)
    assert written.returncode == 0, written.stderr
    published = workspace.exec("""cd /forge && PYTHON_DOTENV_DISABLED=1 /forge/.venv/bin/python - <<'PY'
from forge.session import IndexStore
from forge.session.models import create_session_state
from tests.fixtures.session_state import publish_session

state = create_session_state("fidelity-parent", worktree_path="/workspace")
state.confirmed.claude_session_id = "00000000-0000-4000-8000-000000000001"
state.confirmed.confirmed_by = "hook:SessionStart:startup"
state.confirmed.transcript_path = "/workspace/delegation.jsonl"
publish_session(IndexStore(), state, "/workspace", forge_root="/workspace")
PY""")
    assert published.returncode == 0, published.stdout + published.stderr
    editor = workspace.write_file("/tmp/fidelity-editor", '#!/bin/sh\nprintf "\\nReviewed transfer.\\n" >> "$1"\n')
    assert editor.returncode == 0, editor.stderr
    executable = workspace.exec("chmod +x /tmp/fidelity-editor")
    assert executable.returncode == 0, executable.stderr

    regenerated = workspace.exec(FORGE + f"session transfer regenerate fidelity-parent --strategy {strategy}")
    assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
    shown = workspace.exec(FORGE + "session transfer show fidelity-parent --json")
    assert shown.returncode == 0, shown.stdout + shown.stderr
    content = json.loads(shown.stdout)["content"]
    assert "Preserve the review note." in content
    assert "[result: The parser preserves the first finding.\nThe second finding follows the image.]" in content
    if strategy == "full":
        assert "Agent(type=Explore, description=Inspect transfer fidelity, prompt=" in content
        assert "SendMessage(recipient=reviewer, summary=Transfer findings, content=" in content
    else:
        assert "Agent(" not in content
        assert "SendMessage(" not in content
    assert "SU1BR0VfUEFZTE9BRA==" not in content

    resumed = workspace.exec(
        FORGE + f"session resume fidelity-parent --fresh --review --strategy {strategy} --child-name fidelity-child",
        timeout=30,
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    child_path = "/workspace/.forge/prev_sessions/fidelity-parent/children/fidelity-child.md"
    child = workspace.read_file(child_path)
    assert "Preserve the review note." in child
    assert "[result: The parser preserves the first finding.\nThe second finding follows the image.]" in child
    if strategy == "full":
        assert "Agent(type=Explore" in child
        assert "SendMessage(recipient=reviewer" in child
    else:
        assert "Agent(" not in child
        assert "SendMessage(" not in child
    assert "SU1BR0VfUEFZTE9BRA==" not in child
    launch_path = "/workspace/.forge/launch-context/fidelity-child.md"
    assert f"--append-system-prompt-file {launch_path}" in workspace.read_file("/tmp/claude_invocations.log")
    launch = workspace.read_file(launch_path)
    assert "The second finding follows the image." in launch
    assert "Reviewed transfer." in launch

    edited = workspace.exec(FORGE + "session transfer edit fidelity-parent --child fidelity-child")
    assert edited.returncode == 0, edited.stdout + edited.stderr
    child_view = workspace.exec(FORGE + "session transfer show fidelity-parent --child fidelity-child --json")
    assert child_view.returncode == 0, child_view.stdout + child_view.stderr
    assert "Reviewed transfer." in json.loads(child_view.stdout)["content"]

    late_result = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "content": [{"type": "text", "text": "Late transfer finding"}]},
                {"type": "text", "text": "Additional review note"},
            ],
        },
    }
    updated = workspace.write_file("/workspace/delegation.jsonl", transcript + json.dumps(late_result) + "\n")
    assert updated.returncode == 0, updated.stderr
    regenerated = workspace.exec(FORGE + f"session transfer regenerate fidelity-parent --strategy {strategy}")
    assert regenerated.returncode == 0, regenerated.stdout + regenerated.stderr
    difference = workspace.exec(FORGE + "session transfer diff fidelity-parent --child fidelity-child")
    assert difference.returncode == 0, difference.stdout + difference.stderr
    assert "Late transfer finding" in difference.stdout
    assert workspace.read_file(child_path) == child


# Defines launch(prompt): the real interactive launcher against a shim that records its positional prompt.
_MOCK_CODEX_LAUNCH = r"""
import os
from pathlib import Path

from forge.core.reactive.env import RunIdentity
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session.codex_invoke import build_codex_interactive_launch, invoke_codex_interactive

bin_dir = Path('/workspace/fidelity-bin')
bin_dir.mkdir()
shim = bin_dir / 'codex'
shim.write_text('''#!/bin/sh
if [ "$1" = "--version" ]; then
    echo 'codex-cli 0.161.0'
    exit 0
fi
for prompt do :; done
printf '%s' "$prompt" > /workspace/codex-prompt.txt
''')
shim.chmod(0o755)
os.environ['PATH'] = str(bin_dir) + os.pathsep + os.environ['PATH']
preflight = CodexPreflight(
    installed=True, version='0.161.0', version_ok=True,
    auth_method='chatgpt_tokens', auth_source='codex_store', billing_mode='subscription_quota',
    ready=True, blocking_reason=None, hook_seam='enrollment_gated',
    proxy_responses='native_direct', doctor_status='ok',
)


def launch_options(extra_args=()):
    return dict(
        preflight=preflight, session_name='fidelity-child', forge_root='/workspace', cwd='/workspace',
        run_identity=RunIdentity(run_id='run_aaaaaaaaaaaa', parent_run_id=None, root_run_id='run_aaaaaaaaaaaa'),
        extra_args=extra_args,
    )


def launch(prompt, extra_args=()):
    return invoke_codex_interactive(**launch_options(extra_args), initial_prompt=prompt)


def prompt_limit(extra_args=()):
    from forge.session.codex_invoke import max_initial_prompt_bytes
    options = launch_options(extra_args)
    del options['cwd']
    argv, env = build_codex_interactive_launch(**options)
    return max_initial_prompt_bytes(argv=argv, env=env)
"""


def _run_check(workspace: ContainerLike, script: str) -> None:
    command = f"cd /forge && PYTHON_DOTENV_DISABLED=1 /forge/.venv/bin/python - <<'CHECK'\n{script}\nCHECK"
    result = workspace.exec(command)
    assert result.returncode == 0, result.stdout + result.stderr


def test_tool_heavy_structured_transfer_launches_on_linux(clean_workspace: ContainerLike) -> None:
    _run_check(
        clean_workspace,
        _MOCK_CODEX_LAUNCH + r"""
import json

from forge.core.ops.codex_bridge import compose_codex_interactive_context
from forge.session.transfer import _generate_structured_context
from tests.fixtures.transcript_delegation import tool_heavy_transcript

transcript = Path('/workspace/busy.jsonl')
transcript.write_text('\n'.join(json.dumps(entry) for entry in tool_heavy_transcript()))
content, warnings = _generate_structured_context('parent', ['parent'], transcript, None, None, None)
assert not warnings
prompt = compose_codex_interactive_context(content)
assert launch(prompt) == 0
assert Path('/workspace/codex-prompt.txt').read_text() == prompt
assert 'Review complete' in prompt
assert 'raw output' not in prompt
""",
    )


def test_initial_prompt_limit_matches_linux_exec(clean_workspace: ContainerLike) -> None:
    _run_check(
        clean_workspace,
        _MOCK_CODEX_LAUNCH + r"""
import errno
import subprocess

limit = prompt_limit()
assert limit == 32 * os.sysconf('SC_PAGE_SIZE') - 1, limit
prompt = 'é' * (limit // 2) + 'x' * (limit % 2)
assert len(prompt.encode('utf-8')) == limit
assert launch(prompt) == 0
assert Path('/workspace/codex-prompt.txt').read_bytes() == prompt.encode('utf-8')
try:
    subprocess.run(['/bin/true', 'x' * (limit + 1)], check=False)
except OSError as error:
    assert error.errno == errno.E2BIG, error
else:
    raise AssertionError('exec accepted an argument above the computed limit')
""",
    )


def test_native_options_share_linux_argument_budget(clean_workspace: ContainerLike) -> None:
    _run_check(
        clean_workspace,
        _MOCK_CODEX_LAUNCH + r"""
import errno
import resource

# Linux ARG_MAX follows the stack soft limit, with a 128 KiB floor. This makes the
# aggregate limit bind before MAX_ARG_STRLEN without depending on the Docker host.
_, hard = resource.getrlimit(resource.RLIMIT_STACK)
resource.setrlimit(resource.RLIMIT_STACK, (512 * 1024, hard))
assert os.sysconf('SC_ARG_MAX') == 128 * 1024
args = ('-c', 'developer_instructions="' + 'é' * 16_384 + '"')
baseline = prompt_limit()
limit = prompt_limit(args)
assert baseline - limit > 32_768
prompt = 'é' * (limit // 2) + 'x' * (limit % 2)
assert launch(prompt, args) == 0
assert Path('/workspace/codex-prompt.txt').read_bytes() == prompt.encode('utf-8')
try:
    launch('x' * baseline, args)
except OSError as error:
    assert error.errno == errno.E2BIG, error
else:
    raise AssertionError('exec accepted the prompt budget that ignored native options')
""",
    )
