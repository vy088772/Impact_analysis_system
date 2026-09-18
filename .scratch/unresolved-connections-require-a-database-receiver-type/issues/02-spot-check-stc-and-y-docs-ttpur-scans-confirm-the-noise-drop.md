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

**Status:** done

- [x] STC's refreshed scan cache shows every remaining `unresolved_connections`
      entry naming a database-shaped receiver type; any prior entry for a
      non-database receiver (config/HTTP/logging/email-shaped) is gone.
- [x] Y-DOCs/TTPUR's refreshed scan cache shows the same.
- [x] `connection_sources` for both systems is unchanged from before Ticket 01.
- [x] No system-specific code change was needed to get this result.

---

**Note (verification):** Re-scanned both named systems with
`scan_store.get_or_scan(root, refresh=True)` — no code change, this ticket
is verification-only. Both caches moved from `cache_version` 37 (pre-fix) to
38 (post-fix), same `source_commit` as before (the systems' own source did
not move).

STC and Y-DOCs/TTPUR each had **zero** `unresolved_connections` entries
already, before Ticket 01's filter existed (checked against the pre-refresh
pickle, which cache-version 37 predates). So the first two checklist items
hold, but vacuously — there was no noise in these two systems to drop, only
absence of noise to preserve. `connection_sources` is confirmed unchanged
by file-key-set equality (not just count): STC 24 files, Y-DOCs/TTPUR 539
files, identical key sets before and after.

Because a vacuous result doesn't itself confirm the fix *generalizes* (the
spec's actual concern per Story 7), extended the spot-check to the two
systems in the whole `data/scan_cache/` (all systems at `cache_version` 37)
that did carry pre-fix `unresolved_connections` noise — TOPCSCY and
RTTalentDB, the same pair the companion Razor-helper investigation's own
ticket 02 fell back to for the identical reason. Re-scanned both:

- TOPCSCY: 1101 → 242 entries (78% dropped); `connection_sources` unchanged
  at 714 files.
- RTTalentDB: 175 → 70 entries (60% dropped); `connection_sources` unchanged
  at 381 files.

The remaining entries in both fall entirely into the two irreducible
categories Ticket 01's own note already named — no new or system-specific
noise shape appeared:
1. A receiver rooted at a BCL/static type with no local variable declaration
   (`DateTime`, `string`, `decimal`, `Regex`, `HttpUtility`, `File`,
   `Directory`, `Path`, `Convert`, `Enumerable`, `ColorTranslator`).
2. A locally declared type that happens to end in `Context` but is a
   framework object, not a database context (`HttpContext context`,
   `ValidationContext validationContext`, `context.Session`).

No per-system code change was made or needed to get any of these four
results — every system used the same shared filter Ticket 01 shipped.
