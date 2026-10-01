# 07 — The write-access type test says why it fails

**What to build:** The test that guards the write-access type list fails today with a bare `StopIteration` when the sibling checkout is on a branch without the list. The test gets an assertion that names the cause: the sibling checkout lacks the list, and the person must switch to a branch that holds commit 5a9aec0. The production code does not change. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** done (branch worktree-lookup-review-07 in llamaindex-spec-rag)

- [x] The bare `next(...)` is replaced by an assertion with a clear message.
- [x] The message names commit 5a9aec0 and says to switch the sibling checkout.
- [x] A test shows that, with the list absent, the failure carries that message.
- [x] With the list present, the five original checks pass as before.
