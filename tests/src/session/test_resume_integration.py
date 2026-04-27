"""Integration tests for session resume functionality.

Tests:
- Strategy variations (minimal/structured/full output headings)
- Budget exceeded error path
- Proxy inheritance (intent vs started_with_proxy)
- Depth traversal across multi-session chain
- Index semantics (two names → one worktree)

Note: Basic resume happy path is already covered in test_manager_integration.py:
- test_resume_creates_child_session
- test_resume_with_explicit_child_name
- test_resume_raises_when_not_found
"""

from __future__ import annotations

import pytest

from tests.src.session.conftest import WorktreeWorkspace

# All tests in this file require Docker
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

# HOME directory for isolated testing
HOME = "/home/test"


# -----------------------------------------------------------------------------
# Strategy Variation Tests (Heading-Level Assertions)
# -----------------------------------------------------------------------------


class TestResumeStrategyVariations:
    """Tests for different resume strategies producing expected output sections."""

    def test_minimal_strategy_produces_lineage_only(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Minimal strategy context file should have Lineage section, no conversation."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-minimal', worktree_path='/workspace')

# Resume with minimal strategy
child_manifest, handoff_result = manager.resume_session(
    'parent-minimal',
    strategy='minimal',
)

# Read the context file content
context_file = handoff_result.context_file
context_content = context_file.read_text() if context_file else ''

print(json.dumps({
    'has_lineage_section': '## Lineage' in context_content,
    'has_conversation_summary': '## Conversation Summary' in context_content,
    'has_full_transcript': '## Full Transcript' in context_content,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["has_lineage_section"] is True
        assert result.data["has_conversation_summary"] is False
        assert result.data["has_full_transcript"] is False

    def test_structured_strategy_has_conversation_summary(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Structured strategy context file should have Conversation Summary section."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-structured', worktree_path='/workspace')

# Resume with structured strategy (default)
child_manifest, handoff_result = manager.resume_session(
    'parent-structured',
    strategy='structured',
)

# Read the context file content
context_file = handoff_result.context_file
context_content = context_file.read_text() if context_file else ''

print(json.dumps({
    'has_conversation_summary': '## Conversation Summary' in context_content,
    'has_artifacts': '## Artifacts' in context_content,
    'has_full_transcript': '## Full Transcript' in context_content,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["has_conversation_summary"] is True
        assert result.data["has_artifacts"] is True
        assert result.data["has_full_transcript"] is False

    def test_full_strategy_has_full_transcript(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Full strategy context file should have Full Transcript section."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-full', worktree_path='/workspace')

# Create a small transcript artifact (fits any reasonable budget)
artifacts_dir = Path('/workspace/.forge/artifacts/parent-full/transcripts')
artifacts_dir.mkdir(parents=True, exist_ok=True)
transcript_path = artifacts_dir / 'sample.jsonl'
# Small transcript: ~100 bytes = ~25 tokens
transcript_path.write_text('{"requestId":"r1","message":{"role":"user","content":[{"type":"text","text":"hello"}]}}')

# Update parent's confirmed.artifacts to include the transcript
store = SessionStore('/workspace','parent-full')
parent_state = store.read()
parent_state.confirmed.artifacts['transcripts'] = [
    {'copied_path': '.forge/artifacts/parent-full/transcripts/sample.jsonl'}
]
store.write(parent_state)

# Resume with full strategy and generous budget
child_manifest, handoff_result = manager.resume_session(
    'parent-full',
    strategy='full',
    context_limit=100000,  # Large budget
)

# Read the context file content
context_file = handoff_result.context_file
context_content = context_file.read_text() if context_file else ''

print(json.dumps({
    'has_full_transcript': '## Full Transcript' in context_content,
    'has_artifacts': '## Artifacts' in context_content,
    'has_conversation_summary': '## Conversation Summary' in context_content,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["has_full_transcript"] is True
        assert result.data["has_artifacts"] is True
        assert result.data["has_conversation_summary"] is False


# -----------------------------------------------------------------------------
# Budget Exceeded Tests
# -----------------------------------------------------------------------------


class TestResumeBudgetExceeded:
    """Tests for budget checking when using full strategy."""

    def test_full_strategy_exceeds_budget_raises_error(self, manager_workspace: "WorktreeWorkspace") -> None:
        """Full strategy should raise ContextBudgetExceededError with helpful message."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore
from forge.session.exceptions import ContextBudgetExceededError

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-budget', worktree_path='/workspace')

# Create a transcript artifact of KNOWN SIZE
# 4096 bytes = ~1024 tokens (using file_size // 4 heuristic)
artifacts_dir = Path('/workspace/.forge/artifacts/parent-budget/transcripts')
artifacts_dir.mkdir(parents=True, exist_ok=True)
transcript_path = artifacts_dir / 'large.jsonl'
transcript_path.write_text('x' * 4096)  # 4096 bytes

# Update parent's confirmed.artifacts
store = SessionStore('/workspace','parent-budget')
parent_state = store.read()
parent_state.confirmed.artifacts['transcripts'] = [
    {'copied_path': '.forge/artifacts/parent-budget/transcripts/large.jsonl'}
]
store.write(parent_state)

# Attempt resume with full strategy and TINY budget
error_type = None
error_message = None
try:
    manager.resume_session(
        'parent-budget',
        strategy='full',
        context_limit=100,  # Tiny: 100 tokens, transcript is ~1024 tokens
    )
except ContextBudgetExceededError as e:
    error_type = 'ContextBudgetExceededError'
    error_message = str(e)

print(json.dumps({
    'error_type': error_type,
    'has_strategy_guidance': '--strategy structured' in (error_message or '') or 'structured' in (error_message or ''),
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["error_type"] == "ContextBudgetExceededError"
        assert result.data["has_strategy_guidance"] is True


# -----------------------------------------------------------------------------
# Proxy Inheritance Tests
# -----------------------------------------------------------------------------


class TestResumeProxyInheritance:
    """Tests for proxy template inheritance during resume."""

    def test_resume_inherits_from_parent_intent_when_no_started_with_proxy(
        self, manager_workspace: "WorktreeWorkspace"
    ) -> None:
        """If parent has no started_with_proxy, derivation.inherited_proxy is None."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent with intent.proxy.template (but no hooks ran = no started_with_proxy)
manager.start_session(
    name='parent-intent-only',
    worktree_path='/workspace',
    proxy_template='litellm-gemini',  # Sets intent.proxy.template
)

# Resume parent
child_manifest, handoff_result = manager.resume_session('parent-intent-only')

# Check derivation
derivation = child_manifest.confirmed.derivation

print(json.dumps({
    'child_name': child_manifest.name,
    'derivation_inherited_proxy': derivation.inherited_proxy if derivation else None,
    'derivation_parent_session': derivation.parent_session if derivation else None,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # No started_with_proxy in parent, so inherited_proxy should be None
        assert result.data["derivation_inherited_proxy"] is None
        assert result.data["derivation_parent_session"] == "parent-intent-only"

    def test_resume_inherits_from_started_with_proxy_when_present(self, manager_workspace: "WorktreeWorkspace") -> None:
        """If parent has started_with_proxy, derivation.inherited_proxy is set from it."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore
from forge.session.models import StartedWithProxy

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-with-proxy', worktree_path='/workspace')

# Seed confirmed.started_with_proxy (simulating what hooks would do)
store = SessionStore('/workspace','parent-with-proxy')
parent_state = store.read()
parent_state.confirmed.started_with_proxy = StartedWithProxy(
    base_url='http://localhost:8084',
    template='litellm-openai',
    proxy_id='test-proxy-123',
    port=8084,
)
store.write(parent_state)

# Resume parent
child_manifest, handoff_result = manager.resume_session('parent-with-proxy')

# Check derivation
derivation = child_manifest.confirmed.derivation

print(json.dumps({
    'derivation_inherited_proxy': derivation.inherited_proxy if derivation else None,
    'derivation_parent_session': derivation.parent_session if derivation else None,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["derivation_inherited_proxy"] == "litellm-openai"
        assert result.data["derivation_parent_session"] == "parent-with-proxy"


# -----------------------------------------------------------------------------
# Depth / Lineage Tests
# -----------------------------------------------------------------------------


class TestResumeDepthLineage:
    """Tests for lineage traversal with depth parameter.

    Note: Multi-generation chains require multiple worktrees because
    SessionStore is one manifest per worktree.
    """

    def test_depth_one_shows_immediate_parent_only(self, manager_workspace: "WorktreeWorkspace") -> None:
        """depth=1 should only show immediate parent in lineage."""
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-depth', worktree_path='/workspace')

# Resume with depth=1 (default)
child_manifest, handoff_result = manager.resume_session(
    'parent-depth',
    depth=1,
)

# Check lineage
lineage = handoff_result.lineage

print(json.dumps({
    'lineage': lineage,
    'lineage_length': len(lineage),
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["lineage"] == ["parent-depth"]
        assert result.data["lineage_length"] == 1

    def test_depth_traverses_multiple_generations_via_fork(self, manager_workspace: "WorktreeWorkspace") -> None:
        """depth parameter should include ancestors up to specified depth.

        Uses fork_session to create multi-generation chain across worktrees.
        """
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from pathlib import Path
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.store import SessionStore

manager = SessionManager(index_store=IndexStore())

# Create grandparent session in /workspace
manager.start_session(name='grandparent', worktree_path='/workspace')

# Fork to create parent (fork_session sets parent_session)
# This creates a new worktree
parent_manifest, _ = manager.fork_session(
    parent_name='grandparent',
    fork_name='parent-gen',
)

# Resume parent with depth=2 to see both generations
child_manifest, handoff_result = manager.resume_session(
    'parent-gen',
    depth=2,
)

# Check lineage
lineage = handoff_result.lineage

print(json.dumps({
    'lineage': lineage,
    'lineage_length': len(lineage),
    'parent_in_lineage': 'parent-gen' in lineage,
    'grandparent_in_lineage': 'grandparent' in lineage,
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        assert result.data["parent_in_lineage"] is True
        assert result.data["grandparent_in_lineage"] is True
        assert result.data["lineage_length"] == 2


# -----------------------------------------------------------------------------
# Index Semantics Tests
# -----------------------------------------------------------------------------


class TestResumeIndexSemantics:
    """Tests documenting index behavior after resume."""

    def test_resume_index_has_both_parent_and_child_entries(self, manager_workspace: "WorktreeWorkspace") -> None:
        """After resume, both parent and child appear in index (same worktree).

        This documents current behavior: resume_session() adds child entry
        without removing parent entry, resulting in two names pointing at
        the same manifest/worktree.
        """
        result = manager_workspace.run_python(
            """
import json
import os
os.chdir('/workspace')

from forge.session.index import IndexStore
from forge.session.manager import SessionManager

manager = SessionManager(index_store=IndexStore())

# Create parent session
manager.start_session(name='parent-index', worktree_path='/workspace')

# Resume creates child
child_manifest, _ = manager.resume_session('parent-index')

# List all sessions (returns list of (name, entry) tuples)
sessions = manager.list_sessions()
session_names = [name for name, _entry in sessions]

# Get paths for both
index_store = IndexStore()
index = index_store.read()
parent_entry = index.sessions.get('parent-index')
child_entry = index.sessions.get(child_manifest.name)

print(json.dumps({
    'session_names': session_names,
    'parent_in_index': 'parent-index' in session_names,
    'child_in_index': child_manifest.name in session_names,
    'parent_path': parent_entry.worktree_path if parent_entry else None,
    'child_path': child_entry.worktree_path if child_entry else None,
    'same_worktree': (parent_entry.worktree_path if parent_entry else None) == (child_entry.worktree_path if child_entry else None),
}))
""",
            home=HOME,
        )
        assert result.ok, f"Failed: {result.stderr}"
        assert result.data is not None
        # Both names should be in the index
        assert result.data["parent_in_index"] is True
        assert result.data["child_in_index"] is True
        # Both should point to the same worktree
        assert result.data["same_worktree"] is True
