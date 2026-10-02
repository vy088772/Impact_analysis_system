# Keep the Analyze Response Typed Across the HTTP Seam

Status: ready-for-agent

This spec records the accepted decisions Q1 through Q17 from the discussion on 2026-10-02.
It covers Impact_analysis_system and llamaindex-spec-rag.
It creates no implementation tickets.

## Problem Statement

An analyst cannot distinguish an empty analysis section from a broken response format.
The service declares the response envelope, but many nested records remain dictionaries.
The client reads JSON into dictionaries.
Seven client modules read fields by string keys with empty defaults.
A renamed field can therefore appear as an empty section without an error.

The client checks the Evidence Status of some records, but does not check the complete response shape.
The client also reads capacity metadata before that check.
A broken response can therefore affect a recovery request before the client detects the error.

The two repositories use separate Python environments.
They do not import each other's production modules.
The existing agreement-file tests already let both repositories check one set of sample data.

## Solution

The client checks each Analyze Response when it receives the response.
It then keeps the data typed through recovery, merge, and the seven consumer modules.
A valid empty section remains empty.
A missing required field causes a clear Contract Error instead of an empty section.

The service and the client each maintain their own Pydantic models.
Both repositories test those models against one agreement file.
The client keeps the original response separate from its merged result.
The merged result adds coverage information and the Database identity of each path.

A Contract Error stops analysis for the affected System.
Other Systems continue through the existing analysis workflow.
The final result states which System failed and why its evidence is unavailable.
The result does not present that failure as zero impact.

## User Stories

1. As an analyst, I want an empty section to mean no returned evidence, so that I do not confuse emptiness with a format error.
2. As an analyst, I want missing required fields to cause an error, so that a renamed field cannot hide evidence.
3. As an analyst, I want unknown record fields to cause an error, so that the client cannot silently discard new information.
4. As an analyst, I want wrong field types to cause an error, so that automatic conversion cannot hide a format change.
5. As an analyst, I want valid empty lists to pass validation, so that ordinary empty results remain usable.
6. As an analyst, I want valid optional fields to remain optional, so that analysis does not invent missing source material.
7. As an analyst, I want null values accepted only where allowed, so that a null list cannot become an empty list.
8. As an analyst, I want unknown evidence ratings rejected, so that the client cannot guess an evidence rating.
9. As an analyst, I want the client to check each initial response, so that broken data cannot control a recovery request.
10. As an analyst, I want the client to check each recovery response, so that recovery cannot introduce unchecked data.
11. As an analyst, I want a valid empty request to return a typed result, so that all analysis callers receive one interface.
12. As an analyst, I want the full Lookup Database Set preserved, so that the model change does not narrow my analysis.
13. As an analyst, I want an explicit Database target preserved, so that the model change does not change request routing.
14. As an analyst, I want missing SQL caches reported separately, so that a Contract Error cannot look like an unscanned Database.
15. As an analyst, I want a broken response to stop its System analysis, so that partial cache results cannot hide the failure.
16. As an analyst, I want other Systems to continue, so that one broken response does not discard their valid evidence.
17. As an analyst, I want failed Systems listed in the final result, so that I can see the limits of the answer.
18. As an analyst, I want no automatic retry after a Contract Error, so that the client does not repeat an incompatible request.
19. As an analyst, I want unresolved database facts preserved, so that unresolved evidence remains different from a broken response.
20. As an analyst, I want existing merge rules preserved, so that typing does not change which database facts survive.
21. As an analyst, I want distinct paths preserved, so that different branches and Databases remain visible.
22. As an analyst, I want each merged path to retain its Database identity, so that path expansion opens the correct SQL cache.
23. As an analyst, I want capacity notes preserved, so that omitted paths remain visible after a bounded recovery request.
24. As an analyst, I want coverage information preserved, so that the answer states which Databases the client read or skipped.
25. As an analyst, I want valid existing output preserved, so that the model change does not change a supported analysis result.
26. As a maintainer, I want explicit nested models, so that the response contract does not stop at its envelope.
27. As a maintainer, I want typed data in all seven consumers, so that a wrong attribute causes a check failure.
28. As a maintainer, I want separate original and merged models, so that service fields remain separate from client additions.
29. As a maintainer, I want the original response unchanged, so that I can reproduce and compare merge behavior.
30. As a maintainer, I want both models to reuse local nested types, so that the client does not duplicate each record definition.
31. As a maintainer, I want independent repository models, so that neither Python environment imports the other repository.
32. As a maintainer, I want an explicit client Pydantic dependency, so that validation does not depend on an indirect dependency.
33. As a maintainer, I want existing response shapes preserved, so that typing does not require new record tags.
34. As a maintainer, I want dynamic maps distinguished from records, so that legitimate map keys do not cause false errors.
35. As a maintainer, I want one agreement file, so that the repositories cannot maintain different sample copies.
36. As a maintainer, I want a missing agreement file to fail a test, so that a test cannot silently omit the contract check.
37. As a maintainer, I want actual service responses tested, so that matching handwritten models cannot hide a producer defect.
38. As a maintainer, I want invalid sample cases tested, so that the tests prove rejection as well as acceptance.
39. As a maintainer, I want merge and recovery tested through analysis, so that internal changes do not require new test interfaces.
40. As a maintainer, I want errors to identify the affected field, so that I can locate a contract change quickly.
41. As a maintainer, I want errors to exclude input values, so that logs do not disclose source code or credentials.
42. As a maintainer, I want distinct Contract Error messages, so that a format error does not appear as a catalog setup problem.
43. As a maintainer, I want focused type checks, so that dictionary access cannot return unnoticed during migration.
44. As a maintainer, I want the OpenAPI export updated, so that the declared HTTP contract matches the service models.
45. As a maintainer, I want paired deployment, so that a partly migrated contract never reaches production.
46. As a maintainer, I want staged verification, so that I can locate failures before the next migration stage.

## Implementation Decisions

### Terms and Existing Decisions

- An HTTP seam is the point where the service sends an Analyze Response to the client over HTTP.
- An Analyze Response is the service's JSON result for one analysis request.
- A Typed Analyze Result is the client's checked, merged analysis result.
- Pydantic is the Python library that parses data into models and checks the declared fields.
- A Contract Error identifies an Analyze Response that does not satisfy the declared data shape.
- A Database Invocation is an evidence-rated C# data-access call, as the service glossary defines it.
- An Execution Path retains the source and target evidence supplied by the service.
- A Compact Path Candidate is the bounded path summary used before Path Expansion.
- An Evidence Gap states why the run cannot verify a claim.
- Impact Coverage Scope states which Systems and caches the run actually checked.
- OpenAPI is the machine-readable description of the HTTP interface.
- Preserve the client ADR-0007 rules for the Lookup Database Set and the merge of Database Invocations.
- Preserve the service ADR-0007 distinction between invocation Evidence Status and client conclusion Evidence Status.
- Keep the flat invocation rating separate from the wrapper evidence rating and the client conclusion rating.
- Do not use an evidence rating as a record-kind tag.

### Models and Scope

- Use independent Pydantic models in the service and the client (Q10).
- Declare Pydantic as a direct client dependency.
- Do not import production code across repositories.
- Replace the untyped Analyze records with declared nested models.
- Cover the complete known Analyze Response shape, including fields that the current consumers do not read.
- Type every Analyze field that the seven consumer modules read (Q1).
- Migrate context_builder, grounding, agent_tools, path_selection, coverage, analyze_merge, and run_cli.
- Update adjacent callers and annotations where the changed Analyze interface requires it.
- Keep other endpoint response contracts unchanged.
- Keep a separate Analyze Response model and Typed Analyze Result model (Q6).
- Reuse nested types within each repository where the original and merged records have the same contract.
- Declare client additions only in the merged result or its merged nested records.
- Keep the original response unchanged during the merge (Q12).
- Build new merged records when the client adds a Database identity.
- Do not require all models to be deeply immutable.
- Return a typed result for an empty program request without making an HTTP request.

### Validation Rules

- Require every service-emitted envelope field and ProgramAnalysis container in the client response model (Q4).
- Accept an empty container where the service contract permits it.
- Do not replace a missing required field with an empty container.
- Reject unknown fields in structured records, including nested records (Q5).
- Allow dynamic keys only in fields whose contract is an actual key-value map.
- Declare the map value types; do not use a dynamic map to hide structured records.
- Reject wrong primitive types instead of converting them automatically (Q9).
- Reject a numeric string for a number and a boolean for an integer.
- Accept null only where the existing contract permits null.
- Preserve legitimate omitted nested fields, including optional source snippets (Q11).
- Preserve the difference between an omitted field and a null field during service serialization.
- Describe existing record variants with explicit models or bounded unions where necessary.
- Do not add a kind tag or normalize existing record shapes merely to simplify validation.
- Preserve valid JSON encodings for declared enums and lists.
- Use the actual JSON parsing path when testing strict validation.
- Do not promote a known unresolved rating to a Contract Error.
- Reject unknown invocation and wrapper evidence values using their separate declared vocabularies.

### Receive, Recover, and Merge

- Parse each successful Analyze HTTP response once, before the client reads its fields (Q13).
- Apply the same parse entry to initial, explicit-target, unscoped, and recovery Analyze responses.
- Check the response before capacity metadata can cause a recovery request.
- Preserve the existing request budget and bounded Candidate Omission Recovery rules.
- Keep the data typed through recovery and merge.
- Do not convert checked Analyze models back into dictionaries for the seven consumers.
- Use model attributes for structured fields.
- Keep dictionary access only for genuine dynamic maps and unrelated endpoint data.
- Preserve Database Invocation identity, source-span identity, and resolved-view precedence.
- Discard Wrong-cache Non-resolution only under the existing merge rule.
- Preserve distinct same-cache branches and distinct cross-Database paths.
- Preserve the existing path ordering and service-supplied relevance key.
- Preserve definition deduplication, capacity notes, and coverage facts.
- Do not change the meaning of a complete Database identity pair.

### Errors and User-visible Results

- Raise a distinct client Contract Error for malformed JSON or a failed Analyze model check.
- Retain a stable error code and safe structured details in the existing service-error handling interface.
- Stop the affected System analysis when any of its Analyze responses fails validation (Q3).
- Do not publish a partial merge from that System after a Contract Error.
- Keep the missing-SQL-cache response and its normal skip behavior separate from a Contract Error.
- Continue analysis for other Systems through the applicable existing entry points (Q7).
- Record one structured Evidence Gap for the failed System.
- Make that gap visible in the returned result and the applicable final output.
- Keep valid Specification Evidence available without presenting it as successful static analysis.
- Do not describe a Contract Error as zero impact, a catalog setup problem, or a request for clarification.
- Prevent automatic Analyze retries for that System during the same run after a Contract Error.
- Keep normal transient HTTP retry behavior for unrelated transport and server failures.
- Record the System, requested Database identity, endpoint, error code, field path, and validation error category (Q14).
- Exclude field values, response bodies, source snippets, SQL definitions, credentials, and connection strings from error details.
- Give malformed JSON a safe category without echoing the response body.
- Do not add a new evidence rating for a Contract Error.

### Agreement and Delivery

- Keep one agreement file in the service repository (Q8).
- Let client tests read that file through the existing sibling-repository test helper.
- Require both repositories in the documented sibling layout when running agreement tests.
- Fail the test when the agreement file is missing; do not skip it.
- Deploy both repositories as a compatible pair (Q2).
- Do not retain legacy dictionary-return interfaces or old field-name aliases.
- Do not add a response-format version field (Q16).
- Complete the model and agreement-test stage first (Q17).
- Complete the receive, recovery, and merge stage next.
- Complete the consumer and error-reporting stage last.
- Validate each stage before the next stage.
- Deploy only after the complete migration passes its required checks.

## Testing Decisions

- A good test checks observable data, errors, and output rather than private helpers or call order.
- Use the existing HTTP seam as the main contract test surface.
- Send a representative request through the service route with controlled scan and cache inputs.
- Feed the resulting JSON through the client's public Analyze entry point with a controlled HTTP transport.
- Check the Typed Analyze Result or the Contract Error, not the parser's private implementation.
- Use each repository's own environment; no test imports the sibling's production models.
- Use the final analysis entry point for failed-System continuation and visible Evidence Gap tests.
- Use the existing merge entry point for focused merge behavior tests where it already provides the smallest useful interface.
- Do not create separate public test interfaces for each of the seven consumers.
- These surfaces match the accepted Q15 test decisions; the discussion already confirmed the seam choice.
- Prior art: the canonical_object_identity agreement tests independently check one shared sample file.
- Prior art: the declared-Database Analyze tests exercise request routing and multi-cache merge through the client entry point.
- Prior art: the Analyze definition-merge tests check deduplication and retained definitions.
- Prior art: the path-evidence wiring tests check the returned routing identity and rendered evidence.
- Prior art: the OpenAPI export test compares the committed export with the live service schema.
- Reuse these test patterns and helpers rather than adding a second sample synchronization system.

### Agreement Cases

- Include a valid empty response and a response with a program that has empty sections.
- Include nonempty methods, snippets, definitions, diagnostics, view information, and related programs.
- Include Database Invocations, full Execution Paths, Compact Path Candidates, and shared-component contributions.
- Include the supported record variants and legitimately absent nested fields.
- Include every invocation evidence rating and the separate wrapper evidence vocabulary where present.
- Include legal null values and dynamic map entries.
- Check service serialization against the agreement samples, including presence, omission, and JSON field names.
- Check client acceptance against the same samples through its JSON parse path.
- Compare the declared structured field sets with the samples so an unrepresented added field cannot pass unnoticed.
- Check actual producer output as well as samples; two matching handwritten models alone do not prove the service contract.
- Check missing required fields, renamed fields, unknown fields, wrong types, illegal nulls, and unknown evidence values.
- Check malformed JSON without exposing the input body in the error.

### Workflow Cases

- Check an initial Contract Error before any capacity-driven recovery request.
- Check a Contract Error in a recovery response.
- Check both explicit Database routing and declared-Database request expansion.
- Check the existing unscoped request when the declared SQL caches are unavailable.
- Check that a Contract Error after one valid cache response discards that System's partial analysis.
- Check normal missing-cache skips independently from validation errors.
- Check unchanged merge identities, resolved-view precedence, path order, definition union, and Database stamps.
- Check that merging does not change the original response.
- Check bounded recovery and remaining capacity notes.
- Check typed results for no HTTP reads and for valid empty data.
- Check that another System still contributes its valid result after one System fails.
- Check that all failed Systems remain visible when no System provides usable static analysis.
- Check returned gaps and final output across the supported Analyze entry points.
- Check that a repeated automatic Analyze attempt returns the recorded failure without another request.
- Check that error details contain no source text, SQL body, credentials, or input values.
- Check unchanged supported output from the seven consumers.

### Required Gates

- Run the focused contract, recovery, merge, error, and output tests in each repository's own environment.
- Run type checks for the touched service and client modules, including the seven consumers and adjacent changed callers.
- Compare type errors with the pre-change baseline and introduce no new errors in the touched code.
- Update the OpenAPI export after the service model change.
- Run the OpenAPI parity test.
- Run both repositories' applicable offline regression suites.
- Report any pre-existing failure or unavailable environment requirement separately.
- Do not call the migration complete while a new required test or type-check failure remains.

## Out of Scope

- Changes to other endpoint contracts, including Path Evidence, reverse lookup, flow chains, refresh, and object location.
- Changes to Database Invocation rating, path construction, source analysis, or wrapper classification.
- Changes to catalog contents, scan credentials, SQL caches, or cache versions.
- Changes to the Lookup Database Set, path selection rules, or recovery limits.
- New legacy response aliases, dictionary compatibility adapters, or mixed-version deployment support.
- A new response-format version number or new record-kind fields.
- A shared production model package or cross-repository production imports.
- Independent copies of the agreement samples or new sample-copy automation.
- A redesign of all error handling or all Evidence Gap behavior beyond the new Analyze Contract Error.
- Mandatory deep immutability for every model.
- Unrelated cleanup or fixes to pre-existing test failures.
- Implementation tickets, product-code changes, deployment, and commits during this spec-writing task.

## Further Notes

- The accepted test surfaces come from Q15; no new design interview is required for this spec.
- The feature changes the handling of invalid responses, not the meaning of valid analysis evidence.
- The estimated eighty key reads describe the migration size, not a fixed acceptance count.
- Identify the current callers by their behavior because recent changes can move the original line numbers.
- The repository samples must represent the current producer, not stale assumptions about nested dictionary shapes.
- Pair deployment is an operational requirement, not a new wire-format field.
- Strict JSON validation can accept JSON representations of enums and arrays without permitting arbitrary primitive conversion.
- Keep the separate invocation, wrapper, and conclusion evidence concepts intact throughout the migration.
- The client agreement tests need the sibling repository checkout even though runtime code does not.
- A model default must not hide a required HTTP field that the service stopped sending.
- Preserve each edited file's line-ending style during the later implementation.
- This document is the single specification for both repositories.