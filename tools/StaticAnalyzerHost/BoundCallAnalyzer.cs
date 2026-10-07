using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

/// <summary>
/// One call inside a method declaration, with its Bound Call Target (ADR-0044): the class and
/// the method that the call reaches. The class is a simple name, the same name a method span and
/// a Database Invocation carry, so the call graph joins them without a translation.
///
/// A call through a corpus interface with no Local Implementer, or with two or more, has no
/// target. It keeps its <see cref="UnresolvedReason"/> and, for a tie, every candidate class, so
/// the chain can report the call instead of a guess.
/// </summary>
internal sealed record BoundCall(
    string CallText,
    int StartOffset,
    int EndOffset,
    string TargetClass,
    string TargetMethod,
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

    internal static List<BoundCall> Analyze(
        MethodDeclarationSyntax method,
        SemanticModel? semanticModel,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        if (semanticModel is null)
            return new List<BoundCall>();
        return method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Select(call => Bind(call, semanticModel, sourceRoots))
            .OfType<BoundCall>()
            .ToList();
    }

    private static BoundCall? Bind(
        InvocationExpressionSyntax call,
        SemanticModel semanticModel,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        var symbolInfo = semanticModel.GetSymbolInfo(call);
        // A call whose arguments do not bind (a type from an unresolved package) gives candidate
        // symbols instead of one symbol. They still name the method when every candidate is an
        // overload of one method in one class, because a node of the call graph is that method.
        var candidates = (symbolInfo.Symbol is IMethodSymbol bound
                ? new[] { bound }
                : symbolInfo.CandidateSymbols.OfType<IMethodSymbol>())
            .Select(candidate => (candidate.ReducedFrom ?? candidate).OriginalDefinition)
            .Where(IsSourceMethod)
            .ToList();
        if (candidates.Count == 0)
            return null;

        var callText = string.Join(" ", call.Expression.ToString().Split(
            (char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        BoundCall Target(string targetClass, string targetMethod) => new(
            callText, call.SpanStart, call.Span.End, targetClass, targetMethod, "", Array.Empty<string>());
        BoundCall Unresolved(string reason, IEnumerable<string> candidateClasses) => new(
            callText, call.SpanStart, call.Span.End, "", "", reason,
            candidateClasses.Distinct(StringComparer.Ordinal).OrderBy(name => name, StringComparer.Ordinal).ToList());

        var targets = candidates
            .Select(candidate => (Class: candidate.ContainingType.Name, Method: candidate.Name))
            .Distinct()
            .ToList();
        if (targets.Count > 1)
            return Unresolved(AmbiguousOverload, targets.Select(target => target.Class));

        var method = candidates[0];
        if (method.ContainingType.TypeKind != TypeKind.Interface)
            return Target(method.ContainingType.Name, method.Name);

        var implementers = LocalImplementers(method.ContainingType.Name, method.Name, sourceRoots);
        return implementers.Count switch
        {
            1 => Target(implementers[0].MethodDeclaringClassName, method.Name),
            0 => Unresolved(NoLocalImplementer, Array.Empty<string>()),
            _ => Unresolved(AmbiguousImplementation, implementers.Select(implementer => implementer.ClassName)),
        };
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
