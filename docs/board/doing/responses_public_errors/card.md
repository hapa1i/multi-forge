# Keep internal validation errors out of Responses replies

[CodeQL alert 35](https://github.com/hapa1i/multi-forge/security/code-scanning/35) found that Responses ingress sent
exception text to clients when source resolution or request preparation failed. Callers need a request ID and a
diagnostic they can act on. Internal exceptions can include configuration or library details.

Use fixed public messages for unexpected validation failures. The request-policy validator can supply specific guidance
for a known refusal, such as an unsupported tool under required ZDR. [Execution checklist](checklist.md)
