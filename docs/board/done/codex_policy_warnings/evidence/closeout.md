# B3 fixture closeout

Closed on 2026-10-11 after PR #262 merged. [closeout.json](closeout.json) records the result. The private captures,
retained runtime package, and wheel artifacts remain available; only the fixture-owned Codex credential file is removed.
No logout command or model call is part of closeout. Local credential removal does not prove remote token revocation.

Before cleanup, the committed `b3-verify.py` rechecked all 16 selected captures and the prior quote-quality result in a
separate output directory. Its inputs were links to the retained captures, project, wheel verification, original host
configuration hashes, and turn ledger. The original verification reports were preserved. The command was:

```bash
PROBE_ROUND_ROOT="$ROUND/closeout-verification" .venv/bin/python \
  scripts/experiments/codex-hooks/b3-verify.py --real-case real-claude-authenticated \
  --wheel-prefix wheel-review --tui-combined-case tui-review-final
```

The [preserved-artifact manifest](preserved-artifacts.json) contains the 52 baseline hashes used below. They can also be
checked against merge commit `f1019f6c` before its board lane move.

The following one-time command ran from the checkout. It refuses live fixture processes, checks ownership and retained
evidence before unlinking the credential file, and never reads credential contents. Process arguments are inspected only
for the fixture path and are neither printed nor retained. The referenced pre-closeout hash manifest was computed from
the 52 historical JSON/text files in the merged evidence directory before the lane move.

````python
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
from datetime import datetime, timezone

root = Path("/private/tmp/forge-b3-20261010")
evidence = Path("docs/board/done/codex_policy_warnings/evidence")
report_path = evidence / "closeout.json"
assert not report_path.exists(), "Preserve an existing closeout record."
assert root.resolve(strict=True) == root
assert root.stat().st_uid == os.getuid()
assert (root / "B3_ROUND").read_text() == "independent-b3-round-v1\n"
home = root / "codex-home"
assert home.resolve(strict=True) == home
assert home != Path.home() / ".codex"
assert (home / ".forge-codex-probe-home").read_text() == "independent-login-v1\n"
auth = home / "auth.json"
identity = json.loads((root / "identity.json").read_text())
binary = Path(identity["retained_path"])
assert binary.resolve(strict=True).is_relative_to(root / "runtime")

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def host_state():
    config = {
        name: digest(Path.home() / ".codex" / name)
        if (Path.home() / ".codex" / name).is_file() else None
        for name in ("config.toml", "hooks.json")
    }
    host_auth = Path.home() / ".codex/auth.json"
    info = host_auth.lstat() if host_auth.exists() else None
    return config, (info.st_ino, info.st_size, info.st_mtime_ns) if info else None

spec = importlib.util.spec_from_file_location(
    "probe_runtime", "scripts/experiments/codex-hooks/probe-runtime.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
known = {}
registries = list((root / "captures").rglob("processes.jsonl"))
for registry in registries:
    for line in registry.read_text().splitlines():
        row = json.loads(line)
        known[row["pid"]] = row

def remaining():
    table = probe.process_table()
    ancestors = {os.getpid()}
    pid = os.getpid()
    while pid in table and table[pid]["ppid"] not in ancestors:
        pid = table[pid]["ppid"]
        ancestors.add(pid)
    matched = []
    output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    for line in output.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) == 2 and int(fields[0]) not in ancestors and str(root) in fields[1]:
            matched.append(int(fields[0]))
    return {"registered": probe.living(known), "fixture_path_pids": matched}

before_processes = remaining()
assert not any(before_processes.values()), "Refuse cleanup while fixture processes remain."
assert digest(binary) == identity["sha256"]
enrolled = json.loads((root / "ENROLLED").read_text())
assert digest(home / "config.toml") == enrolled["config_sha256"]
historical = json.loads(Path("/private/tmp/b3-closeout-evidence-before.json").read_text())
assert all(digest(evidence / name) == sha for name, sha in historical.items())
verified = json.loads((root / "closeout-verification/verification.json").read_text())
assert len(verified["cases"]) == 16 and all(row["passed"] for row in verified["cases"].values())
assert verified["real_quote_usable"] and verified["reserved_codex_turns"] == 32
before_host = host_state()
info = auth.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
auth.unlink()
assert not auth.exists()
after_processes = remaining()
assert not any(after_processes.values())
after_host = host_state()
source = (evidence / "closeout.md").read_text().split("```python\n", 1)[1].split("\n```", 1)[0]
report = {
    "closed_at_utc": datetime.now(timezone.utc).isoformat(),
    "merge_commit": "f1019f6c7e3589500f0c8d8037ed4c8d9e5b4bd9",
    "tested_head": "81c1444830419b73ee53098d1d4130b7bfbc8d1a",
    "command_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "probe_runtime_sha256": digest(Path(spec.origin)),
    "offline_verifier_cases_passed": len(verified["cases"]),
    "offline_verifier_report_sha256": digest(root / "closeout-verification/verification.json"),
    "real_quote_usable": verified["real_quote_usable"],
    "reserved_codex_turns": verified["reserved_codex_turns"],
    "new_model_calls": 0,
    "historical_artifacts_preserved": len(historical),
    "process_registries_checked": len(registries),
    "recorded_process_identities": len(known),
    "processes_before": before_processes,
    "processes_after": after_processes,
    "signals_sent": [],
    "fixture_auth_file_removed": "$ROUND/codex-home/auth.json",
    "host_codex_config_hashes_unchanged_during_cleanup": before_host[0] == after_host[0],
    "host_codex_auth_metadata_unchanged_during_cleanup": before_host[1] == after_host[1],
    "host_codex_config_unchanged_since_round_start": verified["host_codex_config_bytes_unchanged"],
    "host_auth_validity_verified": False,
    "fixture_enrollment_config_sha256": digest(home / "config.toml"),
    "retained_codex_sha256": digest(binary),
    "captures_and_runtime_retained": True,
}
report_path.write_text(json.dumps(report, indent=2) + "\n")
(root / "CLOSED").write_text(report["closed_at_utc"] + "\n")
print(json.dumps(report, indent=2))
````
