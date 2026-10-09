#!/usr/bin/env python3
"""Export the retained B2 round and its publication supplements from frozen private inputs.

The original export.py is retained with path redaction in helper-sources.json. This script
makes its omitted publication steps explicit and adds native feedback evidence.
Input publication.json supplies the original path substitutions, eight product
file names and seven historical helper names; it contains no credential values.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import marshal
import re
import subprocess
from pathlib import Path
from types import CodeType
from typing import Any

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("inputs", type=Path, help="Frozen round files, with publication.json and original relative paths")
parser.add_argument("output", type=Path, help="New output directory; never overwrite a published round")
args = parser.parse_args()
ROOT = args.inputs.resolve()
CAP = ROOT / "captures"
DEST = args.output.resolve()
DEST.mkdir(parents=True, exist_ok=False)
publication = json.loads((ROOT / "publication.json").read_text())
INDEX: dict[str, str] = {}


def clean(s: str) -> str:
    """Apply the original round's path and opaque-message redaction rules."""
    s = (
        s.replace(publication["source_root"], "<ROUND_ROOT>")
        .replace(publication["checkout"], "<CHECKOUT>")
        .replace(publication["home"], "<HOME>")
    )
    s = re.sub(r"/private/var/folders/[A-Za-z0-9/_.+-]*", "<TEMP>", s)
    s = re.sub(r"gAAAA[A-Za-z0-9_=-]{40,}", "<OPAQUE_ENCRYPTED_AGENT_MESSAGE>", s)
    return s


def raw(p: Path) -> str:
    """Hash original private bytes before replacing identifying paths."""
    data = p.read_bytes()
    INDEX[str(p.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return clean(data.decode(errors="replace"))


def j(p: Path) -> Any:
    """Read and redact one retained JSON source."""
    return json.loads(raw(p))


def lines(p: Path) -> list[dict[str, Any]]:
    """Read optional captured JSONL records."""
    if not p.exists():
        return []
    return [json.loads(x) for x in raw(p).splitlines() if x.strip()]


def write(name: str, obj: object) -> None:
    """Write one reviewed export with the original formatting."""
    (DEST / name).write_text(clean(json.dumps(obj, indent=2, ensure_ascii=False)) + "\n")


def selected(p: Path, names: list[str]) -> dict[str, Any]:
    """Retain available named captures without inventing missing observations."""
    return {name: j(p / name) for name in names if (p / name).exists()}


def stream(p: Path) -> list[dict[str, Any]]:
    """Select structured events; the source hash also covers non-JSON diagnostics."""
    result = []
    if p.exists():
        for line in raw(p).splitlines():
            try:
                result.append(json.loads(line))
            except ValueError:
                pass
    return result


def native(thread: str) -> list[dict[str, Any]]:
    """Locate exactly one retained synthetic rollout for the thread."""
    paths = list((ROOT / "codex-home").glob("sessions/*/*/*/*" + thread + ".jsonl"))
    assert len(paths) == 1
    return stream(paths[0])


def present(path: Path) -> bool:
    """Hash the retained bytes behind a positive file-existence assertion."""
    if not path.exists():
        return False
    raw(path)
    return True


def normalized_code(value: Any) -> Any:
    """Compare executable code while excluding filename and source-line positions."""
    if not isinstance(value, CodeType):
        return value
    attributes = (
        "co_code",
        "co_names",
        "co_varnames",
        "co_freevars",
        "co_cellvars",
        "co_argcount",
        "co_posonlyargcount",
        "co_kwonlyargcount",
        "co_flags",
        "co_exceptiontable",
        "co_stacksize",
        "co_nlocals",
        "co_name",
        "co_qualname",
    )
    return tuple(getattr(value, name) for name in attributes), tuple(normalized_code(v) for v in value.co_consts)


def harness_drift(snapshots: dict, recorded_cases: dict) -> dict:
    """Compare recorded source hashes with the first published PR commit."""
    checkout = Path(__file__).resolve().parents[3]
    revision = publication["published_revision"]
    prefix = "scripts/experiments/codex-hooks/"
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", revision, "--", prefix], cwd=checkout, text=True
    ).splitlines()
    sources = {
        path.removeprefix(prefix): subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=checkout)
        for path in paths
    }
    hashes = {path: hashlib.sha256(source).hexdigest() for path, source in sources.items()}
    files = {}
    for filename, prefixes in {
        "instrumentation/sitecustomize.py": ("89-", "90-", "91-", "92-", "93-", "94-", "95-", "96-", "97-"),
        "b2-terminal.py": ("97-",),
        "b2-run.py": ("89-", "90-", "91-", "92-", "93-", "95-", "96-"),
        "b2-forks.py": ("94-",),
        "hooks/b2-hook.py": ("90-",),
    }.items():
        observed = {
            name: snapshots[row["command"]["harness_snapshot"]].get(filename)
            for name, row in recorded_cases.items()
            if name.startswith(prefixes)
        }
        files[filename] = {
            "published_sha256": hashes[filename],
            "recorded_case_hashes": observed,
            "matching_cases": [name for name, digest in observed.items() if digest == hashes[filename]],
        }
    cached_path = ROOT / "sitecustomize.cpython-313.pyc"
    cached = cached_path.read_bytes()
    INDEX[cached_path.name] = hashlib.sha256(cached).hexdigest()
    if cached[:4] != importlib.util.MAGIC_NUMBER:
        raise ValueError("Use Python 3.13 to compare the retained sitecustomize bytecode.")
    equivalent = normalized_code(marshal.loads(cached[16:])) == normalized_code(
        compile(sources["instrumentation/sitecustomize.py"], "sitecustomize.py", "exec")
    )
    return {
        "published_revision": revision,
        "recorded_snapshot_count": len(snapshots),
        "exact_snapshot_matches": sum(snapshot == hashes for snapshot in snapshots.values()),
        "files": files,
        "sitecustomize_bytecode": {
            "cache_sha256": INDEX[cached_path.name],
            "normalized_code_equal": equivalent,
            "method": "Compare Python 3.13 code objects recursively, excluding filenames and source-line positions; no cached code is executed.",
            "limitation": "This compares the retained cache only. Older terminal/run/fork sources were not retained, so their behavioral equivalence is unverified.",
        },
    }


cases = {}
builds = {}
identities = {}
for p in sorted(CAP.iterdir()):
    if not p.is_dir() or p.name == "sanitized":
        continue
    if (p / "command.json").exists():
        command = j(p / "command.json")
        files = command.pop("harness_files", {})
        identity = command.pop("codex_identity", None)
        if identity:
            ident = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            identities[ident] = identity
            command["codex_identity_ref"] = ident
        key = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        builds[key] = files
        command["harness_snapshot"] = key
        cases[p.name] = {"command": command, **selected(p, ["process-result.json", "terminal-result.json"])}
write("harness-snapshots.json", builds)
write(
    "provenance.json",
    {
        "identity": j(ROOT / "identity.json"),
        "quota_reservations": lines(ROOT / "turns.jsonl"),
        "harness_snapshots_file": "harness-snapshots.json",
        "codex_identities": identities,
        "cases": cases,
    },
)
base: dict[str, Any] = {}
for name in (
    "00-preflight",
    "05-config-schema",
    "10-headless-fire",
    "60-exec-resume",
    "61-rollout-identity",
    "81-enrolled-coverage",
    "84-fresh-project",
):
    p = CAP / name
    base[name] = {
        str(x.relative_to(p)): raw(x)
        for pattern in (
            "results/*.oracle.txt",
            "results/verdict.txt",
            "results/*findings.txt",
            "results/*summary.txt",
            "results/*matrix.txt",
            "results/*.exit",
            "results/*.last-message.txt",
            "meta/version.txt",
        )
        for x in sorted(p.glob(pattern))
    }
p = CAP / "88-b2-enrollment"
base["88-b2-enrollment"] = {
    "preflight": j(p / "results/preflight.json"),
    "enrollment": j(p / "results/enrollment.json"),
    "dispatcher": j(p / "results/forge-doctor.json")["hook_dispatcher"],
    "receipt": j(p / "96427-observation-receipt.json"),
    "launchers": lines(p / "hook-launchers.jsonl"),
}
notes = CAP / "80-enroll-fixture/meta/operator-notes.txt"
if notes.exists():
    base["operator_enrollment_notes"] = raw(notes)
write("baseline.json", base)
product: dict[str, Any] = {}
for p in sorted(CAP.glob("8[9]-*")) + sorted(CAP.glob("91-*")) + sorted(CAP.glob("92-*")):
    if not p.is_dir() or "failure" in p.name or "missing-login" in p.name or "env-" in p.name:
        continue
    product[p.name] = {
        "stream": stream(p / "stdout"),
        "hooks": lines(p / "hook-launchers.jsonl"),
        "reviewer": lines(p / "reviewer.jsonl"),
        "usage": lines(p / "usage-correlation.jsonl"),
        "receipts": {x.name: j(x) for x in p.glob("*receipt.json")},
    }
project = CAP / "fixture/proj"
product["filesystem"] = {
    name: present(project / name)
    for name in (
        "src/blocked_b2.py",
        "src/paired_b2.py",
        "tests/test_paired_b2.py",
        "src/absent_b2.py",
        "updated_b2.txt",
        "malformed_b2.txt",
        "supervised_b2.txt",
        "advisory_b2.txt",
        "advisory_resume_b2.txt",
        "producer_b2.txt",
        "unmarked_b2.txt",
    )
}
product["file_contents"] = {name: raw(project / name) for name in publication["file_contents"]}
write("product.json", product)
warning = {}
oracles = {x["name"]: x["nonce"] for x in lines(CAP / "b2-results.jsonl")}
for p in sorted(CAP.glob("90-*")):
    warning[p.name] = {
        "nonce": oracles[p.name],
        "last": raw(p / "last.txt"),
        "events": stream(p / "stdout"),
        "hook_payloads": [j(x) for x in p.glob("PreToolUse-*.stdin.json")],
    }
for name, arm in warning.items():
    thread = next(row["thread_id"] for row in arm["events"] if row.get("type") == "thread.started")
    records = native(thread)
    matching = [row for row in records if arm["nonce"] in json.dumps(row)]
    injected = [
        row
        for row in matching
        if row.get("type") == "response_item" and row.get("payload", {}).get("role") == "developer"
    ]
    arm["rollout_check"] = {
        "thread_id": thread,
        "nonce_record_count": len(matching),
        "injected_messages": injected,
        "historical_hook_output_captured": False,
        "limitation": "Native context was inspected. Hook stdout/stderr/exit were not captured; offline replay does not establish the historical exit status.",
    }
write("feedback.json", warning)
coverage: dict[str, Any] = {}
for name in ("93-tools-off", "93-tools-on", "93-mcp-positive"):
    p = CAP / name
    events = stream(p / "stdout")
    tid = next(x["thread_id"] for x in events if x.get("type") == "thread.started")
    coverage[name] = {
        "events": events,
        "payloads": [j(x) for x in p.glob("PreToolUse-*.stdin.json")],
        "native_tool_records": [
            x
            for x in native(tid)
            if x.get("type") == "response_item"
            and x["payload"].get("type")
            in ("function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output")
        ],
    }
coverage["mcp_requests"] = lines(CAP / "mcp-positive-requests.jsonl")
coverage["timings"] = lines(CAP / "93-dispatch-timings/samples.jsonl")
coverage["reviewers"] = lines(CAP / "93-dispatch-timings/reviewer.jsonl")
coverage["cold_admission"] = j(CAP / "93-cold-admission/samples.json")
coverage["cold_reviewers"] = lines(CAP / "93-cold-admission/reviewer.jsonl")
write(
    "dispatcher-timings.json",
    {key: coverage.pop(key) for key in ("timings", "reviewers", "cold_admission", "cold_reviewers")},
)
coverage["dispatcher_timings_file"] = "dispatcher-timings.json"
write("coverage.json", coverage)
forks = {}
for p in sorted(CAP.glob("94-*")):
    forks[p.name] = {
        **selected(p, ["fork-facts.json", "concurrent-facts.json"]),
        "last": raw(p / "last.txt") if (p / "last.txt").exists() else None,
        "fork_last": raw(p / "fork-last.txt") if (p / "fork-last.txt").exists() else None,
        "events": stream(p / "stdout"),
        "reviewer": lines(p / "reviewer.jsonl"),
        "hooks": lines(p / "hook-launchers.jsonl"),
        "payloads": [j(x) for x in p.glob("PreToolUse-*.stdin.json")],
    }
p = CAP / "94-parent-mutation"
a = j(p / "manifest-before.json")
b = j(p / "manifest-after.json")
forks["parent_delta"] = {
    "old_confirmed_at": a["confirmed"]["confirmed_at"],
    "new_confirmed_at": b["confirmed"]["confirmed_at"],
    "appended_decisions": b["confirmed"]["policy"]["decisions"][len(a["confirmed"]["policy"]["decisions"]) :],
    "codex_before": a["confirmed"].get("codex"),
    "codex_after": b["confirmed"].get("codex"),
}
write("forks.json", forks)
setup = lines(CAP / "setup.jsonl")
statuses = []
activities = []
for x in setup:
    if x["command"][1:4] == ["policy", "supervisor", "status"]:
        statuses.append(json.loads(x["stdout"]))
    if x["command"][1:3] == ["telemetry", "activity"]:
        activities.append(json.loads(x["stdout"]))
lifetime: dict[str, Any] = {
    p.name: {
        "reviewer": lines(p / "reviewer.jsonl"),
        "events": stream(p / "stdout"),
        "hooks": lines(p / "hook-launchers.jsonl"),
        **selected(p, ["process-result.json", "injected-signal.json"]),
        "file_exists": present(project / (p.name + ".txt")),
    }
    for p in sorted(CAP.glob("95-*"))
}
write("lifetime-status.json", {"status_after_each_case": statuses, "activity_after_each_case": activities})
lifetime["status_file"] = "lifetime-status.json"
write("lifetime.json", lifetime)
background = {}
for p in sorted(CAP.glob("96-*")):
    background[p.name] = {
        "events": stream(p / "stdout"),
        "hooks": {x.name: j(x) for x in p.glob("Background-*.json")},
        **selected(p, ["process-result.json"]),
    }
for p in sorted(CAP.glob("97-tui-*")):
    if "failure" in p.name:
        continue
    if not (p / "terminal.log").exists():
        continue
    s = raw(p / "terminal.log")
    s = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", s)
    s = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[\x20-\x7e]", "", s)
    background[p.name] = {
        "terminal_plain": s,
        **selected(p, ["terminal-actions.json", "terminal-result.json", "active-refusal.json", "process-result.json"]),
        "hooks": {x.name: j(x) for x in p.glob("Background-*.json")},
        "stop": [j(x) for x in p.glob("Stop-*.stdin.json")],
        "receipts": {x.name: j(x) for x in p.glob("*receipt.json")},
    }
write("interactive-background.json", background)
stop_thread = "01a11e50-142a-7850-a363-bc8ab9bb41fc"
stop_records = [
    x
    for x in native(stop_thread)
    if (x.get("type") == "event_msg" and x["payload"].get("type") != "token_count")
    or (x.get("type") == "response_item" and x["payload"].get("type") == "message")
]
p = CAP / "81-enrolled-coverage"
stop: dict[str, Any] = {"thread": stop_thread, "native_records": stop_records, "hooks": []}
for path in p.rglob("*.stdin.json"):
    payload = j(path)
    if payload.get("session_id") == stop_thread:
        stop["hooks"].append(payload)
write("stop.json", stop)
write(
    "artifact.json",
    {
        "wheel": j(CAP / "wheel.json"),
        "preflight_after": j(CAP / "preflight-after.json"),
        "teardown": j(CAP / "teardown.json"),
    },
)
(DEST / "environment.sh.txt").write_text(
    "# Sanitized evidence template; placeholders require editing before use.\n" + raw(ROOT / "run")
)
helpers = {
    name: {"sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), "source": raw(ROOT / name)}
    for name in publication["helpers"]
}
write("helper-sources.json", helpers)
write("harness-drift.json", harness_drift(builds, cases))
excluded = [
    p.name
    for p in sorted(CAP.iterdir())
    if p.is_dir()
    and (
        (
            p.name.startswith(("89-", "91-", "92-"))
            and any(word in p.name for word in ("failure", "missing-login", "env-"))
        )
        or (p.name.startswith("97-tui-") and "failure" in p.name)
    )
]
write(
    "export-selection.json",
    {
        "excluded_product_or_tui_directories": excluded,
        "selection": "Original export.py omitted product directories containing failure, missing-login or env-, and TUI directories containing failure. Their command/process records remain in provenance.json when captured; README.md records the non-passing attempts.",
        "publication_supplements": "The original ad hoc commands adding product.file_contents and the four helper sources were not retained. This exporter reconstructs those steps from the retained bytes and publishes all seven helpers.",
        "inputs": "Frozen original source-hashes.json inputs, the five feedback rollouts, product file contents, historical helper sources and publication.json; no auth store is copied.",
        "published_revision": publication["published_revision"],
        "input_manifest": j(ROOT / "publication.json"),
    },
)
write(
    "source-hashes.json",
    {
        "redaction": "Local paths replaced; opaque encrypted agent-message strings replaced, not decoded. Only synthetic probe conversations included. SHA256 hashes identify raw private sources before redaction.",
        "sources": INDEX,
    },
)
print("Exported", len(list(DEST.glob("*.json"))), "JSON evidence files")
