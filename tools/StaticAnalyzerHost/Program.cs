using System.Text.Json;

internal static class Program
{
    private const int ContractVersion = 2;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length == 0)
                return Fail("usage: StaticAnalyzerHost <csharp|sql|decompile-wrapper> --input <file> [--input <file> ...] | --version");

            if (args.Length == 1 && args[0] == "--version")
            {
                Write(new { contract_version = ContractVersion, host_version = "0.1.0", commands = new[] { "csharp", "sql", "decompile-wrapper" } });
                return 0;
            }

            if (args[0] == "csharp")
            {
                var csharpInputs = ReadCSharpInputs(args);
                return AnalyzeCSharp(csharpInputs.InputPaths, csharpInputs.SourceRoots);
            }
            if (args[0] == "sql")
            {
                var inputs = ReadInputPaths(args);
                return inputs.Count == 1 ? AnalyzeSql(inputs[0]) : Fail("sql accepts exactly one input file");
            }
            if (args[0] == "decompile-wrapper")
            {
                var decompileInputs = ReadDecompileWrapperInputs(args);
                return DecompileWrapper(decompileInputs.CsprojPath, decompileInputs.ReceiverType);
            }
            return Fail($"unknown command: {args[0]}");
        }
        catch (Exception exception)
        {
            return Fail(exception.Message);
        }
    }

    private static int AnalyzeCSharp(List<string> inputPaths, List<string> sourceRoots)
    {
        var contextPaths = inputPaths
            .Concat(sourceRoots.SelectMany(root => Directory.EnumerateFiles(root, "*.cs", SearchOption.AllDirectories)))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        var sourceFiles = contextPaths.Select(CSharpAnalyzer.ReadSource).ToList();
        var analyses = inputPaths
            .Select(inputPath => CSharpAnalyzer.Analyze(inputPath, sourceFiles))
            .ToList();
        if (analyses.Count == 1)
        {
            var analysis = analyses[0];
            Write(new { contract_version = ContractVersion, source_id = analysis.SourceId, methods = analysis.Methods, db_invocations = analysis.DbInvocations });
        }
        else
        {
            Write(new
            {
                contract_version = ContractVersion,
                sources = analyses.Select(analysis => new { source_id = analysis.SourceId, methods = analysis.Methods, db_invocations = analysis.DbInvocations }),
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

    private static int DecompileWrapper(string csprojPath, string receiverType)
    {
        var classification = DecompiledWrapperClassifier.Classify(csprojPath, receiverType);
        Write(new
        {
            contract_version = ContractVersion,
            status = classification.Status,
            dll_path = classification.DllPath,
            assembly_identity = classification.AssemblyIdentity,
            detail = classification.Detail,
            translation_problem_methods = classification.TranslationProblemMethods,
            wrapper_definitions = classification.WrapperDefinitions,
        });
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

    private static (List<string> InputPaths, List<string> SourceRoots) ReadCSharpInputs(string[] args)
    {
        if (args.Length < 3 || (args.Length - 1) % 2 != 0)
            throw new ArgumentException("usage: StaticAnalyzerHost csharp --input <file> [--input <file> ...] [--source-root <directory> ...]");

        var inputPaths = new List<string>();
        var sourceRoots = new List<string>();
        for (var index = 1; index < args.Length; index += 2)
        {
            var option = args[index];
            var path = args[index + 1];
            if (option == "--input")
            {
                if (!File.Exists(path))
                    throw new FileNotFoundException("input file not found", path);
                inputPaths.Add(path);
            }
            else if (option == "--source-root")
            {
                if (!Directory.Exists(path))
                    throw new DirectoryNotFoundException($"source root not found: {path}");
                sourceRoots.Add(path);
            }
            else
            {
                throw new ArgumentException("expected --input or --source-root before each C# path");
            }
        }

        if (inputPaths.Count == 0)
            throw new ArgumentException("csharp requires at least one --input path");
        return (inputPaths, sourceRoots);
    }

    private static (string CsprojPath, string ReceiverType) ReadDecompileWrapperInputs(string[] args)
    {
        string? csprojPath = null;
        string? receiverType = null;
        for (var index = 1; index < args.Length; index += 2)
        {
            if (index + 1 >= args.Length)
                throw new ArgumentException("usage: StaticAnalyzerHost decompile-wrapper --csproj <file> --receiver-type <name>");
            switch (args[index])
            {
                case "--csproj":
                    csprojPath = args[index + 1];
                    break;
                case "--receiver-type":
                    receiverType = args[index + 1];
                    break;
                default:
                    throw new ArgumentException("expected --csproj or --receiver-type");
            }
        }
        if (string.IsNullOrWhiteSpace(csprojPath) || string.IsNullOrWhiteSpace(receiverType))
            throw new ArgumentException("decompile-wrapper requires --csproj and --receiver-type");
        return (csprojPath, receiverType);
    }

    private static void Write(object value) => Console.WriteLine(JsonSerializer.Serialize(value, JsonOptions));
}