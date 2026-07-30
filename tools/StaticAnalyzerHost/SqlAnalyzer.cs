using Microsoft.SqlServer.TransactSql.ScriptDom;

internal static class SqlAnalyzer
{
    internal static SqlAnalysis Analyze(string inputPath)
    {
        using var reader = new StringReader(File.ReadAllText(inputPath));
        _ = new TSql160Parser(initialQuotedIdentifiers: true).Parse(reader, out var errors);
        return new SqlAnalysis(
            Array.Empty<object>(),
            errors.Select(error => new SqlParseError(error.Line, error.Message)).ToList());
    }
}

internal sealed record SqlAnalysis(object[] Operations, List<SqlParseError> ParseErrors);
internal sealed record SqlParseError(int Line, string Message);