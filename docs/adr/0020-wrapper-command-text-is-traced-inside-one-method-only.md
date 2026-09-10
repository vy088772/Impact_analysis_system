# Wrapper Command Text Is Traced Inside One Method Only

**Status:** Accepted
**Date:** 2026-09-09

## Context

`CSharpAnalyzer.ResolveCommandTextArgument` reads a wrapper call's command text only when the call site passes a string literal. Any other expression yields `commandTextKind = "dynamic"` and no procedure name.

WebForms code tolerated that rule. ASP.NET Core code does not, and the two systems measured disagree about which shape they use:

```
IQCS         262 wrapper calls   variable 261 (usp 209, _spName 44, sqlCmd 8), literal 1
RTTalentDB   213 wrapper calls   literal 204, method parameter 9
```

Under the current rule IQCS resolves one procedure name out of 262. Every other call becomes an unresolved invocation, and the system's stored-procedure relations are effectively empty.

`ReadCommandTextCandidates` already walks an identifier back to the declarations and assignments that precede it inside the same method. It was written for the direct ADO.NET path and was never wired to the wrapper path. Measured against IQCS, 253 of the 261 variable call sites hold the literal assignment inside the same method, either as `string usp = "[dbo].[usp_...]"` or as a field assignment a few lines above the call.

## Decision

The wrapper path uses `ReadCommandTextCandidates` to resolve its command text. The analyzer does not follow a command text across a method boundary. A command text that arrives as a method parameter stays unresolved and carries its own reason code.

## Consequences

- IQCS moves from 1 resolved procedure name to roughly 254 of 262. RTTalentDB's 9 parameter-carried calls and IQCS's 8 remaining calls stay unresolved, and say why.
- Interprocedural constant propagation would recover those 17 calls, which is 3.6 per cent of the two systems' invocations. It is a different class of analysis, and it belongs to its own decision rather than to this one.
- WebForms projects share this code path, so their resolved counts rise too. A count that rises is not proof of correctness, which is why the Y-DOCs baseline is captured before this change and compared after it.
