"""Every method declaration shape reaches the C# scan.

`.scratch/rttalentdb-program-to-sql-chain/` ticket 02. The seam is
`CSharpParser.parse_file`. Each declaration below comes from RTTalentDB.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_analyzer.csharp_parser import CSharpParser


def _methods(tmp_path: Path, declaration: str, body: str = "return null;"):
    source = (
        "namespace Rt.Services\n"
        "{\n"
        "    public class Sample\n"
        "    {\n"
        f"        {declaration}\n"
        "        {\n"
        f"            {body}\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    path = tmp_path / "Sample.cs"
    path.write_text(source, encoding="utf-8")
    result = CSharpParser().parse_file(str(path))
    return {m.name: m for c in result.classes for m in c.methods}


@pytest.mark.parametrize(
    "declaration, name",
    [
        (
            "public async Task<(bool Success, string Message)> InvalidateJobType(string jobTypeId)",
            "InvalidateJobType",
        ),
        ("public async Task<JobDuty?> GetJobDutyById(string id)", "GetJobDutyById"),
        ("public static string? NTAccount(this ClaimsPrincipal user)", "NTAccount"),
        (
            "private async Task<List<T>> ExecuteAndMapList<T>(string spName, SqlParameter[]? param = null) where T : new()",
            "ExecuteAndMapList",
        ),
        (
            "public async Task<Dictionary<string, DataTable>> GetPersonnelSkillPivot(PersonnelSkillQryParam QryParam)",
            "GetPersonnelSkillPivot",
        ),
        ("public async Task <IActionResult> ImportData()", "ImportData"),
    ],
)
def test_declaration_shape_is_scanned(tmp_path, declaration, name):
    assert name in _methods(tmp_path, declaration)


def test_tuple_method_keeps_its_calls(tmp_path):
    methods = _methods(
        tmp_path,
        "public async Task<(bool Success, string Message)> InvalidateJobType(string jobTypeId)",
        body="await usp_ExecCmdGetFisrtValueAsync(jobTypeId);",
    )
    assert "usp_ExecCmdGetFisrtValueAsync" in methods["InvalidateJobType"].calls


def test_return_type_text_is_recorded_whole(tmp_path):
    methods = _methods(tmp_path, "public async Task<Dictionary<string, DataTable>> Pivot()")
    assert methods["Pivot"].return_type == "Task<Dictionary<string, DataTable>>"


@pytest.mark.parametrize(
    "statement",
    ["return Foo(1, 2);", "await Bar(x);", "var (a, b) = Baz(x);", "new Qux(1);", "throw Err(x);"],
)
def test_statement_is_not_a_method(tmp_path, statement):
    methods = _methods(tmp_path, "public void Run()", body=statement)
    assert set(methods) == {"Run"}
