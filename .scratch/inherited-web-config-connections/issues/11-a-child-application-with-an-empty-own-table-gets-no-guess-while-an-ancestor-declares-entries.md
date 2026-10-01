# 11 — A child application with an empty own table gets no guess while an ancestor declares entries

**Status:** done (2026-10-01)

**Found in:** the second review of the whole effort (2026-10-01).

**Problem:** Two parts of the spec disagree.

- Story 17 says: "I want a call whose connection stays unresolved to keep its
  current Evidence Status, so that this change does not demote any call."
- The section "Inherited lookup tables" says: "After step 2, the view gives
  the key-as-name guess only when the own table and each inherited table are
  empty."
- The code follows the second rule. A child application whose own
  `Web.config` table is empty had the key-as-name guess before step 2. After
  step 2, it loses the guess when an ancestor declares any entry. A key that
  no layer declares then gets no Database.
- The test `test_the_view_gives_the_guess_only_when_the_own_table_and_each_inherited_table_are_empty`
  pins the current behavior.

**Effect today:** none. On 2026-10-01, each local child application (ATV,
Response, TTRDQ) had an entry in its own table. These applications had no
guess before step 2 either.

**What to decide:**

1. Keep the current rule, and change story 17 to exclude this case.
2. Give the guess when the own table is empty, also when an ancestor declares
   entries.

**Done when:** the spec and the code agree, and one test pins the decision.

## Comments

### 2026-10-01 — decision: option 1

- The maintainer chose option 1. The current rule stays, and story 17
  excludes this case.
- Reason: a key that no layer declares fails at run time in IIS. A guess for
  that key is probably wrong.
- The spec gains an amendment of story 17. The note in "Inherited lookup
  tables" now names this decision.
- The code does not change. The test
  `test_the_view_gives_the_guess_only_when_the_own_table_and_each_inherited_table_are_empty`
  pins the decision.
