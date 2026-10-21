# Dependency remediation evidence

The 2026-10-22 read-only Dependabot API snapshot contains 27 open alerts, numbered 34 through 60, all in `uv.lock`.
[alerts.json](alerts.json) records each advisory and affected range. Package spelling is normalized for comparison;
PyJWT's 14 alerts remain distinct.

Auditing all 126 third-party registry packages also found [six additional advisories](additional-advisories.json),
bringing this PR's scope to 33 advisories across seven affected packages. The additional audit covered development and
platform-specific lock entries as well as runtime dependencies.

## Resolution and packaging

| Package          | Previous lock | Candidate lock | Dependency path                    |
| ---------------- | ------------- | -------------- | ---------------------------------- |
| aiohttp          | 3.14.3        | 3.14.5         | Forge and LiteLLM                  |
| certifi          | 2026.7.22     | 2026.10.19     | HTTP clients and SDKs              |
| multidict        | 6.7.1         | 6.9.1          | aiohttp and yarl                   |
| oauthlib         | 3.3.1         | 4.0.0          | fastapi-sso                        |
| PyJWT            | 2.13.0        | 2.15.1         | Forge and fastapi-sso              |
| urllib3          | 2.7.0         | 2.8.0          | botocore and requests              |
| virtualenv       | 21.7.8        | 21.14.12       | pre-commit only                    |
| python-discovery | 1.6.0         | 1.6.4          | Required by the patched virtualenv |
| yarl             | 1.24.5        | 1.25.1         | Required by the patched aiohttp    |

Runtime floors are ordinary project requirements, so wheel installers enforce them without uv's repository-only
constraints. Virtualenv keeps its existing development constraint location. LiteLLM 1.102.0, FastAPI and Starlette are
unchanged. No other package version changes are intended.

## Advisory review

- [aiohttp 3.14.4](https://github.com/aio-libs/aiohttp/releases/tag/v3.14.4),
  [multidict 6.9.1](https://github.com/aio-libs/multidict/releases/tag/v6.9.1),
  [urllib3 2.8.0](https://github.com/urllib3/urllib3/releases/tag/2.8.0) and
  [virtualenv 21.7.13](https://github.com/pypa/virtualenv/releases/tag/21.7.13) provide the minimum releases for their
  captured alerts.
- [OAuthlib 4.0.0](https://github.com/oauthlib/oauthlib/releases/tag/v4.0.0) removes JSONP revocation support and
  includes constant-time PKCE comparison. The PKCE upstream advisory also names an earlier patched release, but 4.0.0 is
  required to cover both alerts. Fastapi-sso 0.22.0 accepts this version and uses `WebApplicationClient`, not the
  removed server-side JSONP surface.
- PyJWT's [options mutation advisory](https://github.com/advisories/GHSA-gvp8-978c-rx2q) has no patched-version field in
  the snapshot, but its affected range ends at 2.13.0. Tagged
  [2.15.0 source](https://github.com/jpadilla/pyjwt/blob/2.15.0/jwt/api_jwt.py) copies caller options in
  `_merge_options` before modifying them. The packaged floor also covers the alerts requiring 2.15.0.
- [Certifi's advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) describes
  compromised emSign trust roots. The selected 2026.10.19 release preserves their removal and
  [restores unaffected roots](https://github.com/certifi/python-certifi/commit/662df63d7906df66f1f07c0751a3dfe9da14d914).
- Virtualenv 21.14.9 covers the five additional shell/launcher advisories. The selected
  [21.14.12 release](https://github.com/pypa/virtualenv/releases/tag/21.14.12) also bundles
  [pip 26.2.2](https://pip.pypa.io/en/stable/news/#v26-2-2), which updates its vendored certifi trust bundle.

These upgrades protect newly resolved environments. Existing generated launchers require environment recreation per the
[virtualenv advisory](https://github.com/pypa/virtualenv/security/advisories/GHSA-c978-59m8-c77v); old container images
and explicitly supplied CA bundles are not rewritten by this dependency change.

## Validation

Before changing dependencies, the metadata regression failed for all five affected runtime floors and passed its two
unchanged controls. This confirms that lock-only constraints could not protect wheel installations. The final focused
file passes all eight tests, including the additional certifi floor. `make build` passes for both the wheel and source
distribution.

All 27 captured vulnerable ranges exclude the final locked versions. A final pip-audit 2.10.1 scan through the PyPI
service reports zero known vulnerabilities among all 126 third-party registry packages, with no skipped packages. The
audit uses pinned requirements generated directly from every registry entry in `uv.lock`, without platform filtering:

```bash
.venv/bin/python - <<'PY' > /tmp/forge-dependency-audit.txt
import tomllib
from pathlib import Path
for package in tomllib.loads(Path("uv.lock").read_text())["package"]:
    if "registry" in package.get("source", {}):
        print(f"{package['name']}=={package['version']}")
PY
uvx pip-audit==2.10.1 --no-deps --disable-pip --progress-spinner off -r /tmp/forge-dependency-audit.txt
```

The local OAuth compatibility check passed with sockets disabled: fastapi-sso 0.22.0 and OAuthlib 4.0.0 construct an
authorization URL, prepare a PKCE token request, parse a local token response and attach a bearer token successfully. No
token exchange was dispatched.

`FORGE_WHEEL_SMOKE_PYTHON=3.11 ./scripts/test-wheel-runtime.sh` passed on Python 3.11.14. Its clean environment resolves
outside `uv.lock`: all six patched runtime versions match the table, with LiteLLM 1.102.0 and fastapi-sso 0.23.0.
Dependency compatibility, startup, local liveliness and cleanup passed; virtualenv and python-discovery are absent from
the runtime environment.

A disposable `virtualenv --no-download` environment passed its generated pip launch and `pip check`. The bundled seed is
pip 26.2.2 with vendored certifi 2026.10.19; the environment was removed after verification.

`make test-regression` passed all 2,091 tests. Full `make pre-commit` passed, including Markdown links and file limits.
The first `make test` unit run had 11,137 passes and one failure in the unchanged watchdog timeout test
(`test_deadline_reports_timeout`, expected `TimeoutExpired` was not raised). The whole watchdog file then passed all six
tests. The full `make test` confirmation without a concurrent regression suite passed all 11,138 unit tests (117
deselected) and all 523 integration tests (13,385 deselected). Docker image build, runtime preflight and exact-wheel
release/walkthrough image tests passed. The initial timeout failure did not recur; no watchdog code or test changed.

Test runs unset provider credentials and set `PYTHON_DOTENV_DISABLED=1`. No model inference or native-client trial is
part of this maintenance task.
