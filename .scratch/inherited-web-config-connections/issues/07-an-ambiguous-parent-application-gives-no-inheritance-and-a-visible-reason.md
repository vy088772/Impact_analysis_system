# 07 — An ambiguous Parent Application gives no inheritance and a visible reason

**What to build:** When the analyzer cannot choose one Parent Application, it
does not inherit. It shows the reason in the scan result. The Evidence Status
of the call does not change. See the spec, section "Parent Application".

**Blocked by:** 05 — A child web application resolves a connection its Parent
Application declares

**Status:** done (2026-09-30)

- [x] Two candidate parents with the same longest path give no Parent
      Application.
- [x] Two projects with the same IIS URL give no Parent Application to each
      other.
- [x] The unresolved connections of the scan result hold the reason
      `ambiguous_parent_application` for the affected key.
- [x] `ambiguous_parent_application` is the only reason that the `Web.config`
      path records. Each other failed `Web.config` lookup stays silent.
- [x] The reason does not reach the rating of the Database Invocation. A call
      that was `likely` stays `likely`.
- [x] Seam A tests cover both ambiguous cases. Each test checks the reason of
      the answer that the view gives.
- [x] Scan result check: one test scans a fixture repository with the project
      scanner. It checks that the unresolved connections of the C# Scan Result
      hold `ambiguous_parent_application`.

## Comments

### 2026-09-30 — implementation notes

Files this ticket changed (other tickets run in parallel):

- `code_analyzer/parent_application.py`: new `AMBIGUOUS_PARENT_APPLICATION`;
  `_nearest_ancestor` gives `(path, ambiguous)`; new `ancestry_of` gives the
  chain and the flag. Two projects with the same IIS URL are ambiguous for each
  other. `parent_of` and `chain_of` keep their old results.
- `code_analyzer/connection_lookup.py`: `FileConnections` takes `ambiguous_parent`
  and `blocking_layers`. On the `Web.config` path a lookup that finds nothing
  gives the reason, unless a `<clear/>` or `<remove>` layer stops the key first.
  The key-as-name guess keeps its Database and also carries the reason.
- `code_analyzer/db_connection_tracker.py`: the tracker records this reason one
  time for one read (two patterns match one `new SqlConnection(...)` line). No
  other reason is deduplicated, so current coverage numbers do not change.
- Tests: 8 Seam A tests in `tests/test_connection_lookup.py`; one scan result
  test in `tests/test_connection_tracking.py`.
- Docs: ADR-0038, `CONTEXT.md` (Parent Application), `docs/進階手冊.md`.

Decisions:

- A same-URL twin makes the project ambiguous even when a real ancestor exists.
  This follows the spec wording. It hides that ancestor. A later ticket can
  change it.
- An ambiguous link with a child that declares no entry gives no connection
  source, as before. The scan result only gains the reason.

Test result: 1437 passed (same two files left out as tickets 05 and 06).

### 2026-09-30 — code review

- Spec: no missing criterion. Two gaps stay as a judgement: no test reads the
  Evidence Status of a call (the reason never reaches the gateway), and no
  tracker-level test apart from the scan result test.
- Standards: no hard breach. Fixed: the `CONTEXT.md` gap; the dedupe now covers
  this reason only; a `<clear/>` silence test. Smells that stay: the
  `(chain, ambiguous)` tuples could be one small type.

### 2026-10-01 — correction after the review of the whole effort

- The second decision above is not correct in each case. It is correct when
  the own `Web.config` of the child declares at least one entry.
- When each layer is empty, the view gives the key-as-name guess and also the
  reason `ambiguous_parent_application`. The key then shows in the connection
  sources and in the unresolved connections of the scan result.
- This result agrees with stories 17, 38, and 43 of the spec. The test
  `test_an_ambiguous_parent_application_keeps_the_key_as_name_guess_with_the_reason`
  pins it at the view. No scanner test pins it.
