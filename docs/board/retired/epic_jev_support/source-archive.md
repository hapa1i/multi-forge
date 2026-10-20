# Jev experiment source archive

The A2 rule-pack and A3 cascade experiments were removed after the initiative was retired. Their dedicated tests and
unused packaged rule/consent foundations were removed with them. A1's client, telemetry and transport probe remain
supported; see [the probe guide](../../../../scripts/experiments/jev/README.md).

Historical commands and verification counts in these retired cards describe the code at their recorded revisions. They
are not commands supported by the current checkout. The final complete source before removal is
[`39ba8cbb49d2ca3906f196edae2b139705a51bf1`](https://github.com/hapa1i/multi-forge/tree/39ba8cbb49d2ca3906f196edae2b139705a51bf1):

- [Experiment scripts](https://github.com/hapa1i/multi-forge/blob/39ba8cbb49d2ca3906f196edae2b139705a51bf1/scripts/experiments/jev/README.md),
  including their usage instructions.
- [Rule-pack design and ownership](https://github.com/hapa1i/multi-forge/blob/39ba8cbb49d2ca3906f196edae2b139705a51bf1/docs/design_rule_packs.md).
- [Packaged rule and consent modules](https://github.com/hapa1i/multi-forge/tree/39ba8cbb49d2ca3906f196edae2b139705a51bf1/src/forge/policy/rule_pack).
- [Evaluation tests](https://github.com/hapa1i/multi-forge/tree/39ba8cbb49d2ca3906f196edae2b139705a51bf1/tests/src/scripts).

To reproduce offline results, use a separate checkout of that revision and follow its instructions. Reports also bind
specific source hashes and revisions: use those when reproducing the original historical observation rather than the
last tooling version. Existing paid captures do not authorize new provider calls.

Human labels, corpora, manifests, captures and original source hashes remain unchanged under
[A2](../jev_rule_pack/card.md) and [A3](../jev_cascade/card.md). Recorded paths and hashes describe their original
sources; removal does not rewrite provenance or convert negative results into accepted consumer quality. These cards
remain retired, and any new use case begins with a new proposed card.
