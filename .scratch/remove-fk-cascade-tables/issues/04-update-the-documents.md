# 04 — Update the documents

**What to build:** A reader of the documents finds no description of a FK
cascade table. A reader does not look for a feature that is not there, and does
not build a client against a field that the service no longer returns.

Update the readme, the user manual, the advanced handbook and the integration
design document.

Three statements in the integration design document are already wrong today.
The document says that the resolver reads the foreign key system view. The
resolver read the SQL cache and inferred from primary key names. The document
says twice that the table list includes the cascade tables. The cascade tables
were a separate field. Delete all three statements with the rest.

The user manual holds two troubleshooting rows about the feature. One row tells
the reader to refresh the cache when the cascade list shrinks. The other row
tells the reader that an empty cascade list is normal. Remove both rows.

The advanced handbook names the resolver module in its module list, and shows a
cascade depth in a sample configuration. Remove both.

Leave the historical records alone. Design decision 9 keeps its original text,
because ADR-0031 supersedes it in place. The S3 milestone table keeps its
original text, because it records what the team built and that record is
correct.

**Blocked by:** 01 — Remove the FK cascade table from the analysis service; 02 —
Remove the FK cascade table from the orchestrator. The documents describe the
real behaviour of both repositories.

**Status:** done

- [x] The readme feature list names no cascade table.
- [x] The user manual holds neither troubleshooting row.
- [x] The advanced handbook module list names no resolver module, and its sample configuration shows no cascade depth.
- [x] The integration design document describes the real response fields, and holds none of the three wrong statements.
- [x] Design decision 9 is unchanged.
- [x] The S3 milestone table is unchanged.

**Note (2026-09-22):** Two of the ticket's named rows/statements turned out to
share their sentence with content that has nothing to do with the cascade
feature, so a whole-row delete would have thrown away correct information:

- README's `service/` module list (`README.md`) also names `fk_resolver.py`,
  same as the advanced handbook's module list. The ticket's checklist only
  calls out the handbook, but ticket 01 already deleted that file, so leaving
  it in the readme's tree would still point a reader at a module that is
  gone. Removed it there too, for the same reason the checklist gives for the
  handbook.
- The user manual's and the advanced handbook's troubleshooting tables each
  hold one row that covers **both** "SP 完整定義" and "FK 連動表" in a single
  sentence (`使用說明書.md`, `進階手冊.md`). The ticket describes this as "a
  row about the feature," but the SP-definition half of the row is accurate
  and unrelated to the cascade removal. Edited both rows to drop only the FK
  clause, keeping the SP-definition troubleshooting advice intact, rather
  than deleting the row outright.
- The user manual's second row (`FK 連動表總是空`) had no such mixture and
  was deleted outright, as the ticket asks.

Traced the "three wrong statements" in `docs/INTEGRATION_DESIGN.md` to: §6.1
("Table 外鍵", claiming the resolver queries `sys.foreign_keys` directly —
deleted the whole subsection and renumbered the former §6.2 to §6.1), and the
`tables[]`/`tables: list[str]` field comments at two places ("含 FK 連動"),
matching "twice." Also removed the `fk_depth`/`related_tables` request and
response fields, the `fk_resolver.py` module-tree line, the `IMPACT_FK_DEPTH`
env sample, and the now-stale FK mentions in the pipeline-coverage table and
architecture diagram, since the checklist requires the document to "describe
the real response fields" throughout, not only in the three flagged
sentences. Left untouched: §9's S3 milestone row and §10's decision 9 (both
still mention FK cascade text, exactly as the ticket requires), and the
handbook's `adr/` index line describing what ADR-0011 did — that line
describes the ADR's own historical scope, not a currently existing feature.

Confirmed via ticket 03's note that ADR-0031 in this spec's and this
ticket's own prose is a stale reference — the real file is
`docs/adr/0032-remove-the-fk-cascade-table-feature.md` (0031 was already
taken by an unrelated ADR). This ticket's checklist never asks me to write
an ADR number into any of the four documents, so the stale number does not
propagate into this change; flagging it here only so a future reader of
this ticket isn't misled by its own "ADR-0031" text.
