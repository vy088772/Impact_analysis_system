using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

/// <summary>
/// One call inside a method declaration, with its Bound Call Target (ADR-0044): the method that
/// the call reaches. <see cref="TargetNode"/> is the call graph node of that method, the same
/// node its method span carries (<see cref="BoundCallAnalyzer.NodeOf"/>). <see
/// cref="TargetClass"/> and <see cref="TargetMethod"/> are its simple names, for display.
///
/// A call through a corpus interface with no Local Implementer, or with two or more, has no
/// target. Nor does a call whose one Local Implementer has no method that the compiler, or the
/// parameter types, map to the interface method. It keeps its <see cref="UnresolvedReason"/> and
/// every candidate class, so the chain can report the call instead of a guess.
/// </summary>
internal sealed record BoundCall(
    string CallText,
    int StartOffset,
    int EndOffset,
    string TargetClass,
    string TargetMethod,
    string TargetNode,
    string UnresolvedReason,
    IReadOnlyList<string> CandidateClasses);

/// <summary>
/// Records the Bound Call Target of each call in one method. The semantic model binds the call,
/// so a field, a primary constructor parameter, a property, a local variable, an overload and an
/// extension method all resolve the way the compiler resolves them. A method of a corpus
/// interface goes through the Local Implementer rule of <see cref="WrapperAnalyzer"/>.
///
/// Only a method that the scan root declares is a target. A call into a framework or a package
/// method is not an edge of the call graph, so it is not recorded.
/// </summary>
internal static class BoundCallAnalyzer
{
    internal const string NoLocalImplementer = "no_local_implementer";
    internal const string AmbiguousImplementation = "ambiguous_implementation";
    internal const string AmbiguousOverload = "ambiguous_overload";
    internal const string UnmappedImplementation = "unmapped_implementation";

    private static readonly Lazy<IReadOnlyList<MetadataReference>> RuntimeReferences = new(() =>
        (AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string ?? "")
            .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
            .Where(path => Path.GetFileName(path) is var name
                && (name.StartsWith("System.", StringComparison.Ordinal)
                    || name is "System.dll" or "mscorlib.dll" or "netstandard.dll"))
            .Select(path => (MetadataReference)MetadataReference.CreateFromFile(path))
            .ToList());

    // The Local Implementer search walks the whole corpus. One batch asks it once per interface
    // method, not once per call, so the answer is kept for the root list it was found in.
    private static IReadOnlyList<CompilationUnitSyntax>? _implementersRoots;
    private static readonly Dictionary<(string Interface, string Method), IReadOnlyList<WrapperAnalyzer.LocalImplementerCandidate>>
        ImplementersCache = new();

    /// <summary>
    /// A compilation of the scan root's own source, for a scan root whose project compilation
    /// is not available. It holds the runtime's own assemblies only. A call between two methods
    /// of the scan root still binds, because both declarations are in the source; a call into
    /// an unresolved package binds to nothing and is not an edge anyway.
    /// </summary>
    internal static CSharpCompilation SourceOnlyCompilation(IEnumerable<SyntaxTree> syntaxTrees)
        => CSharpCompilation.Create(
            "BoundCallTargets",
            syntaxTrees,
            RuntimeReferences.Value,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

    private static readonly SymbolDisplayFormat NodeTypeFormat = new(
        globalNamespaceStyle: SymbolDisplayGlobalNamespaceStyle.Omitted,
        typeQualificationStyle: SymbolDisplayTypeQualificationStyle.NameAndContainingTypesAndNamespaces,
        genericsOptions: SymbolDisplayGenericsOptions.IncludeTypeParameters);

    private static readonly SymbolDisplayFormat NodeParameterTypeFormat =
        WrapperAnalyzer.BoundParameterTypeFormat.WithGenericsOptions(SymbolDisplayGenericsOptions.IncludeTypeParameters);

    // The type identity of a Local Implementer (`CSharpAnalyzer.GetTypeIdentity`): the namespace
    // and the containing types, with no type parameters.
    private static readonly SymbolDisplayFormat TypeIdentityFormat = new(
        globalNamespaceStyle: SymbolDisplayGlobalNamespaceStyle.Omitted,
        typeQualificationStyle: SymbolDisplayTypeQualificationStyle.NameAndContainingTypesAndNamespaces);

    /// <summary>
    /// The call graph node of one method (ADR-0044): the namespace and the containing types of
    /// its class, its name, its type parameter count, and its parameter types, for example
    /// <c>Shop.Store.Save(int)</c> or <c>Shop.Store.Get`1()</c>. Two overloads, a generic and a
    /// non-generic method, and two classes of one simple name in two namespaces are each two
    /// nodes. This is the one builder of the node: a method span and a Bound Call Target both
    /// take it, so they join with no translation. The parameter types use the display format
    /// of the bound wrapper identity, with their type arguments.
    /// </summary>
    internal static string NodeOf(IMethodSymbol method)
    {
        method = (method.ReducedFrom ?? method).OriginalDefinition;
        var arity = method.Arity > 0 ? $"`{method.Arity}" : "";
        return $"{method.ContainingType.ToDisplayString(NodeTypeFormat)}.{method.Name}{arity}{ParameterList(method)}";
    }

    private static string ParameterList(IMethodSymbol method)
        => "(" + string.Join(",", method.Parameters.Select(parameter =>
            RefKindPrefix(parameter.RefKind) + parameter.Type.ToDisplayString(NodeParameterTypeFormat))) + ")";

    private static string RefKindPrefix(RefKind refKind) => refKind switch
    {
        RefKind.Ref => "ref ",
        RefKind.Out => "out ",
        RefKind.In => "in ",
        RefKind.RefReadOnlyParameter => "ref readonly ",
        _ => "",
    };

    internal static List<BoundCall> Analyze(
        MethodDeclarationSyntax method,
        SemanticModel? semanticModel,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        if (semanticModel is null)
            return new List<BoundCall>();
        return method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .SelectMany(call => Bind(call, semanticModel, sourceRoots))
            .ToList();
    }

    private static IEnumerable<BoundCall> Bind(
        InvocationExpressionSyntax call,
        SemanticModel semanticModel,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        var symbolInfo = semanticModel.GetSymbolInfo(call);
        // A call whose arguments do not bind (a type from an unresolved package) gives candidate
        // symbols instead of one symbol. When every candidate is an overload of one method in one
        // class, the call reaches each candidate overload: the call graph cannot tell which one
        // the compiler would choose, and it does not drop the edge.
        var candidates = (symbolInfo.Symbol is IMethodSymbol bound
                ? new[] { bound }
                : symbolInfo.CandidateSymbols.OfType<IMethodSymbol>())
            .Select(candidate => (candidate.ReducedFrom ?? candidate).OriginalDefinition)
            .Where(IsSourceMethod)
            .Distinct<IMethodSymbol>(SymbolEqualityComparer.Default)
            .ToList();
        if (candidates.Count == 0)
            return Array.Empty<BoundCall>();

        var callText = string.Join(" ", call.Expression.ToString().Split(
            (char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        BoundCall Target(IMethodSymbol target) => new(
            callText, call.SpanStart, call.Span.End, target.ContainingType.Name, target.Name, NodeOf(target), "",
            Array.Empty<string>());
        BoundCall Unresolved(string reason, IEnumerable<string> candidateClasses) => new(
            callText, call.SpanStart, call.Span.End, "", "", "", reason,
            candidateClasses.Distinct(StringComparer.Ordinal).OrderBy(name => name, StringComparer.Ordinal).ToList());

        if (candidates.Any(candidate => candidate.Name != candidates[0].Name
                || !SymbolEqualityComparer.Default.Equals(candidate.ContainingType, candidates[0].ContainingType)))
            return new[] { Unresolved(AmbiguousOverload, candidates.Select(candidate => candidate.ContainingType.Name)) };

        return candidates.Select(method =>
        {
            if (method.ContainingType.TypeKind != TypeKind.Interface)
                return Target(method);

            var implementers = LocalImplementers(method.ContainingType.Name, method.Name, sourceRoots);
            return implementers.Count switch
            {
                1 => ImplementationOf(method, implementers[0], semanticModel.Compilation) is { } implementation
                    ? Target(implementation)
                    : Unresolved(UnmappedImplementation, new[] { implementers[0].ClassName }),
                0 => Unresolved(NoLocalImplementer, Array.Empty<string>()),
                _ => Unresolved(AmbiguousImplementation, implementers.Select(implementer => implementer.ClassName)),
            };
        })
            // Two candidate interface overloads with no single implementer give one diagnostic.
            .DistinctBy(boundCall => (boundCall.TargetNode, boundCall.UnresolvedReason,
                string.Join(",", boundCall.CandidateClasses)))
            .ToList();
    }

    /// <summary>
    /// The method of the Local Implementer that implements <paramref name="interfaceMethod"/>:
    /// the overload the compiler maps to it, in the implementer or in the corpus base class that
    /// declares it. When the compiler cannot map it (a base list that does not bind), the one
    /// method of the declaring class with the same name and parameter types. Null when neither
    /// rule finds one method.
    /// </summary>
    private static IMethodSymbol? ImplementationOf(
        IMethodSymbol interfaceMethod,
        WrapperAnalyzer.LocalImplementerCandidate implementer,
        Compilation compilation)
    {
        var types = compilation.GetSymbolsWithName(implementer.ClassName, SymbolFilter.Type)
            .OfType<INamedTypeSymbol>()
            .Where(type => type.ToDisplayString(TypeIdentityFormat) == implementer.TypeIdentity)
            .ToList();
        var mapped = types
            .SelectMany(type => type.AllInterfaces
                .Where(contract => SymbolEqualityComparer.Default.Equals(
                    contract.OriginalDefinition, interfaceMethod.ContainingType))
                .SelectMany(contract => contract.GetMembers(interfaceMethod.Name).OfType<IMethodSymbol>())
                .Where(member => SymbolEqualityComparer.Default.Equals(member.OriginalDefinition, interfaceMethod))
                .Select(member => type.FindImplementationForInterfaceMember(member)))
            .OfType<IMethodSymbol>()
            .Select(method => method.OriginalDefinition)
            .Distinct<IMethodSymbol>(SymbolEqualityComparer.Default)
            .ToList();
        if (mapped.Count == 1)
            return mapped[0];

        var interfaceParameters = ParameterList(interfaceMethod);
        var declared = types
            .SelectMany(type => SelfAndBaseTypes(type))
            .Where(type => type.Name == implementer.MethodDeclaringClassName)
            .SelectMany(type => type.GetMembers(interfaceMethod.Name).OfType<IMethodSymbol>())
            .Select(method => method.OriginalDefinition)
            .Where(method => ParameterList(method) == interfaceParameters)
            .Distinct<IMethodSymbol>(SymbolEqualityComparer.Default)
            .ToList();
        return declared.Count == 1 ? declared[0] : null;
    }

    private static IEnumerable<INamedTypeSymbol> SelfAndBaseTypes(INamedTypeSymbol type)
    {
        for (var current = type; current is not null; current = current.BaseType)
            yield return current;
    }

    private static bool IsSourceMethod(IMethodSymbol method)
        => method.MethodKind is MethodKind.Ordinary
            && method.ContainingType is not null
            && method.Locations.Any(location => location.IsInSource);

    private static IReadOnlyList<WrapperAnalyzer.LocalImplementerCandidate> LocalImplementers(
        string interfaceName,
        string methodName,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        // One host run hands every input the same tree instances in a new list, so the lists are
        // compared by their elements.
        if (_implementersRoots is null || !_implementersRoots.SequenceEqual(sourceRoots, ReferenceEqualityComparer.Instance))
        {
            ImplementersCache.Clear();
            _implementersRoots = sourceRoots;
        }
        var key = (interfaceName, methodName);
        if (!ImplementersCache.TryGetValue(key, out var implementers))
        {
            implementers = WrapperAnalyzer.ResolveLocalImplementers(interfaceName, methodName, sourceRoots);
            ImplementersCache[key] = implementers;
        }
        return implementers;
    }
}
