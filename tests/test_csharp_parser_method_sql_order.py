"""The C# parser keeps the first-match order of the SQL text in a method.

`.scratch/rttalentdb-program-to-sql-chain/` ticket 10: the parser removed
duplicate SQL text through a Python `set`. The order of a set of strings
changes with the string hash seed, so two scans of the same source gave a
different `MethodInfo.sql_queries` order. The first match is the order of
`SQL_PATTERNS`, then the order of the matches in the method body.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from code_analyzer.csharp_parser import CSharpParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE = '''
namespace Orders.Pages
{
    public class OrderPage
    {
        public void LoadData()
        {
            string a = "SELECT Id FROM Orders WHERE Id = 1";
            string b = "DELETE FROM Users WHERE Id = 2";
            string c = "INSERT INTO Logs (Msg) VALUES (@m)";
            string d = "SELECT Id FROM Orders WHERE Id = 1";
            string e = "EXEC dbo.usp_Refresh @Id = 3";
            string f = @"SELECT Name FROM Products WHERE Id = 4";
        }
    }
}
'''

# The verbatim string matches the first pattern, so it comes first.
EXPECTED = [
    "SELECT Name FROM Products WHERE Id = 4",
    "SELECT Id FROM Orders WHERE Id = 1",
    "DELETE FROM Users WHERE Id = 2",
    "INSERT INTO Logs (Msg) VALUES (@m)",
    "EXEC dbo.usp_Refresh @Id = 3",
]

SCAN_SCRIPT = '''
import json, sys
from code_analyzer.csharp_parser import CSharpParser
result = CSharpParser().parse_file(sys.argv[1])
print(json.dumps(result.classes[0].methods[0].sql_queries))
'''


def _write_source(tmp_path: Path) -> Path:
    path = tmp_path / "OrderPage.cs"
    path.write_text(SOURCE, encoding="utf-8")
    return path


def _scan_with_hash_seed(path: Path, seed: str) -> list[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    completed = subprocess.run(
        [sys.executable, "-c", SCAN_SCRIPT, str(path)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_method_sql_queries_keep_the_first_match_order(tmp_path: Path) -> None:
    result = CSharpParser().parse_file(str(_write_source(tmp_path)))

    assert result.classes[0].methods[0].sql_queries == EXPECTED


def test_different_hash_seeds_give_the_same_method_sql_queries(tmp_path: Path) -> None:
    path = _write_source(tmp_path)

    scans = [_scan_with_hash_seed(path, seed) for seed in ("1", "2", "3", "4")]

    assert scans == [EXPECTED] * 4
