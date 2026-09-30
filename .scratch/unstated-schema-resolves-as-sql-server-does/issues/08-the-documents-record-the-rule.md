# 08 — The documents record the rule

**What to build:** A maintainer opens the ADRs and the glossary and finds one rule, its sources, and its evidence. ADR-0037 records how an unstated schema resolves and what it reverses. ADR-0035 lists the three cases that still carry the Unproven Schema mark. `CONTEXT.md` defines Schema Resolution. The canonical-object-identity spec points to this spec where Step 2b is replaced.

See "Documents", "Further Notes", and user stories 42 to 48 in the spec.

**Blocked by:** 02, 03, 04, 05, 06, 07 (each document states behaviour the code must already have).

**Status:** ready-for-agent

- [ ] ADR-0037 states the rule (the `sys` rule, the module's schema, then `dbo`), the Microsoft sources, the operator's confirmation, and the evidence from the seven caches.
- [ ] ADR-0037 states what it reverses: the canonical-object-identity decision never to fill an unstated schema.
- [ ] ADR-0037 states the assumptions: name comparison ignores case; dynamic SQL resolves against the login's default schema; the Microsoft text on a static `EXEC` is ambiguous, and this rule reads it as dynamic SQL only.
- [ ] ADR-0035 gains an amendment that lists the three cases of the mark.
- [ ] `CONTEXT.md` gains a Schema Resolution entry. The Canonical Object Identity and Unproven Schema entries agree with it.
- [ ] The canonical-object-identity spec gains one line at its top that names this spec.
- [ ] Every document fits STE100: one term per concept, description sentences of 25 words or fewer, paragraphs of six sentences or fewer.
- [ ] Each behaviour claim is checked against the code before it is written.
