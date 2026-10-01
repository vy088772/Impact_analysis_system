# 02 — Mode 4 validates its finalization settings before the agent runs

**What to build:** In mode 4, a wrong finalization setting fails before the agent starts, as in the other modes. The person does not wait for a full analysis to see the error. The message names the wrong setting. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Mode 4 builds its finalization options before the agent run.
- [x] A new test at the mode 4 entry shows that a wrong setting raises and the fake agent runner records zero calls. This is the one new seam of the spec.
- [x] The error message names the wrong setting.
- [x] A correct setting gives the same result as before.
- [x] Mode 4 and the other modes validate settings at the same point in the run.

## Note (implementation)

- Branch: `worktree-lookup-02-mode4-validate` in `llamaindex-spec-rag` (worktree `.claude/worktrees/lookup-02-mode4-validate`).
- `impact_orch/orchestrator.py`: `run_impact_analysis_agentic` now builds `finalization_options` at the top, before `AgentRunState` and before the pre-agent lookups. The final `finalize_analysis` call reuses that object. 7 lines changed. The file uses CRLF; keep it.
- New test: `tests/test_mode4_finalization_settings_fail_early.py` (wrong values `"LLM"`, `"on"`, `True` raise `ValueError` naming `answer_synthesis`; fake agent runner and pre-agent lookups record zero calls; `"off"` still reaches the agent once).
- Other tickets that edit `run_impact_analysis_agentic` (for example 01) will touch nearby lines; a merge conflict near the top of the function is possible.
- Baseline in a worktree: 36 tests fail with `FileNotFoundError` (sibling-path tests) and 3 in `tests/test_path_selection.py` fail with or without this change. Not regressions.
