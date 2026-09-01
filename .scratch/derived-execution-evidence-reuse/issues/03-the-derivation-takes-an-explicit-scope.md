# 03 — The derivation takes an explicit scope instead of a request

**What to build:** A named identity for the scope that Derived Execution Evidence
belongs to, so that later tickets have something to key reuse on. Behaviour does
not change at all; this is the prefactor that makes the change after it easy.

Today the derivation is handed a whole request and pulls fields off it
defensively, because four different request shapes reach it and not all of them
carry the same fields. That is workable while the result is thrown away every
time, and unworkable the moment the result has to be retained: "whatever this
request happened to carry" cannot be a key, and a key assembled ad hoc at each
call site would drift between them.

After this ticket the derivation is asked for a scope, and the scope is derived
from a request in exactly one place.

**Blocked by:** 01 (the scope is named using the agreed term).

**Status:** done

- [x] The scope identity covers the repository scan roots, the complete Database
      identity the request routes to, and the wrapper contract selector
- [x] The scope is built from a request in one place, not at each call site
- [x] The derivation is asked for a scope rather than reaching into a request for
      the fields it needs
- [x] Every existing call site is migrated, including the ones that derive over a
      subset of files chosen by requested program names
- [x] No behaviour changes: the whole existing suite passes unmodified
- [x] Two requests differing only in a field that cannot change the derived
      evidence produce the same scope identity
- [x] Two requests differing in the Database identity, or in the wrapper contract
      selector, produce different scope identities
- [x] The scope identity is comparable and usable as a key by construction, so a
      later ticket does not have to reshape it

**Note:** Added `DerivedExecutionEvidenceScope`, a frozen dataclass in
`service/analyze_service.py`, with a single classmethod builder
`.of(req, roots)` that reads `database`, `db_server` (normalized through
`sql_cache_store.normalize_server`, so a named-instance suffix or a case
difference that resolves to the same cache never forks the scope), `db_name`,
and `wrapper_contract` off a request, plus the resolved repository scan
roots. `_rated_execution_invocations` — the derivation itself — now takes
this scope and no longer touches `req` at all; every one of its 7 call sites
(`analyze()`, `get_path_evidence()`, `find_by_sp()`, `find_by_table()`, and
both `flow_chain()` branches) builds the scope once, right after resolving
its scan roots, through `DerivedExecutionEvidenceScope.of()` — the one
canonical builder — and threads that same instance down, including the two
`analyze()` call sites that derive over a program-name-filtered subset of
files.

One compromise, made deliberately and documented in code:
`_build_program_execution_paths()` keeps its original 4-positional-argument
signature and gains a keyword-only `scope: Optional[...] = None`, building
one internally from `[root]` only when the caller omits it. Several
pre-existing tests in `tests/test_execution_path_integration.py` call this
private helper directly with the old 4-argument shape, and the ticket
requires them to keep passing unmodified; `analyze()` itself always passes
its own request-level scope explicitly, so production behaviour is
unaffected. A code review flagged this as a small, judgement-call Divergent
Change, worth removing once those direct-call tests are migrated to pass a
scope — noted here for a later ticket, not fixed now since it is outside
ticket 03's no-behaviour-change mandate.

Added `tests/test_derived_execution_evidence_scope.py` (8 tests) pinning the
scope's equality contract directly at `DerivedExecutionEvidenceScope.of()`:
identical requests produce an equal, equal-hash scope; fields outside the
scope (`program_names`, `question`, `refresh`, `max_paths`, `system`, …)
never change it; a server name that resolves to the same cache never changes
it; a non-string wrapper contract selector folds to the same scope as an
empty one (matching what the derivation already treated as contract-less);
a different database, db_server, db_name, wrapper contract, or set of
repository scan roots always changes it; and an instance works as a dict
key.

Ran the full suite before and after the change (`git stash -u` / `pop`) and
diffed the failing-test lists: identical — the same 12 pre-existing
failures (unrelated to this repository area; environment/ordering issues
predating this ticket) on both sides, plus the 8 new tests passing. Two test
files (`test_search_roles.py`, `test_sp_tables.py`) fail collection in this
environment because it has no ODBC driver for a live SQL Server connection;
confirmed identical on baseline HEAD, so excluded from both runs rather than
counted as a regression. No mypy config exists in this repository;
`python -m py_compile` and an `ast.parse` pass confirm the file is
syntactically sound.

Two review sub-agents ran the Standards and Spec axes in parallel. Both came
back with no hard issues — Standards flagged the
`_build_program_execution_paths` fallback above as a judgement call (already
documented and accepted), and Spec confirmed the scope's three components
match ADR-0013 exactly, all seven derivation call sites and the one
`_build_program_execution_paths` call site are migrated, and no reuse/
caching behaviour was added ahead of ticket 04/05.

**Follow-up (re-review after ticket 04 landed):** re-ran the Standards and
Spec axes against this ticket's actual committed diff (`0f21b59...5213cb4`),
this time against the current working tree so ticket 04's later additions
were visible for comparison. Spec came back fully clean: all 8 checklist
items verified independently against the diff (not just the Note above), no
scope creep (confirmed the ticket 04 retention machinery visible in the
current tree is genuinely absent from this ticket's own diff range), and the
Note's claims matched the actual code. Standards flagged three real,
verified inconsistencies in `DerivedExecutionEvidenceScope`'s docstring and
`.of()`'s signature — a Markdown-style `[ADR-0013](../docs/adr/...)` link
(this file cites ADRs as plain inline text everywhere else, e.g. `ADR-0009`,
`（ADR-0012）`) and two unnecessary quoted forward references (`"Derived
ExecutionEvidenceScope"`) despite the file already having
`from __future__ import annotations`, which makes every annotation in it a
string at runtime already. Both were fixed directly (plain `ADR-0013` text;
unquoted type hints), and the identical Markdown-link pattern was also found
and fixed in ticket 04's own `_RatedInvocationsValidityStamp` docstring for
consistency, since it would otherwise have reintroduced the same flagged
smell two commits later in the same file. A claimed "this file's docstrings
are one-liners" finding was checked and rejected: a direct count found 16
multi-line vs. 14 single-line docstrings in this file, so the class's
longer, multi-paragraph docstring was left as-is. Full suite re-run after the
fix: identical 12 pre-existing failures, 593 passed (no regressions).
