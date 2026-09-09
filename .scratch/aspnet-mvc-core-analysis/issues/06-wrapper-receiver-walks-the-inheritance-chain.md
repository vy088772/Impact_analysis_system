# 06 — Wrapper receiver resolution walks the inheritance chain

**What to build:** A data-access call made on a locally declared type that inherits its method from
an external assembly binds to that external type's Contract.

Every measured Core repository writes its data access this way: a local database
context derives from a base class in a shared external library, and the wrapper
method is declared on the base. Contract lookup keys on the receiver type, so a
local subclass currently matches nothing and the call is not recognised as a
wrapper invocation at all.

Keying on the declaring type also means the three repositories that share the
library do not each need their own hand-registered Contract. Their assemblies
are three different revisions, and the existing Assembly Revision Boundary
already keeps those snapshots apart.

**Blocked by:** 05.

**Status:** done

- [x] Receiver type resolution walks the inheritance chain to the type that declares the invoked method.
- [x] The Contract is keyed on that declaring type, not on the local subclass.
- [x] A call on a local context deriving from an external base is recognised as a wrapper invocation.
- [x] A receiver whose declaring type cannot be determined stays unresolved and names why, rather than binding to a guess.
- [x] A wrapper whose method is declared on the receiver's own type binds exactly as it does today.
- [x] Two repositories carrying different revisions of the same external library still produce two separate snapshots.
- [x] Running the analyzer over a measured Core repository reports wrapper invocations where it reported none.

## Note

### The whole defect was one line

Ticket 05 gave the host a real semantic model, and the previous
`06-resolve-overload-from-bound-symbol` ticket already bound each external wrapper call to one
exact method symbol. So the analyzer *already knew* the answer. Measured on IQCS before this
change:

```
wrapper_method_identity: "SQLDbContext.usp_ExecCmdGetDataSetAsync(string,...SqlParameter[],bool)"
wrapper_receiver_type:   "IQCSContext"
```

The bound symbol names the declaring type, and the receiver type reported the subclass beside it.
`CreateUnavailableInvocation` filled `WrapperReceiverType` from `ResolveExternalReceiverType` — a
syntax-only walk to the receiver variable's *declared* type — while the bound symbol sitting in
the same call was thrown away for this purpose. Keying on `method.ContainingType.Name` is the
whole fix; everything else below is the guard rails around it.

### Where the code is

`tools/StaticAnalyzerHost/CSharpAnalyzer.cs`:

- `BoundWrapperSymbolFacts` gains `DeclaringTypeName` (`method.ContainingType.Name`). The compiler
  resolves a call on a subclass that does not override to the *base's* own symbol, so its
  containing type is exactly the type a Contract must be keyed on.
- `ResolvedReceiverType` — a small record naming the four outcomes, so the receiver type and the
  provenance beside it stop travelling as a bare tuple: `None`, `Declaring`, `ReceiverDeclaration`,
  `Unresolved`.
- `ResolveWrapperReceiverType` — the rule itself.
- `InheritsTheInvokedMethod` — the guess guard, below.
- `DeclarationIndex<T>` — one memoized corpus index, now shared by `GetClassDeclarations` and the
  new by-simple-name lookup instead of a second hand-rolled copy of the same memo.

`code_analyzer/csharp_analysis_gateway.py`: `_unresolved_receiver_reason` distinguishes the three
absences a missing contract selection can have.

### The rule, and the two limits on it

**The declaring type replaces a receiver type; it never invents one.** If the syntax resolved no
receiver type at all, nothing is reported, exactly as before. This is not tidiness — the reviewed
wrapper exclusions in `config/wrapper_review_exclusions.json` are keyed on an exact
`(receiver_type, method_name)` pair, and 16 of STC's 18 entries carry an *empty* receiver type
(`Path.Combine`, `File.Exists`, `String.Format` …). Filling those in would silently overturn 167
human triage decisions in one commit. Measured before and after: STC holds at
**167 `reviewed_exclusion`**, unchanged.

**When the compiler cannot bind, an inheriting receiver stays unresolved.** Without a semantic
model the syntactic answer is the subclass, which is a guess about which type declares the method.
`InheritsTheInvokedMethod` catches exactly that case — the corpus declares the receiver's type,
that declaration has a base list, and no part of it declares the invoked method — and the host then
reports no receiver type plus provenance `declaring_type_unresolved`. The gateway turns that into
its own reason code rather than the older, vaguer `receiver_type_missing`:

| provenance | gateway reason |
| --- | --- |
| `declaring_type` | (receiver matched a Contract, or `no_contract_matches_receiver_type`) |
| `receiver_declaration` | as above — this is the pre-ticket answer |
| `declaring_type_unresolved` | `declaring_type_unresolved` |
| *(blank)* | `receiver_type_missing` |

That guard is not hypothetical. Scanning EnterpriseApi as one root spanning six projects builds no
compilation, and **215 calls** land there instead of keying a Contract on `EIPContext`,
`YMTGroupAppContext`, and their siblings.

The by-simple-name lookup is deliberate and one-directional. A receiver's declared type arrives as
bare source text with no namespace, so two same-named types in different namespaces share one
bucket. That errs safely: a namesake declaring the method makes the guard *not* fire, which falls
back to the pre-ticket answer. A collision can cost the new rule; it can never make an answer worse
than the old one.

### Measured

Wrapper calls per project, before → after. The call *count* never moves; what moves is which type
each is keyed on.

| Project | Files | Calls | Receiver was | → keyed on `SQLDbContext` |
| --- | --- | --- | --- | --- |
| IQCS | 267 | 1128 | `IQCSContext` | **262** |
| EnterpriseApi | 214 | 771 | `EFNETDBContext`, `EIPContext`, `YMTGroupAppContext`, `eFinanceDContext`, `eHRISContext` | **127** |
| EnterpriseApp | 151 | 356 | `EIPContext`, `YMTGroupAppContext` | **86** |
| RTTalentDB | 376 | 596 | `RTTalentDBContext` | **2** |
| ETR | 50 | 278 | `ETRContext` | **1** |

**478 calls** across five Core projects. Through the gateway against a `SQLDbContext`-keyed
contract, all 262 IQCS calls move from `receiver_mismatch` to receiver-matched. They do not reach
`explicit_selected` yet: no real `SQLDbContext` Contract exists, because decompiling
`CommonLibrary.dll` into one is Contract Onboarding's job, not this ticket's. This ticket owns the
receiver binding, and the receiver binding is what moved.

WebForms regression, the spec's user stories 35 and 36:

| Repository | Before | After |
| --- | --- | --- |
| Y-DOCs TTPUR (541 files) | 6033 calls, **933 `SQLObject`** | 6033 calls, **933 `SQLObject`** |
| STC (24 files) | 215 calls, 167 `reviewed_exclusion` | 215 calls, 167 `reviewed_exclusion` |

TTPUR runs in 2.1 minutes, the same figure ticket 05 recorded.

### One consequence worth knowing about

The same rule applied uniformly re-shapes the receiver type of *non-database* calls too, because
the declaring type is genuinely a different name from the receiver's declared type:

- Keyword to framework name: `string` → `String`, `decimal` → `Decimal`, `int` → `Int32`.
- Generic argument dropped: `List<string>` → `List`, `IDictionary<string, string>` → `IDictionary`.
- Extension methods key on the static class that declares them: `ILogger<T>.LogInformation` →
  `LoggerExtensions`, `IConfiguration.GetValue` → `ConfigurationBinder`,
  `HttpContext.GetRouteValue` → `RoutingHttpContextExtensions`.
- Inherited WebForms members walk up too: `GridViewRow.FindControl` → `Control`.

Every one of these is correct — that *is* the type that declares the method — and none changes a
call count. It changes how review-list entries group, and it means a future exclusion entry must be
written against the declaring type. STC survived only because exclusion matching casefolds, so its
one non-empty `string` / `Replace` entry still matches `String`. This is recorded because the next
maintainer to add an exclusion needs to know which name to write.

### Tests

`tests/test_wrapper_receiver_declaring_type.py`, six tests, five red before the change:

- `test_inherited_wrapper_call_reports_the_declaring_type_as_its_receiver` — real IQCS, real host.
- `test_inherited_wrapper_call_is_recognised_as_a_wrapper_invocation` — the same real call through
  the real gateway against a `SQLDbContext`-keyed contract.
- `test_wrapper_declared_on_the_receivers_own_type_is_unchanged` — real STC; **green before and
  after**, which is the point of it.
- `test_receiver_whose_declaring_type_is_unknown_stays_unresolved` — a subclass with no compilation.
- `test_unresolved_declaring_type_names_its_own_reason` — the gateway reason code.
- `test_two_revisions_of_one_shared_base_stay_two_snapshots` — **green before the change as well.**
  Keying three repositories on one receiver type is exactly what could have collapsed two snapshots
  into one, so this is a regression guard, not a new capability. `_proposal_binding_key` keys on
  `(assembly_identity, assembly_revision, behavior_surface_unit)`, and the decompilation cache on
  `(assembly_identity, receiver_type)`, so the Assembly Revision Boundary holds untouched.

`pytest`: **711 passed, 12 failed.** The same 12 tickets 01 and 05 recorded, verified again here by
stashing this work, rebuilding the host, and re-running: identical failures, identical assertions.
None touches wrapper receiver resolution.

### The glossary, settled separately

This ticket's commit does not touch `CONTEXT.md`, for the reason ticket 05 recorded: the file held
an uncommitted block of vocabulary belonging to tickets 04 and 05, and git commits whole files, so
adding an entry here would have swept two other tickets' work in under this ticket's message.

The debt was three tickets deep, so it was paid immediately afterwards in its own commit rather
than deferred to a fourth. That commit carries the already-written block (Program Screen, View
Anchor, Project Connection Scope, Framework Label) together with ADR-0018, ADR-0019 and ADR-0021,
which were still untracked and which `CONTEXT.md` links to — ticket 04's code was already committed
while the ADR it cites was not, so those links were dead. It adds ticket 05's **SDK-style Project**,
**Implicit Globbing** and **Restore Assets**, notes `source_file_count` on **Semantic Binding
Availability**, and adds this ticket's **Declaring Receiver Type** with its four provenance states.

ADR-0020 stays untracked: it belongs to ticket 07, which has not started, and no glossary entry
links to it yet.
