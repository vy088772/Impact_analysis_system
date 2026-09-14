using System.Security.Cryptography;
using System.Xml.Linq;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

// Resolves a wrapper receiver type (e.g. "SQLFunc") to the exact DLL referenced by a
// .csproj's <Reference>/<HintPath> entries. Never scans a directory for arbitrary DLLs: a
// receiver type resolved by neither the <Reference Include> name nor any referenced DLL's
// own metadata stays a review candidate.
internal static class AssemblyReferenceResolver
{
    internal static AssemblyReferenceResolution Resolve(string csprojPath, string receiverTypeName)
    {
        if (!File.Exists(csprojPath))
            return AssemblyReferenceResolution.Unresolved("csproj_not_found");

        XDocument document;
        try
        {
            document = XDocument.Load(csprojPath);
        }
        catch (Exception)
        {
            return AssemblyReferenceResolution.Unresolved("csproj_unreadable");
        }

        var ns = document.Root?.Name.Namespace ?? XNamespace.None;
        var references = document.Descendants(ns + "Reference").ToList();
        var csprojDirectory = Path.GetDirectoryName(Path.GetFullPath(csprojPath)) ?? "";

        // Fast path: the assembly is named after the sole wrapper type it exposes (true for
        // every fixture this repo has decompiled so far, e.g. SQLFunc.dll/SQLFunc).
        var byName = references
            .FirstOrDefault(element => MatchesAssemblyName(element.Attribute("Include")?.Value, receiverTypeName));
        if (byName is not null)
            return ResolveHintPath(byName, ns, csprojDirectory);

        // Slow path: a shared library referenced under a project-wide assembly name that
        // differs from the receiver type it declares (e.g. IQCS's CommonLibrary.dll, which
        // declares SQLDbContext among other types) -- open each referenced DLL's metadata
        // (no method decompile yet) and keep the first one that actually defines the type.
        foreach (var reference in references)
        {
            var dllPath = HintPathTarget(reference, ns, csprojDirectory);
            if (dllPath is not null && WrapperAssemblyDecompiler.AssemblyDefinesType(dllPath, receiverTypeName))
                return AssemblyReferenceResolution.Resolved(dllPath);
        }

        return AssemblyReferenceResolution.Unresolved("receiver_not_referenced");
    }

    private static AssemblyReferenceResolution ResolveHintPath(XElement reference, XNamespace ns, string csprojDirectory)
    {
        var hintPath = reference.Element(ns + "HintPath")?.Value;
        if (string.IsNullOrWhiteSpace(hintPath))
            return AssemblyReferenceResolution.Unresolved("hint_path_missing");

        var dllPath = HintPathTarget(reference, ns, csprojDirectory);
        if (dllPath is null)
            return AssemblyReferenceResolution.Unresolved("referenced_dll_missing");

        return AssemblyReferenceResolution.Resolved(dllPath);
    }

    // Null covers a missing <HintPath> and a HintPath the resolver can't find on disk alike --
    // both callers already distinguish those two cases from their own surrounding context.
    private static string? HintPathTarget(XElement reference, XNamespace ns, string csprojDirectory)
    {
        var hintPath = reference.Element(ns + "HintPath")?.Value;
        if (string.IsNullOrWhiteSpace(hintPath))
            return null;
        var dllPath = Path.GetFullPath(Path.Combine(
            csprojDirectory,
            hintPath.Replace('\\', Path.DirectorySeparatorChar)));
        return File.Exists(dllPath) ? dllPath : null;
    }

    private static bool MatchesAssemblyName(string? include, string receiverTypeName)
    {
        if (string.IsNullOrWhiteSpace(include))
            return false;
        var assemblyName = include.Split(',')[0].Trim();
        return string.Equals(assemblyName, receiverTypeName, StringComparison.Ordinal);
    }
}

internal sealed record AssemblyReferenceResolution(bool IsResolved, string? DllPath, string? UnresolvedReason)
{
    internal static AssemblyReferenceResolution Resolved(string dllPath) => new(true, dllPath, null);

    internal static AssemblyReferenceResolution Unresolved(string reason) => new(false, null, reason);
}

// Decompiles a wrapper receiver type's DLL into a Roslyn syntax tree that the existing
// WrapperAnalyzer/CreateDefinition classification pipeline can consume unchanged. A method the
// decompiler cannot faithfully translate is recorded as a translation problem instead of
// aborting the whole assembly or being silently dropped.
internal static class WrapperAssemblyDecompiler
{
    internal static string? TryGetAssemblyIdentity(string dllPath)
    {
        try
        {
            return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(dllPath))).ToLowerInvariant();
        }
        catch (Exception)
        {
            return null;
        }
    }

    internal static WrapperDecompilationResult Decompile(string dllPath, string receiverTypeName)
    {
        byte[] bytes;
        try
        {
            bytes = File.ReadAllBytes(dllPath);
        }
        catch (Exception exception)
        {
            return WrapperDecompilationResult.Failed("dll_unreadable", exception.Message);
        }
        var assemblyIdentity = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

        CSharpDecompiler decompiler;
        ICSharpCode.Decompiler.TypeSystem.ITypeDefinition? typeDefinition;
        try
        {
            var settings = new DecompilerSettings(ICSharpCode.Decompiler.CSharp.LanguageVersion.Latest);
            var resolver = new UniversalAssemblyResolver(dllPath, false, null);
            foreach (var searchDirectory in ReferenceAssemblyDirectories())
                resolver.AddSearchDirectory(searchDirectory);
            var peFile = new PEFile(dllPath);
            decompiler = new CSharpDecompiler(peFile, resolver, settings);
            typeDefinition = decompiler.TypeSystem.MainModule.TypeDefinitions
                .FirstOrDefault(type => type.DeclaringTypeDefinition is null
                    && string.Equals(type.Name, receiverTypeName, StringComparison.Ordinal));
        }
        catch (Exception exception)
        {
            return WrapperDecompilationResult.Failed("decompile_failed", exception.Message, assemblyIdentity);
        }

        if (typeDefinition is null)
            return WrapperDecompilationResult.Failed("type_not_found", null, assemblyIdentity);

        var methodSources = new List<string>();
        var translationProblemMethods = new List<string>();
        var translationProblemDefinitions = new List<WrapperAnalyzer.WrapperDefinition>();
        foreach (var method in typeDefinition.Methods)
        {
            if (method.MetadataToken.IsNil)
                continue;
            try
            {
                methodSources.Add(decompiler.DecompileAsString(method.MetadataToken));
            }
            catch (Exception)
            {
                // The method's body could not be decompiled at all, so it never becomes a
                // MethodDeclarationSyntax that CreateDefinition could classify; still surface it
                // as a distinct, identifiable fact rather than letting it vanish from the output.
                translationProblemMethods.Add(method.Name);
                translationProblemDefinitions.Add(BuildTranslationProblemDefinition(
                    receiverTypeName,
                    method,
                    assemblyIdentity));
            }
        }

        // Each per-method decompile emits its own leading `using` directives, which are not
        // valid syntax inside a class body: hoist and de-duplicate them above the wrapper class.
        var usings = new List<string>();
        var members = new List<string>();
        foreach (var methodSource in methodSources)
        {
            var snippetRoot = CSharpSyntaxTree.ParseText(methodSource).GetCompilationUnitRoot();
            foreach (var usingDirective in snippetRoot.Usings)
            {
                var usingText = usingDirective.ToFullString().Trim();
                if (!usings.Contains(usingText))
                    usings.Add(usingText);
            }
            members.AddRange(snippetRoot.Members.Select(member => member.ToFullString()));
        }

        var classSource = string.Join("\n", usings)
            + $"\nclass {receiverTypeName}\n{{\n"
            + string.Join("\n", members)
            + "\n}\n";
        var syntaxTree = CSharpSyntaxTree.ParseText(classSource);
        var root = (CompilationUnitSyntax)syntaxTree.GetRoot();

        return WrapperDecompilationResult.Succeeded(
            assemblyIdentity,
            root,
            translationProblemMethods,
            translationProblemDefinitions);
    }

    // Metadata-only membership check for AssemblyReferenceResolver's fallback scan: does this
    // DLL declare a top-level type by this name at all? No method body is decompiled here, so
    // this stays cheap even when a project references several DLLs with valid HintPaths.
    internal static bool AssemblyDefinesType(string dllPath, string typeName)
    {
        try
        {
            var settings = new DecompilerSettings(ICSharpCode.Decompiler.CSharp.LanguageVersion.Latest);
            var resolver = new UniversalAssemblyResolver(dllPath, false, null);
            foreach (var searchDirectory in ReferenceAssemblyDirectories())
                resolver.AddSearchDirectory(searchDirectory);
            var peFile = new PEFile(dllPath);
            var decompiler = new CSharpDecompiler(peFile, resolver, settings);
            return decompiler.TypeSystem.MainModule.TypeDefinitions.Any(type =>
                type.DeclaringTypeDefinition is null
                && string.Equals(type.Name, typeName, StringComparison.Ordinal));
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static WrapperAnalyzer.WrapperDefinition BuildTranslationProblemDefinition(
        string receiverTypeName,
        ICSharpCode.Decompiler.TypeSystem.IMethod method,
        string assemblyIdentity)
    {
        var parameterTypes = method.Parameters.Select(parameter => parameter.Type.Name).ToList();
        var methodIdentity = $"{receiverTypeName}.{method.Name}({string.Join(",", parameterTypes)})";
        return new WrapperAnalyzer.WrapperDefinition(
            receiverTypeName,
            receiverTypeName,
            method.Name,
            parameterTypes,
            parameterTypes,
            parameterTypes.Count,
            -1,
            -1,
            null,
            false,
            false,
            null,
            -1,
            methodIdentity,
            "unresolved",
            null,
            assemblyIdentity,
            assemblyIdentity,
            "decompiler_translation_problem",
            // A decompiled body has no connection of its own and no file to be declared in.
            DeclaresConnectionAsLocal: false,
            SourceFilePath: "");
    }

    // Exposed for ProjectCompilationResolver (Semantic Binding Availability), which resolves a
    // project's bare framework references (e.g. "System", "System.Data") against the same
    // downloaded .NET Framework reference assembly package this decompiler already uses to
    // resolve mscorlib etc. for a decompiled wrapper DLL.
    internal static IEnumerable<string> ReferenceAssemblyDirectories()
    {
        var nugetRoot = Environment.GetEnvironmentVariable("NUGET_PACKAGES")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".nuget", "packages");
        var packageRoot = Path.Combine(nugetRoot, "microsoft.netframework.referenceassemblies.net48");
        if (!Directory.Exists(packageRoot))
            yield break;
        foreach (var versionDirectory in Directory.GetDirectories(packageRoot))
        {
            var buildDirectory = Path.Combine(versionDirectory, "build", ".NETFramework", "v4.8");
            if (Directory.Exists(buildDirectory))
                yield return buildDirectory;
        }
    }
}

internal sealed record WrapperDecompilationResult(
    bool IsSuccess,
    string? Reason,
    string? Detail,
    string? AssemblyIdentity,
    CompilationUnitSyntax? Root,
    IReadOnlyList<string> TranslationProblemMethods,
    IReadOnlyList<WrapperAnalyzer.WrapperDefinition> TranslationProblemDefinitions)
{
    internal static WrapperDecompilationResult Succeeded(
        string assemblyIdentity,
        CompilationUnitSyntax root,
        IReadOnlyList<string> translationProblemMethods,
        IReadOnlyList<WrapperAnalyzer.WrapperDefinition> translationProblemDefinitions)
        => new(true, null, null, assemblyIdentity, root, translationProblemMethods, translationProblemDefinitions);

    internal static WrapperDecompilationResult Failed(string reason, string? detail, string? assemblyIdentity = null)
        => new(
            false,
            reason,
            detail,
            assemblyIdentity,
            null,
            Array.Empty<string>(),
            Array.Empty<WrapperAnalyzer.WrapperDefinition>());
}

// Ties reference resolution and decompilation together, then runs the decompiled syntax tree
// through the existing wrapper-definition classification pipeline (WrapperAnalyzer.GetDefinitions).
internal static class DecompiledWrapperClassifier
{
    internal static DecompiledWrapperClassification Classify(string csprojPath, string receiverTypeName)
    {
        var resolution = AssemblyReferenceResolver.Resolve(csprojPath, receiverTypeName);
        if (!resolution.IsResolved)
            return DecompiledWrapperClassification.Unresolved(resolution.UnresolvedReason!);

        var decompilation = WrapperAssemblyDecompiler.Decompile(resolution.DllPath!, receiverTypeName);
        if (!decompilation.IsSuccess)
            return DecompiledWrapperClassification.DecompileFailed(
                resolution.DllPath!,
                decompilation.Reason!,
                decompilation.Detail,
                decompilation.AssemblyIdentity);

        var definitions = WrapperAnalyzer.GetDefinitions(
            new[] { decompilation.Root! },
            decompilation.AssemblyIdentity!,
            decompilation.AssemblyIdentity!);
        var delegatedMethods = WrapperAnalyzer.GetDelegatedMethods(
            decompilation.Root!,
            definitions);
        var unclassifiedPublicMethods = WrapperAnalyzer.GetUnclassifiedPublicMethods(
            decompilation.Root!,
            definitions,
            delegatedMethods);

        return DecompiledWrapperClassification.Resolved(
            resolution.DllPath!,
            decompilation.AssemblyIdentity!,
            definitions.Concat(decompilation.TranslationProblemDefinitions).ToList(),
            decompilation.TranslationProblemMethods,
            unclassifiedPublicMethods,
            delegatedMethods);
    }
}

internal sealed record DecompiledWrapperClassification(
    string Status,
    string? DllPath,
    string? AssemblyIdentity,
    IReadOnlyList<WrapperAnalyzer.WrapperDefinition> WrapperDefinitions,
    IReadOnlyList<string> TranslationProblemMethods,
    IReadOnlyList<string> UnclassifiedPublicMethods,
    IReadOnlyList<WrapperAnalyzer.DelegatedMethod> DelegatedMethods,
    string? Detail)
{
    internal static DecompiledWrapperClassification Unresolved(string reason)
        => new(reason, null, null, Array.Empty<WrapperAnalyzer.WrapperDefinition>(), Array.Empty<string>(), Array.Empty<string>(), Array.Empty<WrapperAnalyzer.DelegatedMethod>(), null);

    internal static DecompiledWrapperClassification DecompileFailed(
        string dllPath,
        string reason,
        string? detail,
        string? assemblyIdentity)
        => new(reason, dllPath, assemblyIdentity, Array.Empty<WrapperAnalyzer.WrapperDefinition>(), Array.Empty<string>(), Array.Empty<string>(), Array.Empty<WrapperAnalyzer.DelegatedMethod>(), detail);

    internal static DecompiledWrapperClassification Resolved(
        string dllPath,
        string assemblyIdentity,
        IReadOnlyList<WrapperAnalyzer.WrapperDefinition> wrapperDefinitions,
        IReadOnlyList<string> translationProblemMethods,
        IReadOnlyList<string> unclassifiedPublicMethods,
        IReadOnlyList<WrapperAnalyzer.DelegatedMethod> delegatedMethods)
        => new("resolved", dllPath, assemblyIdentity, wrapperDefinitions, translationProblemMethods, unclassifiedPublicMethods, delegatedMethods, null);
}

internal static class DecompiledWrapperProposalBuilder
{
    internal static IReadOnlyList<DecompiledWrapperProposal> Build(
        DecompiledWrapperClassification classification,
        string receiverTypeName)
    {
        if (!string.Equals(classification.Status, "resolved", StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(classification.AssemblyIdentity)
            || string.IsNullOrWhiteSpace(classification.DllPath))
            return Array.Empty<DecompiledWrapperProposal>();

        var behaviorSurfaceUnit = classification.WrapperDefinitions
            .Select(definition => definition.TypeIdentity)
            .FirstOrDefault(typeIdentity => !string.IsNullOrWhiteSpace(typeIdentity))
            ?? receiverTypeName;
        var assemblyIdentity = classification.AssemblyIdentity;
        var relevantDefinitions = classification.WrapperDefinitions
            .Where(definition => !string.IsNullOrWhiteSpace(definition.TerminalSink)
                || !string.IsNullOrWhiteSpace(definition.UnresolvedReason))
            .ToList();
        var helperDefinitions = classification.WrapperDefinitions
            .Where(definition => !relevantDefinitions.Contains(definition))
            .ToList();
        var snapshot = new DecompiledImplementationSnapshot(
            $"{classification.DllPath}@sha256:{assemblyIdentity}",
            assemblyIdentity,
            assemblyIdentity,
            behaviorSurfaceUnit,
            relevantDefinitions
                .Select(ToOperation)
                .ToList(),
            helperDefinitions
                .Select(ToOperation)
                .ToList(),
            classification.TranslationProblemMethods,
            classification.UnclassifiedPublicMethods.Count == 0,
            true,
            helperDefinitions.All(definition => string.IsNullOrWhiteSpace(definition.UnresolvedReason)),
            classification.UnclassifiedPublicMethods);
        return new[]
        {
            new DecompiledWrapperProposal(
                receiverTypeName,
                new[] { behaviorSurfaceUnit },
                snapshot,
                "decompiled_auto"),
        };

        ImplementationSnapshotOperation ToOperation(WrapperAnalyzer.WrapperDefinition definition)
        {
            var semantics = definition.MethodSemantics switch
            {
                "fixed_stored_procedure" => "stored_procedure",
                "fixed_inline_sql" => "inline_sql",
                _ => definition.MethodSemantics,
            };
            var argumentRoles = new Dictionary<string, int>();
            if (definition.CommandTextParameterIndex >= 0)
                argumentRoles["command_text"] = definition.CommandTextParameterIndex;
            if (definition.ModeParameterIndex >= 0)
                argumentRoles["command_type"] = definition.ModeParameterIndex;
            if (definition.ConstructorConnectionParameterIndex >= 0)
                argumentRoles["connection"] = definition.ConstructorConnectionParameterIndex;

            return new ImplementationSnapshotOperation(
                definition.MethodIdentity,
                definition.MethodName,
                definition.Parameters.Count,
                definition.RequiredParameterCount,
                definition.ParameterTypes,
                argumentRoles,
                definition.ConstructorConnectionParameterIndex >= 0
                    ? "constructor_connection"
                    : string.IsNullOrWhiteSpace(definition.ConnectionExpression)
                        ? ""
                        : "wrapper_connection",
                semantics,
                definition.TerminalSink,
                !string.Equals(
                    definition.UnresolvedReason,
                    "decompiler_translation_problem",
                    StringComparison.Ordinal),
                !string.IsNullOrWhiteSpace(definition.UnresolvedReason)
                    || string.Equals(semantics, "unresolved", StringComparison.Ordinal),
                string.Equals(semantics, "unresolved", StringComparison.Ordinal),
                definition.CommandTextLiteral,
                definition.AssemblyRevision,
                definition.UnresolvedReason);
        }
    }
}

internal sealed record DecompiledWrapperProposal(
    string Name,
    IReadOnlyList<string> ReceiverTypes,
    DecompiledImplementationSnapshot ImplementationSnapshot,
    string EvidenceKind);

internal sealed record DecompiledImplementationSnapshot(
    string ArtifactIdentity,
    string AssemblyIdentity,
    string AssemblyRevision,
    string BehaviorSurfaceUnit,
    IReadOnlyList<ImplementationSnapshotOperation> Methods,
    IReadOnlyList<ImplementationSnapshotOperation> HelperOperations,
    IReadOnlyList<string> TranslationProblemMethods,
    bool PublicDatabaseOperationsComplete,
    bool HelperOperationsComplete,
    bool InheritedOperationsComplete,
    IReadOnlyList<string> UnclassifiedPublicMethods);

internal sealed record ImplementationSnapshotOperation(
    string MethodIdentity,
    string MethodName,
    int MethodArity,
    int RequiredParameterCount,
    IReadOnlyList<string> ParameterTypes,
    IReadOnlyDictionary<string, int> ArgumentRoles,
    string ConnectionBehaviorBoundary,
    string EffectiveCommandSemantics,
    string? TerminalSink,
    bool BodyComplete,
    bool Unresolved,
    bool SemanticsUnresolved,
    string? CommandTextLiteral,
    string AssemblyRevision,
    string? UnresolvedReason);
