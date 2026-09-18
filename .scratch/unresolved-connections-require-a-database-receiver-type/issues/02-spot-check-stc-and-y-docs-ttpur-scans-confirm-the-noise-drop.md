# 02 — Spot-check STC and Y-DOCs/TTPUR scans confirm the noise drop

**What to build:** Re-scan or re-parse two systems other than IQCS — STC
(`data/scan_cache/fbe54427b2bf7db0.pkl`) and Y-DOCs/TTPUR
(`data/scan_cache/ee4df0cc3ec5f807.pkl`) — with Ticket 01's filter in place,
and confirm each system's `unresolved_connections` count drops to only
entries whose receiver carries a database-shaped declared type, with no
system-specific code change needed to get that result. This confirms the fix
generalizes past IQCS, per the spec's uniform-application requirement.

**Blocked by:** 01 — Filter `unresolved_connections` candidates by
database-receiver type

**Status:** ready-for-agent

- [ ] STC's refreshed scan cache shows every remaining `unresolved_connections`
      entry naming a database-shaped receiver type; any prior entry for a
      non-database receiver (config/HTTP/logging/email-shaped) is gone.
- [ ] Y-DOCs/TTPUR's refreshed scan cache shows the same.
- [ ] `connection_sources` for both systems is unchanged from before Ticket 01.
- [ ] No system-specific code change was needed to get this result.
