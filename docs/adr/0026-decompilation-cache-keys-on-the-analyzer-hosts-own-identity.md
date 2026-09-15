# Decompilation cache keys on the analyzer host's own identity, not just the DLL's

We found a `SQLDbContext` decompilation cached as incomplete (`database_behavior_surface_incomplete`)
weeks after the analyzer host gained the ability to classify it correctly (the Delegated Method
rule). The cache only keyed on the external DLL's Assembly Revision Boundary, so an analyzer
improvement never invalidated the old negative result — it would have been trusted forever. The
cache document now also stores a hash of the compiled `StaticAnalyzerHost` binary itself, the same
technique already used for Assembly Revision Boundary identity, and treats a mismatch as a cache
miss rather than relying on a schema-version constant someone has to remember to bump.

**Consequences:** rebuilding the analyzer host, even for an unrelated change, invalidates every
system's decompilation cache at once, forcing a full re-decompile on each affected receiver's next
refresh. This trades a slower first refresh after a host rebuild for never silently trusting a
stale classification again.
