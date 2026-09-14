using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

/// <summary>
/// Answers whether a syntactic type reference names a type that implements the ADO.NET command
/// contract (`System.Data.IDbCommand`) -- the interface every command type in .NET is required
/// to implement, whichever provider or team wrote it. Returns null when the question cannot be
/// answered at all (no semantic information, or the referenced type does not resolve): a
/// degraded answer is narrower than a full contract check, never a false "does not implement".
/// </summary>
internal interface ICommandContractChecker
{
    bool? ImplementsCommandContract(TypeSyntax type);
}

/// <summary>
/// Ties a contract checker and the pre-existing widened name comparison into the one recognition
/// rule the command-object Command Sources use. The two mechanisms answer one question and
/// produce one outcome -- nothing records which of the two decided, because a Command Source
/// resolved either way is the same fact.
/// </summary>
internal static class CommandContractChecks
{
    /// <summary>The command contract every ADO.NET command type in .NET is required to
    /// implement, whichever provider or team wrote it -- named once so the two contract
    /// checkers can never disagree about which interface this question is about.</summary>
    private const string CommandContractInterfaceName = "IDbCommand";
    private const string CommandContractNamespace = "System.Data";

    internal static bool IsCommandContractType(TypeSyntax type, ICommandContractChecker? checker)
        => checker?.ImplementsCommandContract(type) ?? CSharpAnalyzer.IsSqlCommandType(type);

    internal static bool ImplementsIDbCommand(ITypeSymbol symbol)
        => IsIDbCommandInterface(symbol) || symbol.AllInterfaces.Any(IsIDbCommandInterface);

    private static bool IsIDbCommandInterface(ITypeSymbol symbol)
        => symbol.TypeKind == TypeKind.Interface
            && symbol.Name == CommandContractInterfaceName
            && symbol.ContainingNamespace?.ToDisplayString() == CommandContractNamespace;
}

/// <summary>
/// Answers the contract question against a real project's semantic model -- the local source
/// wrapper path. Unresolvable when the type's own syntax tree lies outside the compilation (no
/// project could be bound around it) or the compiler could not bind the type at all; both report
/// "cannot answer", never "does not implement".
/// </summary>
internal sealed class RoslynCommandContractChecker : ICommandContractChecker
{
    private readonly CSharpCompilation _compilation;

    internal RoslynCommandContractChecker(CSharpCompilation compilation) => _compilation = compilation;

    public bool? ImplementsCommandContract(TypeSyntax type)
    {
        if (!_compilation.ContainsSyntaxTree(type.SyntaxTree))
            return null;
        // GetSymbolInfo, not GetTypeInfo: a TypeSyntax that is the `Type` of an
        // ObjectCreationExpressionSyntax binds as part of the object creation's own overload
        // resolution, so GetTypeInfo on that child node alone reports no type even when the
        // constructor resolved cleanly. GetSymbolInfo resolves the plain name/type reference
        // directly and works uniformly across every context this checker is asked about.
        var symbol = _compilation.GetSemanticModel(type.SyntaxTree).GetSymbolInfo(type).Symbol as ITypeSymbol;
        if (symbol is null || symbol.TypeKind == TypeKind.Error)
            return null;
        return CommandContractChecks.ImplementsIDbCommand(symbol);
    }
}

/// <summary>
/// Answers the contract question for a decompiled wrapper method against a metadata-only
/// compilation built from the decompiled assembly's own resolved references (see
/// <see cref="WrapperAssemblyDecompiler"/>) -- the decompiled external assembly path. A
/// decompiled type is re-parsed from stringified source with no semantic model of its own, so
/// this resolves a syntactic type name against the compilation directly: first as a fully
/// qualified name, then under each namespace the decompiled source imports, mirroring ordinary
/// C# name lookup. A name found under more than one candidate namespace answers "cannot tell"
/// rather than guessing; type binding over a decompiled, per-method re-parsed source is partial
/// by nature, and an unbound name is one more shape of that, never a "does not implement".
/// </summary>
internal sealed class MetadataNameCommandContractChecker : ICommandContractChecker
{
    private readonly Compilation _compilation;
    private readonly IReadOnlyList<string> _importedNamespaces;

    internal MetadataNameCommandContractChecker(Compilation compilation, IReadOnlyList<string> importedNamespaces)
    {
        _compilation = compilation;
        _importedNamespaces = importedNamespaces;
    }

    public bool? ImplementsCommandContract(TypeSyntax type)
    {
        var name = NormalizeName(type);
        if (name is null)
            return null;

        INamedTypeSymbol? resolved = null;
        foreach (var candidate in CandidateFullNames(name))
        {
            var found = _compilation.GetTypeByMetadataName(candidate);
            if (found is null)
                continue;
            if (resolved is not null && !SymbolEqualityComparer.Default.Equals(resolved, found))
                return null; // ambiguous across imported namespaces: cannot tell, not a guess
            resolved = found;
        }
        return resolved is null ? null : CommandContractChecks.ImplementsIDbCommand(resolved);
    }

    // Only a plain (possibly dotted) type name is resolvable this way: a generic instantiation,
    // an array, a nullable-annotated type or `var` names no single metadata type to look up, so
    // this reports "cannot answer" for those rather than stripping them down to a guess.
    private static string? NormalizeName(TypeSyntax type)
    {
        var text = type.ToString().Trim().Replace("global::", "", StringComparison.Ordinal);
        if (text.Length == 0
            || text == "var"
            || text.Contains('<', StringComparison.Ordinal)
            || text.Contains('[', StringComparison.Ordinal)
            || text.EndsWith('?'))
            return null;
        return text;
    }

    private IEnumerable<string> CandidateFullNames(string name)
    {
        if (name.Contains('.', StringComparison.Ordinal))
        {
            yield return name;
            yield break;
        }
        yield return name;
        foreach (var importedNamespace in _importedNamespaces)
            yield return $"{importedNamespace}.{name}";
    }
}
