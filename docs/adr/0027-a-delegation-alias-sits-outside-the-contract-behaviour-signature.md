# A Delegation Alias sits outside the Contract behaviour signature

The decompiler finds a Delegated Method but records it only in the decompilation cache, so a call
to the delegating name matches no Contract at all. In IQCS that name is
`usp_ExecCmdGetDataTableAsync` — the most-used data access method in the codebase, 196 calls, none
of which resolved. A Contract now carries a Delegation Alias for each Delegated Method, derived by
following the delegation chain to the operation that performs the work, so one lookup answers a
call site match and no alias ever points at another alias. The alias collection sits outside the
behaviour signature because the registry computes the Contract Fingerprint from that signature
alone: putting aliases inside would mint a new fingerprint for a behaviour that did not change, and
every System that reuses this Contract by fingerprint would stop reusing it.

**Consequences:** the raw Delegated Method record stays non-transitive, exactly as it always was —
only the alias derivation follows a chain, and the two are separate terms for that reason. A call
matched through an alias reports the method name the source code uses, and records the alias beside
it, so a review line still names a symbol a maintainer can search for in the repository.
