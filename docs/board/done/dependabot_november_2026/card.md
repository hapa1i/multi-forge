# November dependency security fixes

## Goal

Resolve Dependabot alerts 63-68 by raising OAuthLib to 4.0.1 and pyasn1 to 0.6.5. Keep the update limited to the
affected packages and preserve the current runtime/build graph.

## Advisory evidence

The repository's authenticated Dependabot API reported six open high-severity alerts on 2026-11-10:

- Alerts 67-68: OAuthLib device-code token validation,
  [GHSA-3jp2-3mrg-2vxc](https://github.com/oauthlib/oauthlib/security/advisories/GHSA-3jp2-3mrg-2vxc), patched in 4.0.1.
- Alert 63: pyasn1 container decoding,
  [GHSA-fm9c-5rcf-2q5p](https://github.com/pyasn1/pyasn1/security/advisories/GHSA-fm9c-5rcf-2q5p).
- Alert 64: pyasn1 constructed string/ANY decoding,
  [GHSA-9m75-vc3g-4x39](https://github.com/pyasn1/pyasn1/security/advisories/GHSA-9m75-vc3g-4x39).
- Alert 65: pyasn1 binary REAL decoding,
  [GHSA-mm57-4v3p-rchx](https://github.com/pyasn1/pyasn1/security/advisories/GHSA-mm57-4v3p-rchx).
- Alert 66: pyasn1 constructed BIT STRING decoding,
  [GHSA-2qm8-x737-gmw5](https://github.com/pyasn1/pyasn1/security/advisories/GHSA-2qm8-x737-gmw5).

All four pyasn1 advisories identify 0.6.5 as the first patched release.

## Scope

OAuthLib is a direct runtime dependency and is also required by fastapi-sso. Its security floor must be present in wheel
metadata and the generated runtime export. pyasn1 is reached only through
`provider-check -> google-genai -> google-auth -> pyasn1-modules`; update its existing uv constraint without adding the
optional tooling dependency to the wheel runtime.

Follow [dependency security policy](../../../developer/dependency_security.md). Host inventory showed no running managed
proxies or local backends before the update. Verify the patched wheel and rebuild both repository image layers.
