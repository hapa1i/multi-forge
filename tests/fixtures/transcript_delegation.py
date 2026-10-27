"""Native-shaped tool traffic shared by transfer regression and Linux launch tests."""

from typing import Any


def tool_heavy_transcript(tool_pairs: int = 1000) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = [
        {"message": {"role": "user", "content": "Inspect the project"}},
        {
            "requestId": "opening",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Inspecting the project"}]},
        },
    ]
    for index in range(tool_pairs):
        entries.extend(
            [
                {
                    "requestId": f"request-{index}",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": f"read-{index}", "name": "Read", "input": {"path": "source.py"}}
                        ],
                    },
                },
                {
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": f"read-{index}", "content": "raw output " * 50}
                        ],
                    }
                },
            ]
        )
    entries.append(
        {
            "requestId": "closing",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Review complete"}]},
        }
    )
    return entries
