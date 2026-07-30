using System.Text.Json;

internal static class Program
{
    private const int ContractVersion = 1;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length == 0)
                return Fail("usage: StaticAnalyzerHost <csharp|sql> --input <file> [--input <file> ...] | --version");

            if (args.Length == 1 && args[0] == "--version")
            {
                Write(new { contract_version = ContractVersion, host_version = "0.1.0", commands = new[] { "csharp", "sql" } });
                return 0;
            }

            if (args[0] == "csharp")
                return AnalyzeCSharp(ReadInputPaths(args));
            if (args[0] == "sql")
            {
                var inputs = ReadInputPaths(args);
                return inputs.Count == 1 ? AnalyzeSql(inputs[0]) : Fail("sql accepts exactly one input file");
            }
            return Fail($"unknown command: {args[0]}");
        }
        catch (Exception exception)
        {
            return Fail(exception.Message);
        }
    }

    private static int AnalyzeCSharp(List<string> inputPaths)
    {
        var analyses = inputPaths.Select(CSharpAnalyzer.Analyze).ToList();
        if (analyses.Count == 1)
        {
            var analysis = analyses[0];
            Write(new { contract_version = ContractVersion, source_id = analysis.SourceId, methods = analysis.Methods });
        }
        else
        {
            Write(new
            {
                contract_version = ContractVersion,
                sources = analyses.Select(analysis => new { source_id = analysis.SourceId, methods = analysis.Methods }),
            });
        }
        return 0;
    }

    private static int AnalyzeSql(string inputPath)
    {
        var analysis = SqlAnalyzer.Analyze(inputPath);
        Write(new { contract_version = ContractVersion, operations = analysis.Operations, parse_errors = analysis.ParseErrors });
        return 0;
    }

    private static int Fail(string message)
    {
        Console.Error.WriteLine(message);
        return 1;
    }

    private static List<string> ReadInputPaths(string[] args)
    {
        if (args.Length < 3 || (args.Length - 1) % 2 != 0)
            throw new ArgumentException("usage: StaticAnalyzerHost <csharp|sql> --input <file> [--input <file> ...]");

        var inputPaths = new List<string>();
        for (var index = 1; index < args.Length; index += 2)
        {
            if (args[index] != "--input")
                throw new ArgumentException("expected --input before each source file");
            if (!File.Exists(args[index + 1]))
                throw new FileNotFoundException("input file not found", args[index + 1]);
            inputPaths.Add(args[index + 1]);
        }
        return inputPaths;
    }

    private static void Write(object value) => Console.WriteLine(JsonSerializer.Serialize(value, JsonOptions));
}