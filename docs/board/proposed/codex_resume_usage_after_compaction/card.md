# Measure direct Codex resume usage after compaction

Forge reports unknown tokens for every direct headless resume on a thread with any prior compaction. A clean turn after
compaction can therefore finish successfully and still contribute no tokens to activity. The existing subscription
measurement covers an uncompacted thread. [Native resume accounting](../../done/codex_native_resume_usage/card.md)

## Measurement

- Use a disposable subscription login and record the Codex version. Start a top-level thread, compact it, exit Codex,
  then resume the same thread in a new process twice. Capture the last token sample before and after compaction and
  immediately before each resume.
  [Subscription fixture procedure](../../../developer/verification.md#codex-runtime-consumer-lanes-and-supervision)
- For each resume, compare the raw JSONL terminal counters, the change in rollout totals, and the sum of appended
  request records for input, cached input and output. Retain byte offsets, turn identities and the evidence needed to
  distinguish a fresh sample from a carried-forward one. Include a resume with a nonzero cached baseline.
- If those observations establish a comparable post-compaction baseline, specify how Forge recognizes it and test the
  verified delta through the usage event, attempt and activity row. Exercise an intervening compaction or counter reset
  where attribution remains ambiguous. If the measurements disagree, retain unknown usage and document why.

Forked threads have inherited history and need their own evidence before their accounting changes.
