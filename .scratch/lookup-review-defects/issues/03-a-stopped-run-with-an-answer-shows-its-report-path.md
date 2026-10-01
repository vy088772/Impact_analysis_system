# 03 — A stopped run with an answer shows its report path

**What to build:** When the agent stops with no analyzed code but with a finalized answer, the command line prints the report path. The heading says the answer is finalized. The heading "analyzed no code" appears only when no answer exists. The person always finds the report. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] The empty-scope branch picks its heading from the real state of the result.
- [x] A test of the command line output shows the report path and the finalized heading for an empty scope with an answer.
- [x] A test shows the old heading for an empty scope with no answer.
- [x] The non-empty scope output does not change.

## Comments

**Implementation note (2026-10-01).** Repo `llamaindex-spec-rag`, branch `worktree-lookup-03-report-path`, commit `38811e1`. Not merged to the main line yet (parallel with other lookup tickets).

What changed:
- `impact_orch/run_cli.py`, `_ask_agentic_once`, empty-scope branch (`if not res.impact_results`): with `res.answer` it prints the heading `AI 整合答案（本次沒有可分析的程式，以下為證據缺口說明）`, the answer, and `📄 報告已寫出：<report_path>`. Without an answer it keeps `Agent 回覆（未分析程式碼）`. The non-empty branch is untouched.
- `tests/test_architecture_modules.py`: `import io`, helper `_run_once_capturing_output`, and two tests in `ResumeObjectKindClarificationCliTests`.

Checks: 259 tests pass in `test_architecture_modules.py` + `test_run_cli_input.py`. Full suite shows 39 failures and 3 collection errors that come from the worktree location (sibling `Impact_analysis_system` checkout and fixture files not found), not from this change. mypy on `run_cli.py` keeps the old `res = None` union-attr pattern; this change adds 3 more of the same kind.

Merge note: the worktree branch was reset to `b3069ff` (the `spec_extend_20260701` head), because the default worktree base was an old commit.

**Review fix note (2026-10-01).** Code review found the first version used `if res.answer:` only. The orchestrator "analysis attempted but failed" path also returns an answer with empty `impact_results`, but it never runs finalization, so the finalized heading was wrong there. The fix in `impact_orch/run_cli.py` uses `res.answer and res.ai_prompt` (`finalize_analysis` always sets `ai_prompt`). A new test in `tests/test_architecture_modules.py` covers the unfinalized single-source answer. The finalized-case test fixture now sets `ai_prompt`. Commit `533eaca` on branch `worktree-lookup-03-report-path`. 260 tests pass in the two CLI-related test files.
