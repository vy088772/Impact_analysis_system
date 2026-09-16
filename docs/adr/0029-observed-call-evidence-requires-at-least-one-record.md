# Observed Call Evidence requires at least one record

We wanted the analyzer to clear a wrapper method that touches no database by itself, so that a
maintainer writes no exclusion entry for it in each of about one hundred Systems. The first rule we
tried — clear any method whose Local Implementer holds no database-touching record — is unsafe, and
the real IQCS checkout proves it: the scan does not record a call to another method inside the same
project, so `IUtilityService.ViewPath`, which only builds a path string, and
`IUtilityService.GetListFromSysParam`, which reaches a database through a sibling method, both hold
zero records and are indistinguishable. Observed Call Evidence therefore requires at least one
record, and clears a method only when every record it holds names no database receiver type. A
method holding no record at all stays in review.

**Consequences:** a method that genuinely touches nothing, but calls only helpers the scan does not
record, is not cleared and still needs a hand-written exclusion entry — `ViewPath` is exactly that
case. We preferred that cost to a false exclusion, which hides a real database call and is
invisible once made. A call graph in the analyzer host would remove the limitation, and we left it
out until the remaining review noise justifies it.
