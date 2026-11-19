# Require dnspython 2.9.2

Dependabot alerts [69](https://github.com/hapa1i/multi-forge/security/dependabot/69) and
[70](https://github.com/hapa1i/multi-forge/security/dependabot/70) flag the same version, 2.9.0, in the runtime export
and the lock. The upstream fix for excessive memory and CPU use when parsing a DNS zone file first shipped in 2.9.2.
[Upstream advisory](https://github.com/rthalley/dnspython/security/advisories/GHSA-vvf4-9x63-8xvv)

Forge also declares a dnspython minimum in its wheel metadata because email-validator uses it. Raise that minimum to
2.9.2 so consumers using their own resolver receive the fix. Refresh the lock and its generated runtime export.
