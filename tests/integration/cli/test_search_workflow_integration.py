"""Docker-based E2E tests for `forge search` workflows.

Exercises real components end-to-end:
- transcripts on disk under .forge/artifacts/**/transcripts/
- `forge search rebuild-index` discovery + indexing
- `forge search query` query path + JSON output
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestSearchE2E:
    def test_rebuild_index_and_query(self, mock_claude_workspace: ContainerLike) -> None:
        # Create two transcripts across two sessions
        mock_claude_workspace.exec("mkdir -p /workspace/.forge/artifacts/s1/transcripts")
        mock_claude_workspace.exec("mkdir -p /workspace/.forge/artifacts/s2/transcripts")

        mock_claude_workspace.write_file(
            "/workspace/.forge/artifacts/s1/transcripts/t1.jsonl",
            "\n".join(
                [
                    json.dumps(
                        {
                            "requestId": "r1",
                            "timestamp": "2026-01-01T00:00:00Z",
                            "message": {"role": "user", "content": [{"type": "text", "text": "update timeout to 30"}]},
                        }
                    ),
                    json.dumps(
                        {
                            "requestId": "r1",
                            "timestamp": "2026-01-01T00:00:01Z",
                            "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                        }
                    ),
                ]
            )
            + "\n",
        )
        mock_claude_workspace.write_file(
            "/workspace/.forge/artifacts/s2/transcripts/t2.jsonl",
            json.dumps(
                {
                    "requestId": "r2",
                    "timestamp": "2026-01-01T00:10:00Z",
                    "message": {"role": "user", "content": [{"type": "text", "text": "add auth middleware"}]},
                }
            )
            + "\n",
        )

        rebuild = mock_claude_workspace.exec("cd /workspace && forge search rebuild-index", timeout=60)
        assert rebuild.returncode == 0, rebuild.stderr

        query = mock_claude_workspace.exec("cd /workspace && forge search query timeout", timeout=30)
        assert query.returncode == 0, query.stderr

        data = json.loads(query.stdout)
        assert data["total_results"] >= 1
        session_names = {r["session_name"] for r in data["results"]}
        assert "s1" in session_names
