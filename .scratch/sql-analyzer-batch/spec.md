# The SQL Analyzer Reads Many Modules in One Run

Status: ready-for-agent

## Problem Statement

An operator runs the SQL refresh for PUR. The refresh takes about 14 minutes.
The SQL Execution Graph stage alone takes 10 minutes and 51 seconds for 1698
modules.

The graph builder starts one analyzer process for each module. One start of the
analyzer costs about 0.33 seconds on the refresh machine. One module costs
about 0.38 seconds in total. Thus, about 87% of the graph stage is process
start time, not analysis.

The C# command of the analyzer already accepts many input files in one run. The
SQL command accepts exactly one input file.

The graph repair tool calls the same graph builder. Thus, a repair of the PUR
graph is slow for the same reason.

## Solution

The SQL command of the analyzer accepts many input files in one run. The graph
builder sends the modules in batches, with the same batch limits as the C#
analysis. The graph that the batches produce is the same as the graph that one
run for each module produces.

After the change, the SQL Execution Graph stage on PUR ends in 2 minutes or
less. The graph repair tool becomes faster by the same amount.

## User Stories

1. As an operator, I want the SQL Execution Graph stage on PUR to end in 2 minutes or less, so that a full PUR refresh does not block my work for 14 minutes.
2. As an operator, I want the graph stage to start the analyzer once for each batch of modules, not once for each module, so that the refresh does not spend most of its time on process starts.
3. As an operator, I want the graph repair tool to become faster by the same change, so that I can rebuild an old graph quickly after a graph version change.
4. As an operator, I want the graph progress bar to move once for each batch, so that I still see that the refresh works.
5. As an operator, I want the progress bar to show the name of the last module in each batch, so that I can see where the refresh is.
6. As an operator, I want a failure in one module to stop the refresh with an error that names that module, so that I can find the bad definition without a search through a whole batch.
7. As an operator, I want a mismatch between the Python side and the analyzer build to stop the refresh with a contract version error, so that I do not debug a strange JSON error.
8. As an analyst, I want the graph from batched analysis to be the same as the graph from one run for each module, so that no lineage answer changes because of a speed change.
9. As an analyst, I want the graph version to stay the same, so that no cache on disk becomes stale because of this change.
10. As an operator, I want the batch limits to be the same as the C# analysis limits, so that one rule controls the command length for the whole analyzer.
11. As an operator, I want the batch to stay under the Windows command length limit, so that a long module name or a long temp directory path does not make the analyzer fail to start.
12. As a maintainer, I want the single-file SQL command to keep its current response shape, so that a caller that sends one file does not change.
13. As a maintainer, I want the many-file SQL response to use one list with one entry for each input in input order, so that the Python side can join each result to its module without a guess.
14. As a maintainer, I want the Python side to reject a batch response whose entry count differs from the input count, so that a lost or extra result never shifts the operations of one module onto another module.
15. As a maintainer, I want the test stub of the analyzer to support the batch method, so that the existing graph tests keep their stub and do not need the real analyzer.
16. As an operator on the refresh machine, I want an acceptance run of the full PUR refresh, so that the speed and the graph are proven on real data.
17. As an analyst, I want the acceptance run to compare the new graph with the graph in the current PUR cache, so that a difference from the batch change is found on real data.
18. As an analyst, I want the comparison to exclude modules whose definition text changed between the two refreshes, so that a change in the Database does not look like a defect of the batch change.

## Implementation Decisions

- **The analyzer SQL command accepts many inputs.** The command takes one or more `--input` options. With one input, the response keeps its current shape: `contract_version`, `operations`, `parse_errors`. With two or more inputs, the response holds `contract_version` and a list `sources`. Each entry of `sources` holds the `operations` and the `parse_errors` of one input, in input order. This follows the shape of the C# many-file response.
- **The analyzer names the failed input.** When the analysis of one input fails, the analyzer stops with an error message that holds the path of that input. The analyzer does not continue with the other inputs, and it does not turn the failure into a parse error. This keeps the current failure behavior: one bad module stops the refresh.
- **The contract version goes from 3 to 4.** The analyzer and the Python host change together. The existing contract check rejects a mismatch with a clear message.
- **The Python host gets a batch method for SQL.** The method takes a list of input paths and an optional progress callback. It returns one result for each input, in input order. It splits the inputs into batches with the existing limits: at most 100 files for each batch, and at most 24,000 characters for each command. It calls the progress callback once after each batch, with the completed count, the total count, and the last input of the batch. It rejects a batch response whose `sources` length differs from the batch length. The single-file SQL method stays.
- **The graph builder uses the batch method.** It writes each module definition to its temporary file first, then sends all files through the batch method. It joins each result to its module by position. It keeps the module order, so node order and relationship order do not change. When the host raises an error that names an input path, the graph builder raises an error that names the module of that path.
- **The graph stage reports progress once for each batch.** The stage key stays `graph`. The item in each progress report is the name of the last module in the batch.
- **The graph version stays 6.** The graph content does not change, so no cache becomes stale.
- **The graph repair tool needs no change of its own.** It calls the graph builder, so it becomes faster with the builder.

## Testing Decisions

- A good test checks external behavior: the graph that the builder returns, the progress reports it makes, the response and errors of the analyzer. A good test does not check how the host builds its command line.
- **Seam 1: `build_sql_execution_graph()`.** This is the main seam.
  - An equivalence test uses the real analyzer and a few SQL modules. It sets the batch limit to 2, so the modules need more than one batch. The graph from the batch path must be equal to a graph built from one `analyze_sql` call for each module.
  - A progress test checks that the `graph` stage reports once for each batch, with the completed count and the last module name.
  - A failure test checks that a host error that names an input path becomes an error that names the module.
  - The existing stub analyzer in the SQL cache fixtures gains the batch method. The existing graph tests keep their stub.
  - Prior art: `test_sql_execution_graph.py` and `test_nested_sql_execution_paths.py`.
- **Seam 2: `StaticAnalyzerHost`.**
  - The contract test checks version 4 and a `sql` command that accepts many `--input` options.
  - A batch test checks that the SQL batch method splits the inputs by the limits and reports each completed batch.
  - A failure test sends a batch in which one input cannot be read. The error message must hold the path of that input.
  - A response check test gives the host a batch response with a wrong entry count. The host must raise an error.
  - Prior art: `test_analyze_csharp_files_reports_completed_batches` and `test_static_analyzer_host_contract` in `test_static_analyzer_host.py`.
- **Acceptance on real data is not an automated test.** See "Further Notes".

## Out of Scope

- A Release build of the analyzer. The analyzer runs as a Debug build. A Release build can be faster, but it changes the build and the deploy path of the C# analysis too. Handle it in a separate spec.
- The `SP 定義` stage (3 minutes and 12 seconds on PUR). This stage reads definitions from SQL Server, not from the analyzer.
- Parallel analyzer processes.
- A progress report from inside the analyzer for each module.
- A change to the failure behavior: one failed module still stops the refresh.
- The cp950 crash of the refresh command. It belongs to `llamaindex-spec-rag`, in `.scratch/cli-output-encoding/`.

## Further Notes

Measurements on the refresh machine on 2026-09-29, before this change:

| Item | Value |
|---|---|
| Full PUR refresh | about 14 minutes |
| `SP 定義` stage | 3:12 |
| SQL Execution Graph stage | 10:51 for 1698 modules |
| One analyzer start (`--version`) | 0.30 to 0.36 seconds |
| One module in the graph stage | about 0.38 seconds |

With 100 modules for each batch, PUR needs about 17 batches. The estimate for
the graph stage is about 1.5 minutes.

Acceptance on real data (the second ticket, done on the refresh machine):

1. Copy the current PUR cache to a backup location before the refresh.
2. Run `refresh_sql_cli PUR` with the new code.
3. Record the time of the SQL Execution Graph stage. It must be 2 minutes or less.
4. Compare the definition text of each module in the new cache with the backup.
5. If every definition is the same, the new graph must be equal to the backup graph: `nodes`, `relationships`, and `parse_errors`.
6. If some definitions changed, list those modules. Remove their nodes and relationships from both graphs, then compare the rest.
7. Record the result in the Notes of the ticket.
