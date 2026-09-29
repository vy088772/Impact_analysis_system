# Describe the Flow-Chain SP Expansion Limit Truthfully

Status: ready-for-agent

## Problem Statement

The descriptions of the forward relationship chain (`/flow_chain`, direction `forward`) say that the chain has no depth limit. The server has a depth limit.

- The spec-rag client function for `/flow_chain` says "沒有深度控制：圖上記錄了幾層就回幾層". A mode 3 agent reads this sentence as a promise that the `stored_procedures` list is always complete. Thus the agent does not look for truncated paths in `diagnostics`.
- The forward chain builds its Execution Paths with the default expansion limit of the execution path builder (`max_call_depth`, value 5). The builder stops at the seventh nested stored procedure and gives an unresolved path with the reason `call_expansion_truncated`. The builder also stops at a stored-procedure call cycle and gives the reason `stored_procedure_call_cycle`.
- The forward chain puts each path that is not `proven` into `diagnostics` and `unresolved_paths`. It does not put that path into `stored_procedures` or `tables`. The `/flow_chain` response copies the forward-chain diagnostics into its top-level `diagnostics`, and the spec-rag client merges them.
- The return-value line of the same docstring lists `{direction, forward_chain, backward_chains, skipped, source_root}`. The function also returns `diagnostics`. Thus a new sentence that points the agent to `diagnostics` would point to a field that the return-value line does not list.
- The spec `.scratch/retire-dead-flow-chain-surface/spec.md` holds the same wrong premise. User story 11 says that the agent must not expect a depth control. User story 16 and the Further Notes paragraph "Why remove `max_sp_depth` and not give it an effect" say that the SQL Execution Graph gives the full nested SP chain for each path. They also say that a depth limit would cut facts that the graph holds. A limit already exists.

The code review of ticket 03 of that spec accepted the docstring sentence. The review compared the sentence with user story 11. It did not compare the sentence with the server code.

## Solution

Correct the spec-rag docstring. The new text says that a caller has no depth parameter. It says that the server stops the expansion at a nesting that is too deep or at a cycle. It also says where the truncated path goes. Add `diagnostics` to the return-value line.

Correct the wrong premise in the `retire-dead-flow-chain-surface` spec. The corrected text records the existing expansion limit and the reason for it.

Add one test that proves the behavior that the new docstring promises. A truncated forward path appears in `diagnostics`. It does not appear in `stored_procedures`.

The result of `/flow_chain` does not change for any request.

## User Stories

1. As a mode 3 agent that reads the spec-rag client description, I want it to say that I have no depth parameter, so that I do not try to set one.
2. As a mode 3 agent that reads the spec-rag client description, I want it to say that the server stops the expansion of a nesting that is too deep, so that I do not treat `stored_procedures` as a complete list.
3. As a mode 3 agent that reads the spec-rag client description, I want it to say that the server stops the expansion at a stored-procedure call cycle, so that I know a cycle also removes a path from `stored_procedures`.
4. As a mode 3 agent that reads the spec-rag client description, I want it to say that a truncated path goes to `diagnostics`, so that I know where to look for it.
5. As a mode 3 agent that reads the spec-rag client description, I want it to name the reasons `call_expansion_truncated` and `stored_procedure_call_cycle`, so that I can match a diagnostic to its cause.
6. As a mode 3 agent that reads the spec-rag client description, I want it to say that a truncated path does not add its tables to `tables`, so that I do not treat the table list as complete.
7. As a mode 3 agent that reads the return-value line, I want it to list `diagnostics`, so that the field that the description points to is in the documented result.
8. As a maintainer of spec-rag, I want the description not to state the numeric depth limit, so that a change of the server value does not make the spec-rag description wrong.
9. As a maintainer of the server, I want a test that proves that a truncated forward path goes to `diagnostics` and not to `stored_procedures`, so that a change to this behavior fails a test before it makes the spec-rag description wrong.
10. As a maintainer running the test suite after this change, I want the existing flow-chain tests in each repository to pass without modification, so that I have direct evidence that the result did not change.
11. As a maintainer running mypy in each repository after this change, I want no new mypy error, so that I know the change touched no signature.
12. As a future engineer who reads the `retire-dead-flow-chain-surface` spec, I want user story 11 to describe the real limit, so that I do not learn a wrong model of the forward chain.
13. As a future engineer who considers a depth limit for the SP chain, I want the `retire-dead-flow-chain-surface` spec to say that the server already has an expansion limit, so that I do not believe that no limit exists.
14. As a future engineer who considers a depth limit for the SP chain, I want the spec to explain the difference between the removed `max_sp_depth` and the existing expansion limit, so that I understand why one was removed and the other stays.
15. As a future engineer who wants to change the expansion limit, I want the spec to say that the change needs its own spec, so that I do not change it as part of a documentation fix.
16. As a reader of ticket 03 of the `retire-dead-flow-chain-surface` spec, I want a comment that points to this spec, so that I know that the docstring sentence from that ticket was corrected later.
17. As a code reviewer of a later docstring change, I want this spec to record that the earlier review compared a sentence only with a user story, so that I compare a behavior claim with the code.

## Implementation Decisions

- **spec-rag client function for `/flow_chain`, forward-direction paragraph.** Keep the sentence about the method call chain, the SP chain from the SQL Execution Graph, and the tables of each SP. Replace the sentence "沒有深度控制：圖上記錄了幾層就回幾層" with this agreed text:

  > 呼叫端沒有深度參數可調。巢狀 SP 呼叫過深或形成循環時，server 停止展開：該路徑不列入 `stored_procedures` 與 `tables`，改列在 `diagnostics`（原因 `call_expansion_truncated` 或 `stored_procedure_call_cycle`）。

- The new text does not state the numeric limit. The limit is a server value in a different repository. The agent needs the location of the truncated path and the reason codes. It does not need the number.
- **spec-rag client function for `/flow_chain`, return-value line.** Add `diagnostics` to the listed fields. Do not change the other listed fields in this spec.
- The spec-rag change is in the `llamaindex-spec-rag` repository, so its commit goes there. The client module uses LF line endings. Keep them.
- **`retire-dead-flow-chain-surface` spec.** Rewrite the original text in place. Do not append a separate correction section. The git history keeps the old text. The rewrite covers these parts:
  - User story 11: the forward chain lists the SP chain that the SQL Execution Graph records, up to the server expansion limit. The description tells the agent where a truncated path goes, so the agent does not expect a depth parameter.
  - User story 16: the future engineer learns why the field was removed and why the existing expansion limit stays.
  - The Further Notes paragraph "Why remove `max_sp_depth` and not give it an effect": `max_sp_depth` was a caller-controlled field with no effect, so the spec removed it. The server has a separate expansion guard, `max_call_depth` with the value 5. The guard reports each truncated path as `call_expansion_truncated`, so no fact disappears without a report. A change to the guard needs its own spec. Keep the sentence that rejects the "no caller uses the field" argument.
  - The Implementation Decisions entry for the spec-rag client: make it agree with the corrected user story 11.
- **Ticket 03 of `retire-dead-flow-chain-surface`.** Append one line to its Comments. The line points to this spec. Do not change its status or its checklist. Its checklist items are all true as written.
- **Tickets for this spec.** The tickets go into this spec directory, under `issues/`. This reverses the earlier grilling decision to put a ticket 04 into the `retire-dead-flow-chain-surface` directory. The user chose this layout during the to-spec step, because the tracker convention puts one feature in one directory.
- The expansion limit and its value do not change. The forward chain continues to use the default of the execution path builder.
- No ADR. This spec corrects descriptions and adds a test. It does not change a decision about behavior.

## Testing Decisions

A good test here proves an external behavior of the forward chain. A test must not check the text of a docstring. A test must not check that a function, a parameter, or a field is absent.

- **New test at the `build_forward_chain` seam.** Give the forward chain a SQL Execution Graph with a nested stored-procedure chain that is deeper than the default expansion limit. Give it one `proven` Database Invocation into the top stored procedure. Assert these results:
  - `stored_procedures` does not contain the truncated path.
  - `diagnostics` contains a path with the reason `call_expansion_truncated`.
  - `tables` does not contain the tables that only the truncated path reaches.
- The test uses the default limit of `build_forward_chain`. It does not pass a limit, because the forward chain passes none. Thus the test fails if the forward chain starts to pass a different limit.
- Prior art: the execution path integration test module has a forward-chain test that gives an unresolved path. That test asserts that `stored_procedures` is empty and that `diagnostics` holds the path. The execution path builder test module has a nested-graph fixture and a truncation test that sets the limit to 0.
- **spec-rag flow-chain tests** (the declared-databases test module) do not change. They must pass without modification.
- **Existing server flow-chain tests** do not change. They must pass without modification.
- mypy in each repository: the error set of the changed files must contain no new error compared to the commit before the change. In spec-rag, run mypy with the project virtual environment.
- The full test suite of each repository must have no new failure compared to the commit before the change.

## Out of Scope

- The value of `max_call_depth`, its removal, and a different value for `/flow_chain`. A change to the expansion limit needs its own spec.
- The accuracy of the forward chain. This spec corrects only descriptions and adds a test.
- The backward direction of `/flow_chain`. Its description does not claim a depth behavior.
- Other fields of the return-value line, other than the addition of `diagnostics`.
- The server-side docstrings of the forward chain. The module docstring of `flow_chain_builder` does not claim that the chain has no limit.
- Other endpoints that use the execution path builder.

## Further Notes

**Why the new description does not state the number.** The description is in spec-rag, and the limit is in the server. A number in spec-rag would become wrong without a report if the server value changed. The reason codes are more stable, and the agent can match them.

**Why the new test is necessary.** The earlier spec added no test for docstring changes. This docstring is different: it promises a behavior that the agent depends on. The execution path builder already has a test for the truncation. No test proves that the forward chain sends a truncated path to `diagnostics`. Without that test, a change to the forward chain can make the spec-rag description wrong without a failure.

**How the wrong premise got through.** The `retire-dead-flow-chain-surface` spec stated that the graph gives the full nested SP chain. Ticket 03 added a sentence that followed from that premise. The code review compared the sentence with user story 11, which holds the same premise. Thus the review accepted it. A behavior claim in a description needs a comparison with the code, not only with the spec.

This spec comes from a grilling session after the code review of ticket 03 of `.scratch/retire-dead-flow-chain-surface/`.
