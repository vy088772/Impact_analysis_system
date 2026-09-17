using System.Security.Cryptography;
using System.Xml.Linq;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;
using Microsoft.CodeAnalysis;
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
        PEFile peFile;
        UniversalAssemblyResolver resolver;
        try
        {
            var settings = new DecompilerSettings(ICSharpCode.Decompiler.CSharp.LanguageVersion.Latest);
            peFile = new PEFile(dllPath);
            resolver = new UniversalAssemblyResolver(dllPath, false, null);
            foreach (var searchDirectory in ReferenceAssemblyDirectoriesForAssembly(peFile))
                resolver.AddSearchDirectory(searchDirectory);
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

        var declaredMethods = typeDefinition.Methods
            .Where(method => !method.MetadataToken.IsNil)
            .ToList();

        var (usings, members, translationProblemMethods, translationProblemDefinitions) =
            TryDecompileWholeType(decompiler, typeDefinition, receiverTypeName, declaredMethods, assemblyIdentity)
            ?? DecompilePerMethod(decompiler, declaredMethods, receiverTypeName, assemblyIdentity);

        var classSource = string.Join("\n", usings)
            + $"\nclass {receiverTypeName}\n{{\n"
            + string.Join("\n", members)
            + "\n}\n";
        var syntaxTree = CSharpSyntaxTree.ParseText(classSource);
        var root = (CompilationUnitSyntax)syntaxTree.GetRoot();

        var importedNamespaces = usings
            .Select(ExtractImportedNamespace)
            .Where(importedNamespace => importedNamespace is not null)
            .Select(importedNamespace => importedNamespace!)
            .Distinct(StringComparer.Ordinal)
            .ToList();
        Compilation? contractCompilation;
        try
        {
            contractCompilation = BuildContractCompilation(peFile, resolver);
        }
        catch (Exception)
        {
            // A failure here degrades only the contract question the classifier can ask about
            // this assembly's methods, never the decompile that already succeeded above.
            contractCompilation = null;
        }

        return WrapperDecompilationResult.Succeeded(
            assemblyIdentity,
            root,
            translationProblemMethods,
            translationProblemDefinitions,
            contractCompilation,
            importedNamespaces);
    }

    /// <summary>
    /// Decompiles <paramref name="typeDefinition"/> in one pass instead of one method at a time.
    /// Per-method decompilation (<see cref="DecompilePerMethod"/>, still the fallback below) asks
    /// ICSharpCode.Decompiler to disambiguate a short type name -- e.g. <c>SqlParameter</c> --
    /// using only that one method's own references, and it can resolve the wrong one of two
    /// namespaces the type imports for different reasons (see the
    /// <c>sqldbcontext-contract-resolves-its-real-calls</c> spec: <c>usp_ExecCmdGetDataSetAsync</c>'s
    /// own <c>Microsoft.Data.SqlClient.SqlParameter[]</c> parameter came back per-method as
    /// <c>Microsoft.EntityFrameworkCore.SqlParameter[]?</c> -- a namespace that does not even
    /// declare a <c>SqlParameter</c> type -- while decompiling the whole <c>SQLDbContext</c> type
    /// together, where the decompiler sees every namespace the type's methods actually use, named
    /// it correctly). Returns null when the whole-type decompile or its own re-parse fails, or when
    /// the receiver type's own declaration cannot be found in the result, so the caller falls back
    /// to the always-worked per-method path rather than losing a receiver type this decompiler can
    /// still handle one method at a time.
    /// </summary>
    private static (
        List<string> Usings,
        List<string> Members,
        List<string> TranslationProblemMethods,
        List<WrapperAnalyzer.WrapperDefinition> TranslationProblemDefinitions
    )? TryDecompileWholeType(
        CSharpDecompiler decompiler,
        ICSharpCode.Decompiler.TypeSystem.ITypeDefinition typeDefinition,
        string receiverTypeName,
        IReadOnlyList<ICSharpCode.Decompiler.TypeSystem.IMethod> declaredMethods,
        string assemblyIdentity)
    {
        string wholeTypeSource;
        try
        {
            wholeTypeSource = decompiler.DecompileTypeAsString(typeDefinition.FullTypeName);
        }
        catch (Exception)
        {
            return null;
        }

        CompilationUnitSyntax fileRoot;
        try
        {
            fileRoot = CSharpSyntaxTree.ParseText(wholeTypeSource).GetCompilationUnitRoot();
        }
        catch (Exception)
        {
            return null;
        }

        var typeDeclaration = fileRoot.DescendantNodes()
            .OfType<TypeDeclarationSyntax>()
            .FirstOrDefault(candidate => candidate.Identifier.Text == receiverTypeName);
        if (typeDeclaration is null)
            return null;

        var usings = fileRoot.Usings
            .Select(usingDirective => usingDirective.ToFullString().Trim())
            .Where(usingText => !string.IsNullOrWhiteSpace(usingText))
            .Distinct(StringComparer.Ordinal)
            .ToList();

        // Whole-type decompilation lets ICSharpCode.Decompiler print a parameter's type as a
        // short name (e.g. `SqlParameter[]?`) whenever the whole type's own imports make it
        // locally unambiguous -- correct, from the decompiler's point of view, but this
        // repository's own short-name-to-namespace guess (CSharpAnalyzer.ResolveKnownTypeIdentities,
        // used identically for real, non-decompiled source) has no way to know that guess is
        // right, and a type imported for an unrelated method elsewhere in this same class can
        // out-rank the correct one. Qualifying every parameter type here, directly from this
        // method's own real metadata rather than a name guess, means the text handed to that
        // shared resolver is already unambiguous and needs no guessing at all.
        var methodsByShape = declaredMethods
            .Where(method => !IsConstructorLike(method.Name))
            .ToLookup(method => (method.Name, ParameterShapeSignature(method)));
        var members = typeDeclaration.Members
            .Select(member => member is MethodDeclarationSyntax methodSyntax
                ? QualifyParameterTypes(methodSyntax, UniqueMatchOrNull(
                    methodsByShape[(methodSyntax.Identifier.Text, ParameterShapeSignature(methodSyntax))]))
                : member)
            .Select(member => member.ToFullString())
            .ToList();

        // A declared method absent from the decompiled type's own members is exactly what the
        // per-method path below reports as a translation problem for that one method: this
        // repository always surfaces such a method by name rather than letting it silently vanish.
        // A constructor is never classified as a wrapper method either way (it decompiles as a
        // ConstructorDeclarationSyntax, not a MethodDeclarationSyntax) -- reporting it "missing"
        // here would be a false positive, not a real translation problem.
        var decompiledMethodNames = typeDeclaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Select(method => method.Identifier.Text)
            .ToHashSet(StringComparer.Ordinal);
        var missingMethods = declaredMethods
            .Where(method => !IsConstructorLike(method.Name) && !decompiledMethodNames.Contains(method.Name))
            .ToList();

        return (
            usings,
            members,
            missingMethods.Select(method => method.Name).ToList(),
            missingMethods
                .Select(method => BuildTranslationProblemDefinition(receiverTypeName, method, assemblyIdentity))
                .ToList()
        );
    }

    private static bool IsConstructorLike(string methodName) => methodName.StartsWith('.');

    /// <summary>A same-name, same-arity overload pair that differs only in whether one parameter
    /// is an array (e.g. SQLFunc's own `CreateReader(string, SqlParameter)` next to
    /// `CreateReader(string, SqlParameter[])`) is common enough in this registry's own fixtures
    /// that arity alone is not a safe key for matching a decompiled method back to its real
    /// metadata. Array-ness of each parameter, cheap to read from either side and already exactly
    /// what tells such a pair apart syntactically, extends the key enough to keep them distinct.
    /// </summary>
    private static string ParameterShapeSignature(ICSharpCode.Decompiler.TypeSystem.IMethod method) =>
        string.Concat(method.Parameters.Select(parameter =>
            parameter.Type is ICSharpCode.Decompiler.TypeSystem.ArrayType ? 'A' : 'S'));

    private static string ParameterShapeSignature(MethodDeclarationSyntax methodSyntax) =>
        string.Concat(methodSyntax.ParameterList.Parameters.Select(parameter =>
        {
            var type = parameter.Type;
            if (type is NullableTypeSyntax nullableSyntax)
                type = nullableSyntax.ElementType;
            return type is ArrayTypeSyntax ? 'A' : 'S';
        }));

    /// <summary>Only a uniquely bound method is trusted for the parameter-type substitution
    /// above -- a same-name, same-arity, same-shape overload this repository's own real metadata
    /// still cannot tell apart (an actual arity+shape collision, rather than the array-vs-not
    /// case <see cref="ParameterShapeSignature(ICSharpCode.Decompiler.TypeSystem.IMethod)"/>
    /// already resolves) is left for the pre-existing name-guess resolver rather than risking the
    /// wrong overload's parameter types.</summary>
    private static ICSharpCode.Decompiler.TypeSystem.IMethod? UniqueMatchOrNull(
        IEnumerable<ICSharpCode.Decompiler.TypeSystem.IMethod> candidates)
    {
        using var enumerator = candidates.GetEnumerator();
        if (!enumerator.MoveNext())
            return null;
        var match = enumerator.Current;
        return enumerator.MoveNext() ? null : match;
    }

    /// <summary>Rewrites <paramref name="methodSyntax"/>'s own parameter types to their real,
    /// fully qualified names, read directly from <paramref name="method"/>'s metadata rather than
    /// guessed from the decompiled text -- see <see cref="TryDecompileWholeType"/>'s own remark on
    /// why a name guess is not good enough here. A null <paramref name="method"/> (no unique
    /// metadata match) or a parameter-count mismatch (should not happen once matched by arity, but
    /// never trusted blindly) leaves the syntax exactly as decompiled.</summary>
    private static MethodDeclarationSyntax QualifyParameterTypes(
        MethodDeclarationSyntax methodSyntax,
        ICSharpCode.Decompiler.TypeSystem.IMethod? method)
    {
        if (method is null)
            return methodSyntax;
        var parameters = methodSyntax.ParameterList.Parameters;
        if (parameters.Count != method.Parameters.Count)
            return methodSyntax;

        var updated = methodSyntax;
        for (var index = 0; index < parameters.Count; index++)
        {
            var originalParameter = parameters[index];
            if (originalParameter.Type is null)
                continue;
            var qualifiedType = QualifyElementType(originalParameter.Type, method.Parameters[index].Type);
            if (qualifiedType is null)
                continue;
            // Re-fetch the current parameter node by position: earlier iterations already
            // replaced nodes in `updated`, so `originalParameter` itself may no longer be part
            // of this method's own (updated) tree.
            var currentParameter = updated.ParameterList.Parameters[index];
            updated = updated.ReplaceNode(currentParameter, currentParameter.WithType(qualifiedType));
        }
        return updated;
    }

    /// <summary>Finds the innermost element-type name inside <paramref name="syntax"/> (unwrapping
    /// `?` and `[]`) and, only when it is a short, undotted name (never a predefined type like
    /// `string`), replaces just that name with <paramref name="realType"/>'s own real
    /// namespace-qualified name. A `?` nullable-reference-type annotation directly on the
    /// parameter is dropped, not just left in place: it is compile-time-only and erased at
    /// runtime, so a real call site's own argument carries no equivalent annotation to match
    /// against, and this repository's own parameter-type identity never carries one either (see
    /// the fixture `_TRUE_PARAMETER_TYPES` in test_rating_time_command_mode.py and
    /// test_delegation_alias.py -- deliberately `SqlParameter[]`, never `SqlParameter[]?`). An
    /// array wrapper (`[]`) is kept exactly as decompiled; only the annotation is dropped. Null
    /// means nothing needed replacing (a predefined type, or a shape this does not recognize) and
    /// the original syntax is kept as-is.</summary>
    private static TypeSyntax? QualifyElementType(
        TypeSyntax syntax,
        ICSharpCode.Decompiler.TypeSystem.IType realType)
    {
        var withoutNullableAnnotation = syntax is NullableTypeSyntax nullableSyntax
            ? nullableSyntax.ElementType
            : syntax;

        var elementSyntax = withoutNullableAnnotation;
        while (elementSyntax is ArrayTypeSyntax arraySyntax)
            elementSyntax = arraySyntax.ElementType;
        if (elementSyntax is not IdentifierNameSyntax identifier)
            return null;

        var effectiveRealType = realType is ICSharpCode.Decompiler.TypeSystem.ArrayType arrayType
            ? arrayType.ElementType
            : realType;
        if (string.IsNullOrEmpty(effectiveRealType.Namespace))
            return null;
        var qualifiedName = $"{effectiveRealType.Namespace}.{effectiveRealType.Name}";
        // ParseTypeName's result carries no trivia of its own; the space between the parameter's
        // type and its name is trivia on the ORIGINAL type node (trailing) or the identifier
        // token after it (leading) depending on how the decompiler printed it, so the new syntax
        // must inherit the original's own trivia, not just its text -- dropping it silently
        // concatenates the type and the parameter's name (e.g. `SqlParametervarParameter`).
        var qualifiedSyntax = SyntaxFactory.ParseTypeName(qualifiedName).WithTriviaFrom(identifier);

        // `identifier` is the whole (denullabled) type itself for a non-array parameter --
        // `ReplaceNode` only replaces a proper descendant, never the root it is called on, so
        // that case returns the qualified syntax directly rather than trying to replace a node
        // within itself.
        return ReferenceEquals(identifier, withoutNullableAnnotation)
            ? qualifiedSyntax
            : withoutNullableAnnotation.ReplaceNode(identifier, qualifiedSyntax);
    }

    /// <summary>
    /// Decompiles one method at a time, the way this decompiler always worked before whole-type
    /// decompilation (<see cref="TryDecompileWholeType"/>) became the first attempt. Each
    /// per-method decompile emits its own leading `using` directives, which are not valid syntax
    /// inside a class body: hoist and de-duplicate them above the wrapper class.
    /// </summary>
    private static (
        List<string> Usings,
        List<string> Members,
        List<string> TranslationProblemMethods,
        List<WrapperAnalyzer.WrapperDefinition> TranslationProblemDefinitions
    ) DecompilePerMethod(
        CSharpDecompiler decompiler,
        IReadOnlyList<ICSharpCode.Decompiler.TypeSystem.IMethod> declaredMethods,
        string receiverTypeName,
        string assemblyIdentity)
    {
        var methodSources = new List<string>();
        var translationProblemMethods = new List<string>();
        var translationProblemDefinitions = new List<WrapperAnalyzer.WrapperDefinition>();
        foreach (var method in declaredMethods)
        {
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

        return (usings, members, translationProblemMethods, translationProblemDefinitions);
    }

    // A `using X.Y;` directive names an importable namespace this decompiled source's type
    // references may resolve against; `using static` and an alias (`using X = Y;`) name
    // something else and are left out, degrading rather than guessing.
    private static string? ExtractImportedNamespace(string usingDirectiveText)
    {
        var trimmed = usingDirectiveText.Trim().TrimEnd(';').Trim();
        if (!trimmed.StartsWith("using ", StringComparison.Ordinal))
            return null;
        var rest = trimmed["using ".Length..].Trim();
        if (rest.Length == 0
            || rest.StartsWith("static ", StringComparison.Ordinal)
            || rest.Contains('=', StringComparison.Ordinal))
            return null;
        return rest;
    }

    /// <summary>
    /// A metadata-only compilation carrying the reference assemblies for the framework
    /// <paramref name="peFile"/> targets, the decompiled assembly itself, and every assembly it
    /// directly references (resolved the same way the decompile above resolved them) -- "enough
    /// type information" to answer the command-contract question for a type this assembly's own
    /// methods actually name, whichever provider declared it. No source is compiled into it; it
    /// exists only for <see cref="Microsoft.CodeAnalysis.Compilation.GetTypeByMetadataName"/>
    /// lookups. Null when nothing at all resolved, which degrades every contract question for
    /// this assembly to the name-comparison fallback rather than failing the decompile.
    /// </summary>
    private static Compilation? BuildContractCompilation(PEFile peFile, IAssemblyResolver resolver)
    {
        var referencePaths = new List<string> { peFile.FileName };
        foreach (var directory in ReferenceAssemblyDirectoriesForAssembly(peFile))
        {
            if (!Directory.Exists(directory))
                continue;
            referencePaths.AddRange(Directory.EnumerateFiles(directory, "*.dll"));
        }
        foreach (var reference in peFile.AssemblyReferences)
        {
            try
            {
                var resolved = resolver.Resolve(reference);
                if (!string.IsNullOrEmpty(resolved?.FileName))
                    referencePaths.Add(resolved.FileName);
            }
            catch (Exception)
            {
                // A reference this decompiler could not locate answers no contract question;
                // the fallback name comparison decides for whatever type it would have named.
            }
        }

        var metadataReferences = new List<MetadataReference>();
        foreach (var path in referencePaths.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                metadataReferences.Add(MetadataReference.CreateFromFile(path));
            }
            catch (Exception)
            {
                // Same reasoning: an unreadable reference degrades this one contract question,
                // not the whole decompile.
            }
        }
        return metadataReferences.Count == 0
            ? null
            : CSharpCompilation.Create("CommandContractCheck", references: metadataReferences);
    }

    // Metadata-only membership check for AssemblyReferenceResolver's fallback scan: does this
    // DLL declare a top-level type by this name at all? No method body is decompiled here, so
    // this stays cheap even when a project references several DLLs with valid HintPaths.
    internal static bool AssemblyDefinesType(string dllPath, string typeName)
    {
        try
        {
            var settings = new DecompilerSettings(ICSharpCode.Decompiler.CSharp.LanguageVersion.Latest);
            var peFile = new PEFile(dllPath);
            var resolver = new UniversalAssemblyResolver(dllPath, false, null);
            foreach (var searchDirectory in ReferenceAssemblyDirectoriesForAssembly(peFile))
                resolver.AddSearchDirectory(searchDirectory);
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

    // net6.0/net8.0 reference assemblies, keyed by the exact moniker
    // ICSharpCode.Decompiler.Metadata.DotNetCorePathFinderExtensions.DetectTargetFrameworkId
    // reports for an assembly built against that TargetFramework. Every measured System's
    // SDK-style project targets one of these two; a framework detection does name, but that is
    // named nowhere here (a future net7.0/9.0, .NET Standard, ...), degrades to no search
    // directories rather than guessing at a mismatched set.
    private static readonly IReadOnlyDictionary<string, string> CoreReferenceAssemblyRelativePaths =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            [".NETCoreApp,Version=v6.0"] = Path.Combine("ref", "net6.0"),
            [".NETCoreApp,Version=v8.0"] = Path.Combine("ref", "net8.0"),
        };

    // Exposed for ProjectCompilationResolver (Semantic Binding Availability), which resolves a
    // project's bare framework references (e.g. "System", "System.Data") against the same
    // downloaded .NET Framework reference assembly package this decompiler already uses to
    // resolve mscorlib etc. for a decompiled .NET Framework wrapper DLL. Every old-style
    // (non-SDK) project this analyzer reads targets .NET Framework, so this always names the
    // one Framework set below -- never one of the net6.0/net8.0 sets a modern SDK-style project
    // needs.
    internal static IEnumerable<string> ReferenceAssemblyDirectories()
        => DirectoriesForPackage(
            "microsoft.netframework.referenceassemblies.net48",
            Path.Combine("build", ".NETFramework", "v4.8"));

    // The reference-assembly directories to examine `peFile` against: the reference assemblies
    // for the framework it itself targets, not whichever set happened to be on disk. Detection
    // failing outright, and a `.NETFramework` id of any version -- this analyzer carries one
    // Framework set and always has -- both resolve against that one set: exactly what every
    // wrapper DLL decompiled before this ticket did unconditionally (SQLFunc.dll targets 4.5,
    // SQLObject.dll targets 4.0, both against the 4.8 set). A Framework assembly that detection
    // fails to name is a case this analyzer already resolved before this ticket, so detection
    // failure falls back to that same unconditional set, never to nothing.
    // A `net6.0`/`net8.0` assembly resolves against its own matching set instead. Only a
    // framework detection *does* name, and this analyzer carries no set for (a future net7.0/9.0,
    // .NET Standard, ...), yields no search directories: examining it against a mismatched
    // Framework set could answer a base-type question wrong instead of "cannot answer", so the
    // assembly still decompiles with the affected external types left unresolved, rather than
    // guessing at a set that does not describe it.
    private static IEnumerable<string> ReferenceAssemblyDirectoriesForAssembly(PEFile peFile)
    {
        var targetFrameworkId = peFile.DetectTargetFrameworkId();
        if (string.IsNullOrEmpty(targetFrameworkId)
            || targetFrameworkId.StartsWith(".NETFramework", StringComparison.Ordinal))
            return ReferenceAssemblyDirectories();
        return CoreReferenceAssemblyRelativePaths.TryGetValue(targetFrameworkId, out var relativePath)
            ? DirectoriesForPackage("microsoft.netcore.app.ref", relativePath)
            : Array.Empty<string>();
    }

    private static IEnumerable<string> DirectoriesForPackage(string packageId, string relativePath)
    {
        var nugetRoot = Environment.GetEnvironmentVariable("NUGET_PACKAGES")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".nuget", "packages");
        var packageRoot = Path.Combine(nugetRoot, packageId);
        if (!Directory.Exists(packageRoot))
            yield break;
        foreach (var versionDirectory in Directory.GetDirectories(packageRoot))
        {
            var buildDirectory = Path.Combine(versionDirectory, relativePath);
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
    IReadOnlyList<WrapperAnalyzer.WrapperDefinition> TranslationProblemDefinitions,
    Compilation? ContractCompilation = null,
    IReadOnlyList<string>? ImportedNamespaces = null)
{
    internal static WrapperDecompilationResult Succeeded(
        string assemblyIdentity,
        CompilationUnitSyntax root,
        IReadOnlyList<string> translationProblemMethods,
        IReadOnlyList<WrapperAnalyzer.WrapperDefinition> translationProblemDefinitions,
        Compilation? contractCompilation,
        IReadOnlyList<string> importedNamespaces)
        => new(
            true,
            null,
            null,
            assemblyIdentity,
            root,
            translationProblemMethods,
            translationProblemDefinitions,
            contractCompilation,
            importedNamespaces);

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

        var checker = decompilation.ContractCompilation is null
            ? null
            : new MetadataNameCommandContractChecker(
                decompilation.ContractCompilation,
                decompilation.ImportedNamespaces ?? Array.Empty<string>());
        var definitions = WrapperAnalyzer.GetDefinitions(
            new[] { decompilation.Root! },
            decompilation.AssemblyIdentity!,
            decompilation.AssemblyIdentity!,
            checker);
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
                        : definition.ConnectionIsContextConnection
                            ? "context_connection"
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
