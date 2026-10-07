# 08 — Related program expansion uses Bound Call Targets

**What to build:** `/analyze` with an expand depth above 0 lists the files
that a program calls into. For RTTalentDB JobType it gives
`related_programs: []`, because the expansion matches a call by method name
and skips a name with two declarations. An interface and its implementation
give two declarations.

The expansion uses the same Bound Call Target edges as the flow chain. It
keeps its `depth` and `max_programs` limits. The project then has one rule for
"which method does this call reach".

See ADR-0044.

**Blocked by:** 05

**Status:** in-progress (2026-10-07)

- [ ] `/analyze` for RTTalentDB JobType with expand depth 1 lists
      `JobTypeService` and the called method
- [ ] A WebForms static helper call (such as `CommonFunction.AlertMsg`) still
      appears in the expansion
- [ ] Two methods with the same name in two classes do not both appear for
      one call
- [ ] The `depth` and `max_programs` limits behave as before
