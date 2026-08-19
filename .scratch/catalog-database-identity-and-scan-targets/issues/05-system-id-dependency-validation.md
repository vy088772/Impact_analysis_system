# 05 — Verify Declared Dependencies Before Connecting

**What to build:** A mistyped Declared Database Dependency can no longer make the scan tool connect to a host nobody registered. Expanding a System's dependencies for a scan verifies each declared `{server, name}` against the Database Registry before any connection opens, and refuses with the offending pair named. The question-answering path deliberately does not perform this check.

**Blocked by:** 03 — the System flag this validates must exist first.

**Status:** ready-for-agent

- [ ] Expanding a System's Declared Database Dependencies verifies every pair against the Database Registry before any connection is attempted.
- [ ] A declared pair that the registry does not register refuses the run with an error naming the System, the offending pair, and where to register it.
- [ ] Verification happens before the first scan is issued, so a System with one bad pair scans none of its Databases rather than some of them.
- [ ] The question-answering path performs no such verification. An unmatched pair there degrades to a cache miss the service already handles, and never blocks a question.
- [ ] Server addresses are compared through the existing cache-identity normalization, so a short hostname in one file and a fully-qualified one in the other still match.
- [ ] Verification reads the registry only; it never writes to it, and never registers a missing pair.
- [ ] Tests cover: a fully-registered System expanding and scanning normally; an unregistered pair refusing before any scan is issued, with the System and pair in the message; a short-versus-qualified hostname pair still matching; and the question-answering path unaffected by an unregistered pair.
