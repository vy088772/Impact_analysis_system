# The Command Mode resolves at rating time, and the scan stays free of Contract knowledge

An accepted Contract resolved none of its calls. The analyzer decided the Command Mode during the
scan, from a fixed list of method names, so every wrapper outside that list recorded `unknown` for
ever — and a Contract accepted after the scan could not change a cached result. We considered
giving the analyzer host a Contract input channel and re-scanning the affected files whenever a
Contract was accepted; that needed a trigger, a refinement marker in the cache, a termination rule
for the second pass and a new report line, and it would have made the scanner read configuration,
which this codebase deliberately keeps out of it. Instead the scan records Observed Argument Facts
for every argument of a wrapper call, with no Contract knowledge at all, and the analysis gateway
reads the Contract's argument roles at rating time. A Contract accepted today therefore resolves
calls in a scan captured yesterday, and none of that machinery exists.

**Consequences:** the scan output gained a field, so the scan cache version rose and every System
re-scans once on its next refresh. That is the mechanism this repository already uses for a scan
schema change, and it costs less than the machinery we did not build. The `true`/`false` convention
now lives in two places — in the analyzer host for a local wrapper, and in the gateway for an
external one. We accepted that duplication rather than move the local wrapper path into the rating
step, which is a larger change; the two implementations can drift, and a change to either one
should check the other.
