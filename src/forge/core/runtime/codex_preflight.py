"""Native-Codex auth/runtime preflight (Phase 5a).

The dynamic, per-machine half of the runtime seam: where the static capability
matrix in :mod:`forge.core.runtime.registry` says *what Codex can do*, this module
checks *whether this machine can actually run ``codex exec`` non-interactively right
now* -- before any spawn. It is the card's "Compliance and Auth Preflight" for the
Codex runtime.

Binary-authoritative: the installed ``codex`` binary is the source of truth over
docs (a Stage-A probe of 0.137.0 corrected several doc-implied assumptions -- see
the slice-5a checklist note). Concretely:

* ``codex doctor --json`` is parsed for auth state **regardless of exit code** -- the
  binary emits a full valid report (``auth.credentials.status="ok"``) even when it
  exits non-zero on an unrelated provider-reachability hiccup, and its
  ``auth.credentials.details`` are **string booleans** (``"true"``/``"false"``), so a
  truthiness read of ``"false"`` would be a silent bug.
* ``overallStatus`` is **informational only** and never gates readiness: it goes
  ``"warning"`` for unrelated reasons (stale rollout DB rows, update checks) while
  auth is perfectly fine.
* ``doctor`` exposes **no per-hook trust** signal, so 5a can never prove the (not yet
  built) transfer hook is trusted -- ``hook_seam`` never returns ``"active"``. The
  codex_frontend probes (2026-06-10) pinned that hooks DO fire under headless
  ``codex exec`` once trust-enrolled (registry ``native_hooks="enrollment_gated"``),
  so the normal enabled+version-OK case returns ``"enrollment_gated"``: hooks can
  fire, but enrollment state is unchecked. A direct ``[hooks.state]`` read was
  considered and **rejected by decision** (Phase 1): the ``trusted_hash`` preimage is
  not black-box computable (a record cannot be validated), and enrollment survives
  worktrees that have NO ``[hooks.state]`` record at their own config path, so a
  path-keyed read would false-negative in Forge's main isolation workflow.

Render-free (core, not CLI): every function returns data or plain strings. The
``forge runtime preflight codex`` command renders the result; ``CodexPreflight``
carries no Rich and -- importantly -- no secret. The resolved ``CODEX_API_KEY`` value
is never a field on the result (it would leak via ``asdict()``/``--json``); 5b reads
it separately via :func:`codex_api_key_for_subprocess`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

from forge.core.auth.capabilities import CREDENTIALS, format_missing_credential_error
from forge.core.auth.template_secrets import (
    resolve_env_or_credential,
    resolve_env_or_credential_with_source,
)
from forge.core.runtime.codex_rollouts import codex_home
from forge.core.runtime.registry import RuntimeSpec, get_runtime
from forge.core.usage.ledger import BillingMode

logger = logging.getLogger(__name__)

# ``doctor`` runs the full diagnostic suite (network reachability + sqlite integrity
# scans that scale with the rollout-store size), so it is slower than the registry's
# 5s ``--version`` probe; this is a ceiling, not a target. On timeout we degrade to
# env-only auth resolution (a ChatGPT-only machine then fails closed with setup
# guidance) -- acceptable for a one-shot preflight, and ``run_doctor=False`` skips it.
_DOCTOR_TIMEOUT_S = 20
_FEATURES_TIMEOUT_S = 10

_MANAGED_HOOKS_KEY = "allow_managed_hooks_only"

# The newest codex-cli version the codex_frontend probe harness
# (``scripts/experiments/codex-hooks/``) was run against end-to-end (stages 85-87 PASS
# on 2026-06-12). Codex's trust/enrollment, hook-firing, and ``apply_patch``/argv
# behavior are pinned empirically, not contractually -- exactly the surface a minor
# release can change silently. This is a *ceiling*, surfaced as a re-probe notice when
# the installed binary runs ahead of it (``version_beyond_validated``): a bump does not
# block readiness (the binary may be fine), it tells the operator the pinned facts are
# now unverified for their version. Mirrors the 4g ``CLAUDE_VERSION_VALIDATED`` guard;
# bump it after a green probe round on a newer codex.
CODEX_VERSION_VALIDATED = "0.139.0"

# Auth state the preflight has *proven*, named by what is stored -- NOT by the login
# mechanism. ``chatgpt_tokens`` (a ChatGPT-subscription identity) is distinct from
# ``enterprise_token`` (an opaque access-token / agent identity); the device-auth flow
# is just one way to obtain the former.
CodexAuthMethod = Literal["api_key", "chatgpt_tokens", "enterprise_token", "none"]

# Whether Forge's (future) SessionStart transfer hook can deliver context. This
# preflight never returns ``active`` -- Codex trust is keyed to a specific hook entry,
# unprovable before the hook exists. ``enrollment_gated`` is the normal
# enabled+version-OK verdict and is NOT a per-home enrolled-state claim: it means
# "hooks can fire (probe-confirmed: enrolled hooks fire headless AND interactively),
# but enrollment state is unchecked" -- never treat it as ``active``. Reading
# ``[hooks.state]`` to report enrolled-vs-not per hook was rejected by decision
# (codex_frontend Phase 1, 2026-06-10): the ``trusted_hash`` is not black-box
# computable and a path-keyed read false-negatives in worktrees. ``untrusted`` stays
# reserved -- reachable only if a codex-cli source-dive makes the hash computable.
# ``unknown`` covers only the moot cases: not installed, or version unparseable (the
# floor cannot even be proven).
HookSeam = Literal["active", "untrusted", "managed_suppressed", "enrollment_gated", "disabled", "unknown"]

# Whether a Codex run can get the Responses API it requires. Codex emits
# ``wire_api="responses"`` only; no current Forge proxy serves Responses on its
# Codex-facing endpoint, so a ``--proxy`` is ``proxy_unsupported`` and direct
# ``codex exec`` (``native_direct``) is the supported path.
ProxyResponses = Literal["native_direct", "proxy_supported", "proxy_unsupported"]


@dataclass(frozen=True)
class CodexPreflight:
    """Result of a native-Codex preflight. Flat, JSON-safe, and secret-free.

    Consumed by later slices without re-doing 5a's work: 5b gates spawning on
    ``installed``/``ready`` (and injects the key via :func:`codex_api_key_for_subprocess`),
    5c writes ``billing_mode`` verbatim onto the usage ledger, 5d reads ``hook_seam``
    to decide SessionStart-vs-initial-message delivery.
    """

    installed: bool  # codex on PATH; a precondition of ``ready``
    version: str | None  # detected version; None = unparseable (distinct from absent)
    version_ok: bool  # parsed version >= registry hook_min_version (None -> False)
    auth_method: CodexAuthMethod
    auth_source: str  # "env" | "credential_file" | "codex_store" | "none" (provenance; NON-secret)
    billing_mode: BillingMode  # 5c writes this onto the ledger event
    ready: bool  # installed AND auth resolved AND not responses-blocked; NEVER doctor overallStatus
    blocking_reason: str | None  # actionable setup guidance; None iff ready
    hook_seam: (
        HookSeam  # never "active" here (normal enabled case is "enrollment_gated": can fire, enrollment unchecked)
    )
    proxy_responses: ProxyResponses
    doctor_status: str | None  # codex doctor overallStatus -- informational, never gates ready
    version_validated: str = CODEX_VERSION_VALIDATED  # newest probe-validated codex (the ceiling)
    version_beyond_validated: bool = False  # installed runs AHEAD of the probe ceiling -> re-probe notice


class CodexPreflightError(Exception):
    """Raised by :func:`assert_codex_ready` when Codex is not ready (the 5b fail-closed seam).

    Mirrors ``proxy_startup.validate_proxy_startup``'s typed-exception precedent: the
    core returns data (:func:`preflight_codex`); only the launcher that demands
    readiness raises. Carries the full result so callers can inspect why.
    """

    def __init__(self, result: CodexPreflight) -> None:
        self.result = result
        super().__init__(result.blocking_reason or "Codex preflight failed (not ready)")


def preflight_codex(
    *,
    runtime: RuntimeSpec | None = None,
    proxy_id: str | None = None,
    run_doctor: bool = True,
) -> CodexPreflight:
    """Check whether native Codex can run headless on this machine. Never raises for an
    expected condition -- an unready machine returns ``ready=False`` + ``blocking_reason``.

    ``proxy_id`` (an *existing* proxy id, never an auto-started template) adds a
    Responses-capability check on that proxy's Codex-facing wire. ``run_doctor=False``
    skips the (slower) ``codex doctor`` probe, falling back to env-only auth.
    """
    runtime = runtime or get_runtime("codex")

    installed = _codex_installed(runtime)
    version = _detect_version(runtime) if installed else None
    version_ok = _version_meets_floor(version, runtime.hook_min_version)
    # "Beyond the ceiling" only when the version parses AND sorts strictly above the
    # validated one; an unparseable version stays False (we can't claim it ran ahead).
    version_beyond_validated = version is not None and _version_lt(CODEX_VERSION_VALIDATED, version)
    doctor = _probe_doctor_json(runtime) if (installed and run_doctor) else None

    auth = _resolve_codex_auth(doctor)
    hook_seam = _resolve_hook_seam(
        installed=installed,
        version=version,
        runtime=runtime,
        features_hooks_enabled=_probe_features_hooks_enabled(runtime) if installed else None,
        managed_only=_read_managed_only(),
    )
    responses = _resolve_responses_posture(proxy_id)

    # Blocking-reason precedence: install is most fundamental (codex can't run at all),
    # then auth (can't authenticate), then the proxy/Responses posture.
    if not installed:
        blocking_reason: str | None = _not_installed_reason(runtime)
    elif auth.blocking_reason is not None:
        blocking_reason = auth.blocking_reason
    else:
        blocking_reason = responses.blocking_reason

    ready = installed and auth.blocking_reason is None and responses.posture != "proxy_unsupported"

    return CodexPreflight(
        installed=installed,
        version=version,
        version_ok=version_ok,
        auth_method=auth.method,
        auth_source=auth.source,
        billing_mode=auth.billing_mode,
        ready=ready,
        blocking_reason=blocking_reason,
        hook_seam=hook_seam,
        proxy_responses=responses.posture,
        doctor_status=doctor.get("overallStatus") if isinstance(doctor, dict) else None,
        version_beyond_validated=version_beyond_validated,
    )


def assert_codex_ready(
    *,
    runtime: RuntimeSpec | None = None,
    proxy_id: str | None = None,
    run_doctor: bool = True,
) -> CodexPreflight:
    """Return a ready :class:`CodexPreflight`, or raise :class:`CodexPreflightError`.

    The fail-closed seam for the 5b launcher: it must not spawn ``codex exec`` for an
    unready machine.
    """
    result = preflight_codex(runtime=runtime, proxy_id=proxy_id, run_doctor=run_doctor)
    if not result.ready:
        raise CodexPreflightError(result)
    return result


def codex_api_key_for_subprocess() -> str | None:
    """Resolve the ``CODEX_API_KEY`` value for 5b to inject into the ``codex exec`` child env.

    Deliberately separate from :class:`CodexPreflight` and **non-rendered**: the secret
    must never be a field on the result (it would leak via ``asdict()``/``--json``).
    Forge's credential store (``~/.forge/credentials.yaml``) is invisible to the
    ``codex`` binary, so a ``credential_file``-sourced key must be injected by 5b or a
    ``ready=True`` is a lie. ``codex_store`` auth (chatgpt/enterprise) needs no injection
    -- Codex reads its own store. Respects ``auth_ignore_env`` via the resolver.
    """
    return resolve_env_or_credential("CODEX_API_KEY")


# ── Probes (subprocess / filesystem) -- the per-test monkeypatch seams ─────────────


def _codex_installed(runtime: RuntimeSpec) -> bool:
    """Thin wrapper over ``runtime.is_installed()`` (the test seam for PATH presence)."""
    return runtime.is_installed()


def _detect_version(runtime: RuntimeSpec) -> str | None:
    """Thin wrapper over ``runtime.detect()`` (the test seam for version)."""
    return runtime.detect()


def _probe_doctor_json(runtime: RuntimeSpec) -> dict[str, Any] | None:
    """Run ``codex doctor --json`` and parse stdout as JSON, **regardless of exit code**.

    The binary emits a complete, valid report even when it exits non-zero on an
    unrelated provider-reachability failure (Stage-A observed exit 1 with
    ``auth.credentials.status="ok"``), so reusing the registry's "non-zero -> None"
    version rule here would fail closed on an authenticated-but-offline machine.
    Returns None only when there is no parseable JSON object at all.
    """
    bin_name = runtime.headless_cmd[0]
    if shutil.which(bin_name) is None:
        return None
    try:
        result = subprocess.run(
            [bin_name, "doctor", "--json"],
            capture_output=True,
            text=True,
            timeout=_DOCTOR_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("codex doctor probe failed (non-critical): %s", e)
        return None
    out = result.stdout.strip()
    if not out:
        return None
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _probe_features_hooks_enabled(runtime: RuntimeSpec) -> bool | None:
    """Read the ``hooks`` row of ``codex features list`` (no ``--json`` exists).

    Output is columnar ``<name> <stability...> <bool>`` where the stability column can
    be multi-word (``under development``); match the **first** token exactly against
    ``hooks`` (a ``plugin_hooks`` row also exists) and read the **last** token as the
    enabled flag. Returns None when the row is absent or the probe fails (undetermined
    -- distinct from ``False`` = explicitly disabled).
    """
    bin_name = runtime.headless_cmd[0]
    if shutil.which(bin_name) is None:
        return None
    try:
        result = subprocess.run(
            [bin_name, "features", "list"],
            capture_output=True,
            text=True,
            timeout=_FEATURES_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("codex features probe failed (non-critical): %s", e)
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        tokens = line.split()
        if len(tokens) >= 2 and tokens[0] == "hooks":
            return tokens[-1] == "true"
    return None


def _read_managed_only() -> bool:
    """True only on **explicit** local/system evidence that managed-only hooks are enforced.

    Reads ``$CODEX_HOME/requirements.toml`` (default ``~/.codex``) and
    ``/etc/codex/requirements.toml`` for ``allow_managed_hooks_only = true``. Absence is
    NOT proof of "not suppressed" -- cloud/MDM layers exist that we cannot read -- so
    callers treat a ``False`` here as "no local evidence", never "definitely enabled"
    (B4). A managed-only setup is a capability limitation, not a ``ready`` blocker.
    """
    for path in _managed_requirements_paths():
        data = _read_toml(path)
        if data is not None and _toml_flag_true(data, _MANAGED_HOOKS_KEY):
            return True
    return False


def _managed_requirements_paths() -> list[Path]:
    return [codex_home() / "requirements.toml", Path("/etc/codex/requirements.toml")]


def _read_toml(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _toml_flag_true(data: dict[str, Any], key: str) -> bool:
    """True if ``key`` is the TOML boolean ``true`` at top level or one table deep."""
    if data.get(key) is True:
        return True
    return any(isinstance(v, dict) and v.get(key) is True for v in data.values())


# ── Pure resolvers (take probe output; directly unit-testable) ─────────────────────


class _Auth(NamedTuple):
    method: CodexAuthMethod
    source: str
    billing_mode: BillingMode
    blocking_reason: str | None


def _resolve_codex_auth(doctor: dict[str, Any] | None) -> _Auth:
    """Resolve a non-interactive credential, first match wins; binary-authoritative when
    env is absent. ``installed`` is enforced separately as a precondition of ``ready`` --
    a resolved env key on a machine with no ``codex`` still yields ``ready=False``.

    Order: Forge ``CODEX_API_KEY`` (env or credential file) -> ``CODEX_ACCESS_TOKEN``
    (env-only enterprise/automation) -> ``codex``'s own stored auth (via ``doctor``) ->
    none (fail closed with setup guidance naming all three paths).
    """
    value, source = resolve_env_or_credential_with_source("CODEX_API_KEY")
    if value:
        return _Auth("api_key", source, "api", None)

    if os.environ.get("CODEX_ACCESS_TOKEN"):
        # Env-only (not a CREDENTIALS entry -- it is an access token, not an API key).
        # An opaque access token's billing pool is unprovable, so ``unknown`` is honest.
        return _Auth("enterprise_token", "env", "unknown", None)

    # Stored-auth resolution is PRESENCE-based (which credential exists), mirroring the env
    # path -- not validity. We read `.details` (presence booleans) and intentionally NOT
    # `auth.credentials.status`: gating readiness on that status risks the same
    # false-fail-closed trap as overallStatus (the auth check can go non-"ok" benignly;
    # unobserved in Stage A). Real validity is proven when 5b runs `codex exec`.
    details = _doctor_auth_details(doctor)  # string booleans: compare == "true"
    if details.get("stored API key") == "true":
        return _Auth("api_key", "codex_store", "api", None)
    if details.get("stored agent identity") == "true":
        # Access-token identity (codex login --with-access-token); pool unprovable.
        return _Auth("enterprise_token", "codex_store", "unknown", None)
    if details.get("stored ChatGPT tokens") == "true":
        # Consumer ChatGPT is provably quota/credit-billed.
        return _Auth("chatgpt_tokens", "codex_store", "subscription_quota", None)

    reason = format_missing_credential_error(
        CREDENTIALS["codex-api"],
        missing_vars=["CODEX_API_KEY"],
        context="Native Codex preflight",
        extra_hint="Or run 'codex login --device-auth' (ChatGPT) / set CODEX_ACCESS_TOKEN (enterprise).",
    )
    return _Auth("none", "none", "unknown", reason)


def _doctor_auth_details(doctor: dict[str, Any] | None) -> dict[str, Any]:
    """The ``checks.auth.credentials.details`` mapping, tolerantly ({} if any layer missing)."""
    if not isinstance(doctor, dict):
        return {}
    checks = doctor.get("checks")
    auth = checks.get("auth.credentials") if isinstance(checks, dict) else None
    details = auth.get("details") if isinstance(auth, dict) else None
    return details if isinstance(details, dict) else {}


def _resolve_hook_seam(
    *,
    installed: bool,
    version: str | None,
    runtime: RuntimeSpec,
    features_hooks_enabled: bool | None,
    managed_only: bool,
) -> HookSeam:
    """Honest hook-delivery posture. This preflight never returns ``"active"`` (see module note).

    The ``"untrusted"`` verdict stays reserved: the codex_frontend Phase 1 probe
    (2026-06-10) found the ``[hooks.state]`` ``trusted_hash`` is not black-box
    computable and that enrollment survives worktrees with no record at the worktree's
    config path, so a per-hook enrollment read cannot produce a trustworthy verdict
    and is deliberately not implemented (``codex doctor`` exposes no trust signal
    either, Stage A). The normal enabled+version-OK case is ``"enrollment_gated"`` --
    a capability statement, NOT a per-home enrolled-state verdict: hooks can fire, but
    enrollment state is unchecked. ``"unknown"`` remains only for the moot cases --
    not installed, or version unparseable (the floor cannot even be proven, so we
    cannot assert hooks register).
    """
    if not installed:
        return "unknown"  # moot; ready is already False

    floor = runtime.hook_min_version
    if version is not None and floor is not None and _version_lt(version, floor):
        return "disabled"  # known-too-old. version is None (unparseable) does NOT imply disabled -> fall through.

    if features_hooks_enabled is False:
        return "disabled"

    if managed_only:
        return "managed_suppressed"  # explicit evidence only; a capability limit, not a ready blocker

    if version is None:
        # Unparseable version: the hooks floor cannot be proven, so we cannot assert hooks
        # even register -- the honest verdict stays "unknown".
        return "unknown"

    # Enabled, version meets the floor, not suppressed: hooks register/enable AND fire
    # once trust-enrolled, but enrollment state is unchecked by decision (Phase 1: the
    # trusted_hash cannot be validated, and a path-keyed [hooks.state] read would
    # false-negative in worktrees). Not a per-home enrolled claim.
    return "enrollment_gated"


class _Responses(NamedTuple):
    posture: ProxyResponses
    blocking_reason: str | None


def _resolve_responses_posture(proxy_id: str | None) -> _Responses:
    """Whether the chosen route can serve Codex its required Responses API.

    No ``--proxy`` -> ``native_direct`` (direct ``codex exec`` to OpenAI; preferred, not a
    blocker). With ``--proxy <id>``: read that *existing* proxy's ``proxy.yaml`` via the
    config loader (lazy import -- keeps this module light and avoids a ``core -> config``
    edge at import time; it reads the file and starts nothing). A proxy is
    ``proxy_supported`` only when its wire shape is ``openai_responses_passthrough``
    AND its source declares the ``responses_ingress`` capability -- the same
    conjunction the proxy ``/v1/responses`` route enforces, so a green preflight
    cannot 501 at launch. The ``openai_translated``/``anthropic_passthrough`` shapes
    serve Anthropic/OpenAI-chat, never Responses, so they are ``proxy_unsupported``.
    """
    if proxy_id is None:
        return _Responses("native_direct", None)

    from forge.config.loader import load_proxy_instance_config

    try:
        config = load_proxy_instance_config(proxy_id)
    except (ValueError, TypeError) as e:
        # The loader raises on an invalid id (path traversal), corrupt YAML, or a schema
        # violation. The preflight contract is fail-closed (never raise for an expected
        # condition), so surface it as proxy_unsupported instead of a traceback.
        return _Responses(
            "proxy_unsupported",
            f"proxy '{proxy_id}' is invalid or unreadable: {e} " "Omit --proxy to run native 'codex exec' directly.",
        )
    if config is None:
        return _Responses(
            "proxy_unsupported",
            f"proxy '{proxy_id}' not found (run 'forge proxy list'). "
            "Omit --proxy to run native 'codex exec' directly.",
        )

    # proxy_supported requires BOTH the responses passthrough wire shape AND a
    # source that declares responses_ingress -- the exact conjunction the proxy
    # /v1/responses route enforces (fail closed on an unknown/empty source).
    if config.wire_shape == "openai_responses_passthrough":
        from forge.backend.sources import ModelSourceNotFoundError, get_model_source

        source_id = getattr(config, "source", "") or ""
        try:
            if source_id and get_model_source(source_id).capabilities.responses_ingress:
                return _Responses("proxy_supported", None)
        except ModelSourceNotFoundError:
            pass  # fail closed -> proxy_unsupported below

    return _Responses(
        "proxy_unsupported",
        f"proxy '{proxy_id}' (wire_shape={config.wire_shape!r}) cannot serve the Responses API "
        "on its Codex-facing endpoint. Omit --proxy to run native 'codex exec' directly to OpenAI.",
    )


def _not_installed_reason(runtime: RuntimeSpec) -> str:
    cmd = runtime.headless_cmd[0]
    floor = runtime.hook_min_version or "0.131.0"
    return (
        f"Codex runtime '{cmd}' is not installed (not on PATH). "
        f"Tip: Install the Codex CLI (>= {floor}) so '{cmd}' is on PATH."
    )


# ── Version comparison ─────────────────────────────────────────────────────────────


def _version_tuple(v: str) -> tuple[int, ...]:
    """Leading numeric dotted components as an int tuple (stops at the first non-numeric)."""
    parts: list[int] = []
    for component in v.split("."):
        m = re.match(r"\d+", component)
        if m is None:
            break
        parts.append(int(m.group(0)))
    return tuple(parts)


def _version_lt(version: str, floor: str) -> bool:
    # Pad to equal length so a shorter version doesn't sort below an equal padded one
    # (e.g. "0.131" must NOT be < "0.131.0").
    v, f = _version_tuple(version), _version_tuple(floor)
    width = max(len(v), len(f))
    return v + (0,) * (width - len(v)) < f + (0,) * (width - len(f))


def _version_meets_floor(version: str | None, floor: str | None) -> bool:
    if version is None:
        return False
    if floor is None:
        return True
    return not _version_lt(version, floor)
