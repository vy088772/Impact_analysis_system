# 07 — The write-access type test says why it fails

**What to build:** The test that guards the write-access type list fails today with a bare `StopIteration` when the sibling checkout is on a branch without the list. The test gets an assertion that names the cause: the sibling checkout lacks the list, and the person must switch to a branch that holds commit 5a9aec0. The production code does not change. The work is in the `llamaindex-spec-rag` repository.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The bare `next(...)` is replaced by an assertion with a clear message.
- [ ] The message names commit 5a9aec0 and says to switch the sibling checkout.
- [ ] A test shows that, with the list absent, the failure carries that message.
- [ ] With the list present, the five original checks pass as before.
