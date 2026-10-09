#!/usr/bin/env python3
"""A single local echo tool; logs only this synthetic probe's JSON-RPC requests."""

import json
import sys
from pathlib import Path

for line in sys.stdin:
    request = json.loads(line)
    with Path(sys.argv[1]).open("a") as stream:
        stream.write(json.dumps(request) + "\n")
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {
            "protocolVersion": request["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "b2-fixture", "version": "1"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Return the supplied B2 probe text unchanged.",
                    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                }
            ]
        }
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": request["params"]["arguments"]["text"]}]}
    elif method in {"resources/list", "resources/templates/list", "prompts/list"}:
        key = {
            "resources/list": "resources",
            "resources/templates/list": "resourceTemplates",
            "prompts/list": "prompts",
        }[method]
        result = {key: []}
    elif method == "ping":
        result = {}
    else:
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {"code": -32601, "message": "Fixture method unavailable"},
                }
            ),
            flush=True,
        )
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
