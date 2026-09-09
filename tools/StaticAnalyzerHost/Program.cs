using System.Text.Json;
using System.Text.Json.Nodes;

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
                return Fail("usage: StaticAnalyzerHost <csharp|sql|decompile-wrapper|semantic-binding> --input <file> [--input <file> ...] | --version");

            if (args.Length == 1 && args[0] == "--version")
            {
                Write(new { contract_version = ContractVersion, host_version = "0.1.0", commands = new[] { "csharp", "sql", "decompile-wrapper", "semantic-binding" } });
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
                return DecompileWrapper(
                    decompileInputs.CsprojPath,
                    decompileInputs.ReceiverType,
                    decompileInputs.ForceRerun,
                    decompileInputs.CacheRoot);
            }
            if (args[0] == "semantic-binding")
            {
                var scanRoots = ReadSourceRoots(args);
                return SemanticBinding(scanRoots);
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
        // A semantic model lets a wrapper call bind to one exact method symbol (ticket 06);
        // when the project's references don't resolve to exactly one project across the given
        // scan roots, this stays null and every call falls back to the syntax-only path it
        // already used before this ticket existed.
        var compilation = ProjectCompilationResolver.ResolveCompilationForAnalysis(
            sourceRoots,
            sourceFiles.Select(sourceFile => sourceFile.Root.SyntaxTree).ToList());
        var analyses = inputPaths
            .Select(inputPath => CSharpAnalyzer.Analyze(inputPath, sourceFiles, compilation))
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

    private static int SemanticBinding(List<string> scanRoots)
    {
        var attempts = ProjectCompilationResolver.Resolve(scanRoots);
        Write(new
        {
            contract_version = ContractVersion,
            semantic_binding_availability = attempts.Select(attempt => new
            {
                scan_root = attempt.ScanRoot,
                project_file = attempt.ProjectFile,
                availability = attempt.Availability,
                unresolved_references = attempt.UnresolvedReferences,
                source_file_count = attempt.SourceFileCount,
            }),
        });
        return 0;
    }

    private static int AnalyzeSql(string inputPath)
    {
        var analysis = SqlAnalyzer.Analyze(inputPath);
        Write(new { contract_version = ContractVersion, operations = analysis.Operations, parse_errors = analysis.ParseErrors });
        return 0;
    }

    private static int DecompileWrapper(
        string csprojPath,
        string receiverType,
        bool forceRerun,
        string? cacheRoot)
    {
        var resolution = AssemblyReferenceResolver.Resolve(csprojPath, receiverType);
        var assemblyIdentity = resolution.IsResolved
            ? WrapperAssemblyDecompiler.TryGetAssemblyIdentity(resolution.DllPath!)
            : null;
        var cache = new DecompilationAttemptCache(cacheRoot);
        JsonElement cachedResponse = default;
        var hasCachedResponse = assemblyIdentity is not null
            && cache.TryGet(assemblyIdentity, receiverType, out cachedResponse);
        if (hasCachedResponse && !forceRerun)
        {
            Write(AddCacheMetadata(cachedResponse, "hit", false));
            return 0;
        }

        var classification = DecompiledWrapperClassifier.Classify(csprojPath, receiverType);
        var response = new
        {
            contract_version = ContractVersion,
            status = classification.Status,
            dll_path = classification.DllPath,
            assembly_identity = classification.AssemblyIdentity,
            detail = classification.Detail,
            translation_problem_methods = classification.TranslationProblemMethods,
            wrapper_definitions = classification.WrapperDefinitions,
            contract_proposals = DecompiledWrapperProposalBuilder.Build(classification, receiverType),
        };
        var cacheStatus = assemblyIdentity is null
            ? "not_applicable"
            : hasCachedResponse
                ? "bypassed"
                : "miss";
        var enrichedResponse = AddCacheMetadata(
            response,
            cacheStatus,
            assemblyIdentity is not null);
        if (assemblyIdentity is not null)
            cache.Save(assemblyIdentity, receiverType, enrichedResponse);
        Write(enrichedResponse);
        return 0;
    }

    private static JsonElement AddCacheMetadata(
        object response,
        string cacheStatus,
        bool attempted)
    {
        var node = JsonSerializer.SerializeToNode(response, JsonOptions)!.AsObject();
        var outcome = AttemptOutcome(node);
        return AddCacheMetadata(node, outcome, cacheStatus, attempted);
    }

    private static JsonElement AddCacheMetadata(
        JsonElement response,
        string cacheStatus,
        bool attempted)
    {
        var node = JsonNode.Parse(response.GetRawText())!.AsObject();
        var outcome = node["attempt_outcome"]?.GetValue<string>() ?? "incomplete";
        return AddCacheMetadata(node, outcome, cacheStatus, attempted);
    }

    private static JsonElement AddCacheMetadata(
        JsonObject response,
        string outcome,
        string cacheStatus,
        bool attempted)
    {
        response["attempt_outcome"] = outcome;
        response["cache_status"] = cacheStatus;
        response["decompilation_attempt"] = new JsonObject
        {
            ["attempted"] = attempted,
            ["outcome"] = outcome,
            ["cache_status"] = cacheStatus,
            ["assembly_identity"] = response["assembly_identity"]?.DeepClone(),
        };
        return JsonSerializer.SerializeToElement(response);
    }

    private static string AttemptOutcome(JsonObject response)
    {
        var status = response["status"]?.GetValue<string>();
        if (status is "csproj_not_found"
            or "csproj_unreadable"
            or "receiver_not_referenced"
            or "hint_path_missing"
            or "referenced_dll_missing")
            return "not_attempted";
        if (status != "resolved")
            return "incomplete";
        var definitions = response["wrapper_definitions"]?.AsArray();
        var translationProblems = response["translation_problem_methods"]?.AsArray();
        if (definitions is null || definitions.Count == 0
            || translationProblems is not null && translationProblems.Count > 0)
            return "incomplete";
        if (definitions.Any(definition =>
                !string.IsNullOrWhiteSpace(definition?["unresolved_reason"]?.GetValue<string>())))
            return "incomplete";
        return "complete";
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

    private static List<string> ReadSourceRoots(string[] args)
    {
        if (args.Length < 3 || (args.Length - 1) % 2 != 0)
            throw new ArgumentException("usage: StaticAnalyzerHost semantic-binding --source-root <directory> [--source-root <directory> ...]");

        var scanRoots = new List<string>();
        for (var index = 1; index < args.Length; index += 2)
        {
            if (args[index] != "--source-root")
                throw new ArgumentException("expected --source-root before each scan root");
            scanRoots.Add(args[index + 1]);
        }
        if (scanRoots.Count == 0)
            throw new ArgumentException("semantic-binding requires at least one --source-root");
        return scanRoots;
    }

    private static (string CsprojPath, string ReceiverType, bool ForceRerun, string? CacheRoot) ReadDecompileWrapperInputs(string[] args)
    {
        string? csprojPath = null;
        string? receiverType = null;
        string? cacheRoot = null;
        var forceRerun = false;
        for (var index = 1; index < args.Length;)
        {
            switch (args[index])
            {
                case "--csproj":
                    RequireDecompileWrapperValue(args, index);
                    csprojPath = args[index + 1];
                    index += 2;
                    break;
                case "--receiver-type":
                    RequireDecompileWrapperValue(args, index);
                    receiverType = args[index + 1];
                    index += 2;
                    break;
                case "--cache-root":
                    RequireDecompileWrapperValue(args, index);
                    cacheRoot = args[index + 1];
                    index += 2;
                    break;
                case "--rerun":
                    forceRerun = true;
                    index++;
                    break;
                default:
                    throw new ArgumentException("expected --csproj, --receiver-type, --cache-root, or --rerun");
            }
        }
        if (string.IsNullOrWhiteSpace(csprojPath) || string.IsNullOrWhiteSpace(receiverType))
            throw new ArgumentException("decompile-wrapper requires --csproj and --receiver-type");
        return (csprojPath, receiverType, forceRerun, cacheRoot);
    }

    private static void RequireDecompileWrapperValue(string[] args, int index)
    {
        if (index + 1 >= args.Length)
            throw new ArgumentException("decompile-wrapper option requires a value");
    }

    private static void Write(object value) => Console.WriteLine(JsonSerializer.Serialize(value, JsonOptions));
}