# 16 — Coverage report: two ratios per system, with named reasons

**What to build:** A maintainer can re-run the acceptance measurement at any time and see, per
System, how far the analysis actually got.

Two ratios are reported: Database Invocations that resolve an Executed Procedure
Name, and Database Invocations that resolve a Resolved Connection Source. They
are reported separately, because the measured repositories have opposite
bottlenecks and a combined number would hide which one is stuck.

Every invocation below the line names its reason. A ratio alone cannot tell a
resolution that improved from one that merely became confident, so the reason
codes are what make the number actionable.

**Blocked by:** 07, 09, 13.

**Status:** ready-for-agent

- [ ] The report states, per System, the share of Database Invocations that resolve an Executed Procedure Name.
- [ ] The report states, per System, the share of Database Invocations that resolve a Resolved Connection Source.
- [ ] The two ratios are reported separately and are never combined into one number.
- [ ] Every unresolved invocation is counted under a named reason code.
- [ ] The reason codes distinguish at least: command text arriving across a method boundary, a lookup key outside the connection strings namespace, no project file above the source, and no semantic model for the project.
- [ ] The report runs against a named System and is repeatable without a full re-scan where a current cache exists.
- [ ] The WebForms System is reported by the same command, so its numbers can be compared against the captured baseline.
