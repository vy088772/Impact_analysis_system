# Permit Automatic Decompilation of a Referenced External Wrapper Assembly for Contract Onboarding

**Status:** Accepted
**Date:** 2026-08-13
**Amends:** ADR 0004

## Context

ADR 0004 lets Contract Preflight auto-create a contract from "a verified implementation snapshot tied to an exact external assembly identity," but the companion `unified-database-invocation-classification` spec's Out of Scope explicitly forbids "downloading or decompiling an arbitrary external DLL as an automatic refresh side effect." In practice this left opaque external wrappers with no available caller-visible source — for example `SQLFunc.dll`, referenced by `STC` with no matching contract — permanently `unresolved`, because nothing could ever produce the verified snapshot ADR 0004 requires. Manually decompiling `SQLFunc.dll` confirmed the DLL's method bodies decompile completely and readably, so the gap was procedural, not a matter of missing information.

## Decision

Narrow the "no automatic DLL decompilation" boundary, but only for a DLL traceable to an unresolved wrapper receiver's `.csproj` reference, and only under all of the following conditions (see `.scratch/automatic-external-wrapper-decompilation/spec.md` for full detail):

- The system's `wrapper_contract` selector is unspecified (never overrides a valid explicit selector) and the refresh is full-system, never program-scoped.
- Decompilation runs inside the existing `StaticAnalyzerHost`, and the decompiled syntax tree is classified by the same wrapper-definition/`CommandType`/terminal-sink logic already used for local source, extended to recognize a numeric `CommandType` cast (e.g. `(CommandType)4`) as equivalent to the named member it already recognizes.
- Assembly identity is the SHA-256 hash of the DLL's bytes, not its `AssemblyName`/`Version` string, since legacy internal DLLs are commonly unsigned and unversioned.
- Completeness validation reuses the existing `Implementation Snapshot` rules and additionally rejects any method the decompiler could not faithfully translate.
- A complete result is staged and committed through the existing two-file atomic transaction with no human review step, but its registry entry carries a distinct provenance marker identifying it as decompiler-sourced.
- A failed or incomplete attempt is cached by DLL hash so an unchanged DLL is not re-decompiled on every refresh.

## Consequences

A contract can now become active without a human ever reading the source it was derived from. This is acceptable because the completeness bar and the extended `CommandType` recognition are the same evidentiary bar already trusted for local source, and because the decompiler-sourced provenance marker keeps this class of contract separately auditable. Every other rule from ADR 0004 and the `unified-database-invocation-classification` spec — selector precedence, Evidence Status, SP Catalog validation, connection-source separation — is unchanged.
