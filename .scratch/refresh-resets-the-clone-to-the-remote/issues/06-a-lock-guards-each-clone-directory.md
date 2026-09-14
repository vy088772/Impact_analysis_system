# 06 — Two Systems sharing one clone cannot reset it at once

**What to build:** An operator refreshes two Systems that share one repository, and neither sees a half-updated working tree. The catalog points both `Y-Docs_TTPUR` and `Y-DOCs_TTRDQ` at the same repository, and each scans different subdirectories, so one reset can land underneath the other's read.

The second refresh stops rather than waits. Both callers would fetch the same content, and a caller that waits cannot tell how long it will wait.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] A lock is keyed on the clone directory, not on a System.
- [ ] The lock file sits beside the clone directory, not inside it.
- [ ] The cleaning step cannot delete a lock that a running refresh holds.
- [ ] A refresh that finds the lock held returns a busy result immediately, and changes nothing.
- [ ] A refresh never queues behind a held lock.
- [ ] A lock older than thirty minutes counts as abandoned.
- [ ] The next refresh takes over an abandoned lock.
- [ ] A refresh releases its lock when it fails, as well as when it succeeds.
