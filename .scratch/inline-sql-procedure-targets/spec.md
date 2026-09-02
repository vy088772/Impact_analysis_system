# Inline SQL That Runs a Stored Procedure

Status: ready-for-agent

## Problem Statement

`/find_by_sp` answers "which programs call this stored procedure?" from one
field: a Database Invocation's `procedure_name`. An invocation classified as
inline SQL never has one, so a stored procedure reached through inline SQL text
is invisible to the reverse lookup — no match, and no diagnostic either.

Two shapes in `Y-Docs_TTPUR` land there.

The first is a bare procedure name. `SQLObject.CreateTable(strSql, strTableName)`
is a genuine inline-SQL overload, and the application calls it as
`CreateTable("[dbo].[usp_PUR_SO_ChangeReason]", "SP")`. T-SQL lets a batch omit
`EXECUTE` when the procedure call is its first statement, so the command text
runs the procedure exactly as an `EXEC` would. Nothing extracts a target from it:
`_embedded_exec_target` only looks after an `EXEC`/`EXECUTE` keyword. 11 call
sites, 6 stored procedures.

The second needs no new extraction at all. 25 invocations already carry an
Embedded Procedure Target rated `proven` against the SP Catalog — the evidence
is there, dated, and correct — but nothing downstream reads that field.
`find_by_sp` and the Execution Path builder both read `procedure_name`, which
stays empty. The evidence exists and the answer still does not.

## Solution

An inline SQL command text that is nothing but a procedure name yields an
Embedded Procedure Target, the same way an `EXEC` does, under its own reason so
the two provenances stay distinguishable.

The reverse lookup then asks a question neither field answers alone: **which
stored procedure does this invocation run?** A call that selected
stored-procedure mode answers with `procedure_name`. A call whose inline SQL
text executes a procedure answers with its Embedded Procedure Target, once that
target is rated `proven`. Anything below `proven` answers nothing — `likely` and
`unresolved` are candidates, and a candidate answering a reverse lookup would be
the guess this gateway refuses to make.

The two fields stay separate, and the target stays additional evidence, exactly
as they are today. `procedure_name` records what the call itself declared; the
target records what its text turned out to name, with the raw text, the rating,
and the database candidates behind it. Collapsing them would reverse a decision
this gateway already made on purpose — `test_external_text_wrapper_keeps_inline_exec_target_as_additional_evidence`
names it — and would re-rate Contracts that are not wrong. The invocation's mode
stays `inline_sql`, because that is what the wrapper overload does with the text.

## User Stories

1. As an analyst, I want `find_by_sp` to find a program that runs a stored procedure through inline SQL text, so that a call the database really makes is not missing from the impact answer.
2. As an analyst, I want a bare procedure name in a command text treated as running that procedure, so that omitting `EXEC` — which T-SQL permits — does not hide the call.
3. As an analyst, I want an inline SQL statement that merely mentions a procedure name in a larger query left alone, so that recognising bare names cannot invent a call.
4. As a reviewer, I want only a `proven` target to answer the reverse lookup, so that a candidate is never promoted into an answer.
5. As a reviewer, I want a bare name confirmed against the SP Catalog for the invocation's resolved database, so that a table or view name that happens to stand alone is not read as a procedure.
6. As a reviewer, I want the target's own reason to record whether the name came from an explicit `EXEC` or an implicit one, so that the two are still tellable apart after promotion.
7. As a reviewer, I want the invocation's mode left at `inline_sql`, so that this change records a target and never re-rates a Contract.
8. As a maintainer, I want one place that answers "which procedure does this invocation run", so that a reader never has to remember to check two fields.
9. As a maintainer, I want `procedure_name` and the Embedded Procedure Target left as the separate fields they are, so that this change adds a question rather than reversing an existing answer.

## Implementation Decisions

### Implicit EXECUTE

T-SQL executes a batch whose first statement is a bare procedure name, with or
without the `EXECUTE` keyword. A command text that, after leading whitespace and
comments, is one possibly-qualified identifier and nothing else is therefore an
`EXECUTE` of that identifier.

"Nothing else" is the whole guard. A command text with a second token — a
`SELECT`, a parameter, an operator, a second statement — is not this shape and
yields no target, which leaves every ordinary inline SQL statement exactly as it
is today. The identifier still has to be confirmed against the SP Catalog by the
existing rating step before it becomes anything; an unconfirmed name is rated
the same way an unconfirmed `EXEC` target already is.

### Executed Procedure Name

One property on a Database Invocation, reading `procedure_name` first and a
`proven` Embedded Procedure Target second. It names the question the reverse
lookup was already asking badly, and it is the only place either field is
combined — no caller has to remember to check both.

`/find_by_sp` reads it. The Execution Path builder is deliberately left reading
`procedure_name`: an inline SQL invocation with an embedded target has no
Database Invocation shape a path can be built from without re-rating the
Contract, and that is a separate question from whether the reverse lookup can
find the call.

### What this does not change

No existing field, mode, rating, or Contract. An invocation that was inline SQL
before is inline SQL after, with the same evidence and the same target; one more
question can now be asked of it.
