"""Export request timing and client outcomes from a private stage 50 capture."""

import csv
import json
import sys
from pathlib import Path


def export(capture: Path) -> None:
    cases = json.loads((capture / "matrix.json").read_bytes())
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "case",
            "verdict",
            "client_stop",
            "owner_exit",
            "visible_recovery",
            "generic_429",
            "fallback_metadata_warning",
            "followup_visible",
            "attempt",
            "seconds_since_stub_start",
            "method",
            "path",
            "status",
            "stub_reply",
            "title",
            "hosted_web",
            "additional_tools",
            "stream",
            "store",
            "previous_response_id",
            "fixture_call",
            "matching_tool_result",
            "followup_prompt",
            "compaction_prompt",
            "compacted_history",
        ]
    )
    for case in cases:
        requests = json.loads((capture / case["case"] / "requests.json").read_bytes())
        if len(requests) != case["requests"] or not requests:
            raise ValueError(f"Missing request evidence for {case['case']}")
        for number, request in enumerate(requests, 1):
            shape = request["shape"] or {}
            writer.writerow(
                [
                    case["case"],
                    case["verdict"],
                    case["stop"],
                    case["owner_exit"],
                    case["visible_refusal"],
                    case["visible_generic_429"],
                    case["fallback_metadata_warning"],
                    case["visible_followup"],
                    number,
                    request["elapsed_s"],
                    request["method"],
                    request["path"],
                    request["status"],
                    request["sent"],
                    *(
                        shape.get(key)
                        for key in (
                            "title_request",
                            "hosted_web_search",
                            "additional_tools",
                            "stream",
                            "store",
                            "previous_response_id_present",
                            "fixture_call",
                            "fixture_result",
                            "followup",
                            "compaction_prompt",
                            "compacted_history",
                        )
                    ),
                ]
            )


if __name__ == "__main__":
    export(Path(sys.argv[1]))
