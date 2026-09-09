using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

/// <summary>Resolves `CommandType` member names from both named member access and numeric casts (e.g. `(CommandType)4`).</summary>
internal static class CommandTypeCastRecognizer
{
    private static readonly IReadOnlyDictionary<int, string> NumericMembers = new Dictionary<int, string>
    {
        [1] = "Text",
        [4] = "StoredProcedure",
        [512] = "TableDirect",
    };

    internal static bool IsCommandTypeIdentity(ExpressionSyntax expression)
    {
        var normalized = expression.ToString()
            .Trim()
            .Replace("global::", "", StringComparison.Ordinal);
        return normalized is "CommandType" or "System.Data.CommandType";
    }

    /// <summary>Returns the named member (e.g. "StoredProcedure") for a numeric cast to `CommandType`, or null if unmapped.</summary>
    internal static string? ResolveNumericCastMember(ExpressionSyntax expression)
    {
        if (expression is not CastExpressionSyntax cast || !IsCommandTypeIdentity(cast.Type))
            return null;
        if (cast.Expression is not LiteralExpressionSyntax { Token.Value: int numeric })
            return null;
        return NumericMembers.TryGetValue(numeric, out var name) ? name : null;
    }
}

internal static class CSharpAnalyzer
{
    internal static CSharpAnalysis Analyze(string inputPath)
        => Analyze(inputPath, new[] { ReadSource(inputPath) });

    internal static CSharpAnalysis Analyze(
        string inputPath,
        IReadOnlyList<CSharpSource> sourceFiles,
        CSharpCompilation? compilation = null)
    {
        var bytes = File.ReadAllBytes(inputPath);
        var source = File.ReadAllText(inputPath);
        var root = sourceFiles.FirstOrDefault(sourceFile =>
            string.Equals(sourceFile.InputPath, inputPath, StringComparison.OrdinalIgnoreCase))?.Root
            ?? CSharpSyntaxTree.ParseText(source, path: inputPath).GetCompilationUnitRoot();
        var sourceRoots = sourceFiles.Select(sourceFile => sourceFile.Root).ToList();
        var usedWrapperMethodIdentities = WrapperAnalyzer.FindUsedWrapperMethodIdentities(sourceRoots);
        var methods = root.DescendantNodes().OfType<MethodDeclarationSyntax>().Select(method => new MethodSourceSpan(
            method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "",
            method.Identifier.Text,
            method.SpanStart,
            method.Span.End)).ToList();

        var dbInvocations = root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
            .Where(creation => IsSqlCommandType(creation.Type))
            .SelectMany(creation =>
            {
                var methodIdentity = WrapperAnalyzer.GetMethodIdentity(
                    creation.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault(),
                    WrapperAnalyzer.GetKnownTypeIdentities(sourceRoots));
                return DirectSqlClientAnalyzer.Analyze(creation)
                    .Where(_ => methodIdentity is null
                        || !usedWrapperMethodIdentities.Contains(methodIdentity));
            })
            .ToList();
        dbInvocations.AddRange(WrapperAnalyzer.Analyze(root, sourceRoots, compilation));
        dbInvocations.AddRange(AdapterAnalyzer.Analyze(root, sourceRoots));
        dbInvocations.AddRange(root.DescendantNodes()
            .OfType<ObjectCreationExpressionSyntax>()
            .Where(creation => IsDataAdapterType(creation.Type))
            .SelectMany(DirectSqlClientAnalyzer.AnalyzeAdapter));

        return new CSharpAnalysis(
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            methods,
            dbInvocations);
    }

    internal static CSharpSource ReadSource(string inputPath)
    {
        var source = File.ReadAllText(inputPath);
        return new CSharpSource(
            inputPath,
            CSharpSyntaxTree.ParseText(source, path: inputPath).GetCompilationUnitRoot());
    }

    /// <summary>Matches only the exact type name `SqlCommand`, not unrelated types sharing the suffix (e.g. MySqlCommand).</summary>
    internal static bool IsSqlCommandType(TypeSyntax type)
    {
        var typeName = type.ToString();
        var lastSegment = typeName.Split('.').Last();
        return lastSegment == "SqlCommand";
    }

    internal static bool IsDataAdapterType(TypeSyntax type)
        => type.ToString().Split('.').Last() is
            "DbDataAdapter" or
            "SqlDataAdapter" or
            "OleDbDataAdapter" or
            "OdbcDataAdapter" or
            "NpgsqlDataAdapter" or
            "MySqlDataAdapter";

    private static readonly IReadOnlyCollection<string> AdoNetTypeNames = new HashSet<string>(StringComparer.Ordinal)
    {
        "IDbCommand", "DbCommand", "OleDbCommand", "OdbcCommand", "NpgsqlCommand", "MySqlCommand", "OracleCommand",
        "IDbConnection", "DbConnection", "SqlConnection", "SqliteConnection", "NpgsqlConnection", "MySqlConnection",
        "OracleConnection", "OleDbConnection", "OdbcConnection",
        "IDataReader", "DbDataReader", "SqlDataReader", "OleDbDataReader", "OdbcDataReader", "NpgsqlDataReader",
        "MySqlDataReader",
        "IDataParameter", "IDbDataParameter", "DbParameter", "SqlParameter", "OleDbParameter", "OdbcParameter",
        "NpgsqlParameter", "MySqlParameter",
        "IDbTransaction", "DbTransaction", "SqlTransaction", "OleDbTransaction", "OdbcTransaction",
    };

    /// <summary>
    /// Whether a syntactic type reference names an ADO.NET construct: a command, connection, data
    /// adapter, data reader, parameter, or transaction type, from any common ADO.NET provider. Tells
    /// a method that genuinely touches the database apart from a non-database utility method, for a
    /// method whose body yields no Command Source.
    /// </summary>
    internal static bool IsAdoNetType(TypeSyntax type)
    {
        if (IsSqlCommandType(type) || IsDataAdapterType(type))
            return true;
        var name = type.ToString().Trim().TrimEnd('?').Replace("[]", "").Split('.').Last();
        return AdoNetTypeNames.Contains(name);
    }

    /// <summary>The data adapter methods that execute the adapter's own select command.</summary>
    internal static bool IsAdapterFillMethod(string methodName)
        => methodName is "Fill" or "FillAsync";

    /// <summary>Whether an expression denotes a command object: a construction, a parameter,
    /// a local, or a field of command type.</summary>
    internal static bool IsSqlCommandExpression(
        ExpressionSyntax expression,
        MethodDeclarationSyntax method)
    {
        if (expression is ObjectCreationExpressionSyntax creation)
            return IsSqlCommandType(creation.Type);

        var name = expression switch
        {
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            MemberAccessExpressionSyntax member => member.ToString().Trim(),
            _ => "",
        };
        if (string.IsNullOrWhiteSpace(name))
            return false;

        if (method.ParameterList.Parameters.Any(parameter =>
            parameter.Identifier.Text == name
            && parameter.Type is not null
            && IsSqlCommandType(parameter.Type)))
            return true;

        if (method.DescendantNodes().OfType<VariableDeclarationSyntax>().Any(declaration =>
            declaration.Variables.Any(variable => variable.Identifier.Text == name)
            && (IsSqlCommandType(declaration.Type)
                || declaration.Type.ToString() == "var"
                && declaration.Variables.Any(variable =>
                    variable.Identifier.Text == name
                    && variable.Initializer?.Value is ObjectCreationExpressionSyntax creation
                    && IsSqlCommandType(creation.Type)))))
            return true;

        var receiverName = name.StartsWith("this.", StringComparison.Ordinal)
            ? name[5..]
            : name;
        var containingClass = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        return containingClass?.DescendantNodes()
            .OfType<FieldDeclarationSyntax>()
            .Any(field => IsSqlCommandType(field.Declaration.Type)
                && field.Declaration.Variables.Any(variable => variable.Identifier.Text == receiverName)) is true;
    }

    internal static string GetTypeIdentity(TypeDeclarationSyntax? typeDeclaration)
    {
        if (typeDeclaration is null)
            return "";

        var namespaceParts = typeDeclaration.Ancestors()
            .OfType<BaseNamespaceDeclarationSyntax>()
            .Reverse()
            .Select(namespaceDeclaration => namespaceDeclaration.Name.ToString());
        var typeParts = typeDeclaration.AncestorsAndSelf()
            .OfType<TypeDeclarationSyntax>()
            .Reverse()
            .Select(typeDeclaration => typeDeclaration.Identifier.Text);
        return string.Join(".", namespaceParts.Concat(typeParts));
    }

    internal static string QualifyTypeIdentity(string typeName, MethodDeclarationSyntax caller)
    {
        var normalizedTypeName = typeName.Trim().Replace("global::", "", StringComparison.Ordinal);
        if (normalizedTypeName is "bool" or "byte" or "sbyte" or "char" or "decimal"
            or "double" or "float" or "int" or "long" or "nint" or "nuint"
            or "object" or "short" or "string" or "uint" or "ulong" or "ushort"
            or "void")
            return normalizedTypeName;
        return TypeIdentityCandidates(normalizedTypeName, caller).First();
    }

    internal static IReadOnlyList<string> ResolveKnownTypeIdentities(
        string typeName,
        MethodDeclarationSyntax caller,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        var normalizedKnownTypes = knownTypeIdentities
            .Where(type => !string.IsNullOrWhiteSpace(type))
            .Select(type => type.Trim().Replace("global::", "", StringComparison.Ordinal))
            .Distinct(StringComparer.Ordinal)
            .ToList();
        if (normalizedKnownTypes.Count == 0)
            return new[] { QualifyTypeIdentity(typeName, caller) };

        var candidates = TypeIdentityCandidates(typeName, caller);
        var matches = candidates
            .SelectMany(candidate => normalizedKnownTypes
                .Where(type => string.Equals(type, candidate, StringComparison.Ordinal)))
            .Distinct(StringComparer.Ordinal)
            .ToList();
        if (matches.Count > 0)
            return matches;
        return new[] { QualifyTypeIdentity(typeName, caller) };
    }

    private static IReadOnlyList<string> TypeIdentityCandidates(
        string normalizedTypeName,
        MethodDeclarationSyntax caller)
    {
        var namespaceParts = caller.Ancestors()
            .OfType<BaseNamespaceDeclarationSyntax>()
            .Reverse()
            .Select(namespaceDeclaration => namespaceDeclaration.Name.ToString())
            .ToList();
        var candidates = new List<string>();
        if (namespaceParts.Count > 0)
            candidates.Add(string.Join(".", namespaceParts.Append(normalizedTypeName)));

        var root = caller.SyntaxTree.GetRoot();
        var usingDirectives = root.DescendantNodes()
            .OfType<UsingDirectiveSyntax>()
            .ToList();
        if (normalizedTypeName.Contains('.', StringComparison.Ordinal))
        {
            var separator = normalizedTypeName.IndexOf('.', StringComparison.Ordinal);
            var qualifier = normalizedTypeName[..separator];
            var remainder = normalizedTypeName[(separator + 1)..];
            var aliasCandidates = usingDirectives
                .Where(usingDirective => usingDirective.Alias is not null
                    && usingDirective.Name is not null
                    && string.Equals(
                        usingDirective.Alias.Name.ToString(),
                        qualifier,
                        StringComparison.Ordinal))
                .Select(usingDirective => $"{usingDirective.Name}.{remainder}")
                .ToList();
            return aliasCandidates
                .Append(normalizedTypeName)
                .Distinct(StringComparer.Ordinal)
                .ToList();
        }

        foreach (var usingDirective in usingDirectives)
        {
            if (usingDirective.Alias is not null)
            {
                var alias = usingDirective.Alias.Name.ToString();
                if (string.Equals(alias, normalizedTypeName, StringComparison.Ordinal))
                    candidates.Add(usingDirective.Name?.ToString() ?? normalizedTypeName);
                continue;
            }
            if (usingDirective.Name is not null)
                candidates.Add($"{usingDirective.Name}.{normalizedTypeName}");
        }

        candidates.Add(normalizedTypeName);
        return candidates
            .Where(candidate => !string.IsNullOrWhiteSpace(candidate))
            .Distinct(StringComparer.Ordinal)
            .ToList();
    }
}

internal static class SqlTextClassifier
{
    internal static bool LooksLikeInlineSql(string text)
    {
        var normalized = TrimLeadingTrivia(text);
        var match = Regex.Match(normalized, @"^(?<statement>[A-Za-z]+)\b");
        if (!match.Success)
            return false;

        return match.Groups["statement"].Value.ToUpperInvariant() is
            "SELECT" or "INSERT" or "UPDATE" or "DELETE" or "MERGE" or "EXEC" or "EXECUTE";
    }

    private static string TrimLeadingTrivia(string text)
    {
        var index = 0;
        while (index < text.Length)
        {
            while (index < text.Length && char.IsWhiteSpace(text[index]))
                index++;
            if (text.AsSpan(index).StartsWith("--", StringComparison.Ordinal))
            {
                var newline = text.IndexOf('\n', index + 2);
                index = newline < 0 ? text.Length : newline + 1;
                continue;
            }
            if (text.AsSpan(index).StartsWith("/*", StringComparison.Ordinal))
            {
                var commentEnd = text.IndexOf("*/", index + 2, StringComparison.Ordinal);
                index = commentEnd < 0 ? text.Length : commentEnd + 2;
                continue;
            }
            break;
        }
        return text[index..];
    }
}

/// <summary>Finds direct `SqlCommand` invocations by name-based statement matching, without a full Compilation.</summary>
internal static class DirectSqlClientAnalyzer
{
    internal static IReadOnlyList<DirectSqlInvocation> Analyze(ObjectCreationExpressionSyntax creation)
    {
        var method = creation.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault();
        if (method is null)
            return Array.Empty<DirectSqlInvocation>();

        var className = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
        var variableName = ResolveVariableName(creation);
        var arguments = creation.ArgumentList?.Arguments ?? default;
        var textArgument = arguments.Count > 0 ? arguments[0].Expression : null;
        var connectionArgument = arguments.Count > 1 ? arguments[1].Expression : null;

        var connectionExpression = connectionArgument?.ToString().Trim();
        var terminalSinks = ResolveTerminalSinks(method, variableName, creation, creation.SpanStart);

        var relevantStatements = new List<StatementSyntax>();
        var creationStatement = creation.FirstAncestorOrSelf<StatementSyntax>();
        if (creationStatement is not null)
            relevantStatements.Add(creationStatement);

        var propertyAssignments = new List<AssignmentExpressionSyntax>();
        if (variableName is not null)
        {
            propertyAssignments = method.DescendantNodes().OfType<AssignmentExpressionSyntax>()
                .Where(assignment => assignment.Left is MemberAccessExpressionSyntax member
                    && member.Expression.ToString() == variableName)
                .ToList();

            foreach (var assignment in propertyAssignments)
            {
                var propertyName = ((MemberAccessExpressionSyntax)assignment.Left).Name.Identifier.Text;
                var statement = assignment.FirstAncestorOrSelf<StatementSyntax>();

                if (propertyName is "CommandType" or "CommandText" or "Connection")
                {
                    if (statement is not null)
                        relevantStatements.Add(statement);
                }
                if (propertyName == "Connection")
                    connectionExpression = assignment.Right.ToString().Trim();
            }
        }
        foreach (var terminalSink in terminalSinks)
        {
            var sinkStatement = terminalSink.FirstAncestorOrSelf<StatementSyntax>();
            if (sinkStatement is not null)
                relevantStatements.Add(sinkStatement);
        }

        var commandTextAssignments = propertyAssignments
            .Where(assignment => ((MemberAccessExpressionSyntax)assignment.Left).Name.Identifier.Text == "CommandText")
            .Where(assignment => assignment.SpanStart > creation.SpanStart)
            .ToList();
        var commandTextSources = commandTextAssignments
            .Select(assignment => (
                Assignment: (SyntaxNode)assignment,
                Value: assignment.Right))
            .ToList();
        if (textArgument is not null)
        {
            commandTextSources.Add((
                Assignment: creation,
                Value: textArgument));
        }

        var commandTextCandidates = commandTextSources.Count > 0
            ? SyntaxBranchAnalyzer.RemoveShadowedAssignments(commandTextSources)
                .SelectMany(item => ReadCommandTextCandidates(
                    item.Value,
                    method,
                    item.Assignment,
                    item.Assignment.SpanStart))
                .ToList()
            : ReadCommandTextCandidates(textArgument, method, creation, creation.SpanStart).ToList();

        var commandTypeAssignments = propertyAssignments
            .Where(assignment => ((MemberAccessExpressionSyntax)assignment.Left).Name.Identifier.Text == "CommandType")
            .ToList();
        var effectiveCommandTypeAssignments = SyntaxBranchAnalyzer.RemoveShadowedAssignments(
            commandTypeAssignments.Select(assignment => (
                Assignment: (SyntaxNode)assignment,
                Value: assignment.Right)));

        SyntaxNode fallbackSpan = (SyntaxNode?)creation.FirstAncestorOrSelf<StatementSyntax>() ?? creation;
        var startOffset = relevantStatements.Count > 0
            ? relevantStatements.Min(statement => statement.SpanStart)
            : fallbackSpan.SpanStart;
        var endOffset = relevantStatements.Count > 0
            ? relevantStatements.Max(statement => statement.Span.End)
            : fallbackSpan.Span.End;

        var invocations = new List<DirectSqlInvocation>();
        foreach (var candidate in commandTextCandidates)
        {
            var terminalSinkResolution = ResolveTerminalSink(terminalSinks, candidate.BranchContext);
            var terminalSink = terminalSinkResolution.Name;
            var branchContext = SyntaxBranchAnalyzer.Combine(
                candidate.BranchContext,
                terminalSinkResolution.BranchContext);
            var matchingCommandTypeAssignments = effectiveCommandTypeAssignments
                .Where(assignment => SyntaxBranchAnalyzer.IsCompatible(
                    candidate.BranchContext,
                    SyntaxBranchAnalyzer.GetBranchContext(assignment.Assignment)))
                .ToList();
            var commandTypeModes = matchingCommandTypeAssignments
                .Select(assignment => IsStoredProcedureCommandType(assignment.Value)
                    ? "stored_procedure"
                    : IsTextCommandType(assignment.Value)
                        ? "text"
                        : "unknown")
                .Distinct(StringComparer.Ordinal)
                .ToList();
            var hasUnknownCommandType = commandTypeModes.Contains("unknown", StringComparer.Ordinal)
                || commandTypeModes.Count > 1;
            var matchingStoredProcedureAssignments = matchingCommandTypeAssignments
                .Where(assignment => IsStoredProcedureCommandType(assignment.Value))
                .ToList();
            var commandTypeMode = hasUnknownCommandType
                ? "unknown"
                : matchingStoredProcedureAssignments.Count > 0
                    ? "stored_procedure"
                    : matchingCommandTypeAssignments.Count > 0
                        ? "text"
                        : "default_text";

            if (hasUnknownCommandType)
            {
                invocations.Add(CreateInvocation(
                    className,
                    method.Identifier.Text,
                    candidate,
                    false,
                    connectionExpression,
                    startOffset,
                    endOffset,
                    variableName,
                    creation.Type.ToString(),
                    candidate.ArgumentExpression,
                    terminalSink,
                    commandTypeMode: commandTypeMode,
                    branchContext: branchContext));
                continue;
            }

            if (matchingStoredProcedureAssignments.Count == 0)
            {
                invocations.Add(CreateInvocation(
                    className,
                    method.Identifier.Text,
                    candidate,
                    false,
                    connectionExpression,
                    startOffset,
                    endOffset,
                    variableName,
                    creation.Type.ToString(),
                    candidate.ArgumentExpression,
                    terminalSink,
                    commandTypeMode: commandTypeMode,
                    branchContext: branchContext));
                continue;
            }

            foreach (var assignment in matchingStoredProcedureAssignments)
            {
                invocations.Add(CreateInvocation(
                    className,
                    method.Identifier.Text,
                    candidate,
                    true,
                    connectionExpression,
                    startOffset,
                    endOffset,
                    variableName,
                    creation.Type.ToString(),
                    candidate.ArgumentExpression,
                    terminalSink,
                    commandTypeMode: commandTypeMode,
                    branchContext: SyntaxBranchAnalyzer.Combine(
                        branchContext,
                        SyntaxBranchAnalyzer.GetBranchContext(assignment.Assignment))));
            }
        }

        return invocations
            .GroupBy(invocation => (
                invocation.CommandTextKind,
                invocation.CommandText,
                invocation.CommandTypeStoredProcedure,
                invocation.ConnectionExpression,
                invocation.StartOffset,
                invocation.EndOffset,
                BranchContext: string.Join("\u001f", invocation.BranchContext ?? Array.Empty<string>())))
            .Select(group => group.First())
            .ToList();
    }

    internal static IReadOnlyList<DirectSqlInvocation> AnalyzeAdapter(
        ObjectCreationExpressionSyntax creation)
    {
        var method = creation.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault();
        if (method is null)
            return Array.Empty<DirectSqlInvocation>();

        var adapterVariable = ResolveVariableName(creation);
        InvocationExpressionSyntax? fluentFill = null;
        if (creation.Parent is MemberAccessExpressionSyntax fluentMember
            && fluentMember.Expression == creation
            && CSharpAnalyzer.IsAdapterFillMethod(fluentMember.Name.Identifier.Text)
            && fluentMember.Parent is InvocationExpressionSyntax fluentInvocation
            && fluentInvocation.Expression == fluentMember)
        {
            fluentFill = fluentInvocation;
        }
        if (string.IsNullOrWhiteSpace(adapterVariable) && fluentFill is null)
            return Array.Empty<DirectSqlInvocation>();

        var arguments = creation.ArgumentList?.Arguments ?? default;
        var commandTextExpression = arguments.ElementAtOrDefault(0)?.Expression;
        if (commandTextExpression is null || CSharpAnalyzer.IsSqlCommandExpression(commandTextExpression, method))
            return Array.Empty<DirectSqlInvocation>();

        var fillSinks = fluentFill is not null
            ? new List<InvocationExpressionSyntax> { fluentFill }
            : method.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Where(invocation => invocation.Expression is MemberAccessExpressionSyntax member
                    && member.Expression.ToString().Trim() == adapterVariable
                    && CSharpAnalyzer.IsAdapterFillMethod(member.Name.Identifier.Text)
                    && invocation.SpanStart > creation.SpanStart)
                .OrderBy(invocation => invocation.SpanStart)
                .ToList();
        if (fillSinks.Count == 0)
            return Array.Empty<DirectSqlInvocation>();

        var className = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
        var connectionExpression = arguments.ElementAtOrDefault(1)?.Expression?.ToString().Trim();
        var relevantStatements = new List<StatementSyntax>();
        var creationStatement = creation.FirstAncestorOrSelf<StatementSyntax>();
        if (creationStatement is not null)
            relevantStatements.Add(creationStatement);
        relevantStatements.AddRange(
            fillSinks.Select(sink => sink.FirstAncestorOrSelf<StatementSyntax>())
                .Where(statement => statement is not null)
                .Cast<StatementSyntax>());
        var fallbackSpan = (SyntaxNode?)creation.FirstAncestorOrSelf<StatementSyntax>() ?? creation;
        var startOffset = relevantStatements.Count > 0
            ? relevantStatements.Min(statement => statement.SpanStart)
            : fallbackSpan.SpanStart;
        var endOffset = relevantStatements.Count > 0
            ? relevantStatements.Max(statement => statement.Span.End)
            : fallbackSpan.Span.End;

        return ReadCommandTextCandidates(
                commandTextExpression,
                method,
                creation,
                creation.SpanStart)
            .Select(candidate =>
            {
                var terminalSinkResolution = ResolveTerminalSink(
                    fillSinks,
                    candidate.BranchContext);
                return CreateInvocation(
                    className,
                    method.Identifier.Text,
                    candidate,
                    false,
                    connectionExpression,
                    startOffset,
                    endOffset,
                    adapterVariable,
                    creation.Type.ToString(),
                    candidate.ArgumentExpression,
                    terminalSinkResolution.Name,
                    commandTypeMode: "default_text",
                    branchContext: SyntaxBranchAnalyzer.Combine(
                        candidate.BranchContext,
                        terminalSinkResolution.BranchContext));
            })
            .GroupBy(invocation => (
                invocation.CommandTextKind,
                invocation.CommandText,
                invocation.ConnectionExpression,
                invocation.StartOffset,
                invocation.EndOffset,
                BranchContext: string.Join("\u001f", invocation.BranchContext ?? Array.Empty<string>())))
            .Select(group => group.First())
            .ToList();
    }

    private static DirectSqlInvocation CreateInvocation(
        string className,
        string methodName,
        CommandTextCandidate candidate,
        bool commandTypeStoredProcedure,
        string? connectionExpression,
        int startOffset,
        int endOffset,
        string? receiverName,
        string receiverType,
        string? commandTextArgument,
        string? terminalSink,
        string? commandTypeMode = null,
        IReadOnlyList<string>? branchContext = null)
        => new(
            className,
            methodName,
            candidate.CommandTextKind,
            candidate.CommandText,
            commandTypeStoredProcedure,
            connectionExpression,
            startOffset,
            endOffset,
            BranchContext: branchContext ?? candidate.BranchContext,
            ReceiverType: receiverType,
            ReceiverName: receiverName,
            CommandTextArgument: commandTextArgument,
            CommandTextLiteral: candidate.CommandText,
            TerminalSink: terminalSink,
            CommandTypeMode: commandTypeMode,
            CommandTextSourceStartOffset: candidate.SourceStartOffset,
            CommandTextSourceEndOffset: candidate.SourceEndOffset,
            CommandTextProvenance: candidate.ValueProvenance);

    private static string? ResolveVariableName(ObjectCreationExpressionSyntax creation)
    {
        if (creation.Parent is EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax declarator })
            return declarator.Identifier.Text;
        if (creation.Parent is AssignmentExpressionSyntax assignment
            && assignment.Right == creation)
            return assignment.Left.ToString();
        return null;
    }

    private static IReadOnlyList<InvocationExpressionSyntax> ResolveTerminalSinks(
        MethodDeclarationSyntax method,
        string? variableName,
        ObjectCreationExpressionSyntax creation,
        int creationStart)
    {
        if (variableName is null
            && creation.Parent is MemberAccessExpressionSyntax fluentMember
            && fluentMember.Expression == creation
            && fluentMember.Parent is InvocationExpressionSyntax fluentCall
            && fluentCall.Expression == fluentMember
            && IsTerminalSink(fluentMember.Name.Identifier.Text))
            return new[] { fluentCall };

        if (string.IsNullOrWhiteSpace(variableName))
            return Array.Empty<InvocationExpressionSyntax>();

        var adapterVariables = method.DescendantNodes()
            .OfType<ObjectCreationExpressionSyntax>()
            .Where(adapter => CSharpAnalyzer.IsDataAdapterType(adapter.Type))
            .Select(ResolveVariableName)
            .Where(adapterVariable => !string.IsNullOrWhiteSpace(adapterVariable))
            .Cast<string>()
            .Where(adapterVariable => method.DescendantNodes()
                .OfType<ObjectCreationExpressionSyntax>()
                .Where(adapter => ResolveVariableName(adapter) == adapterVariable)
                .Any(adapter => adapter.ArgumentList?.Arguments.Any(argument =>
                    argument.Expression.ToString().Trim() == variableName) is true)
                || method.DescendantNodes()
                    .OfType<AssignmentExpressionSyntax>()
                    .Any(assignment => assignment.Left is MemberAccessExpressionSyntax member
                        && member.Name.Identifier.Text == "SelectCommand"
                        && member.Expression.ToString().Trim() == adapterVariable
                        && assignment.Right.ToString().Trim() == variableName))
            .ToHashSet(StringComparer.Ordinal);

        return method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(call => call.Expression is MemberAccessExpressionSyntax member
                && member.Expression.ToString() == variableName
                && IsTerminalSink(member.Name.Identifier.Text)
                && call.SpanStart > creationStart)
            .OrderBy(call => call.SpanStart)
            .Concat(adapterVariables.SelectMany(adapterVariable => method.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Where(call => call.Expression is MemberAccessExpressionSyntax member
                    && member.Expression.ToString().Trim() == adapterVariable
                    && CSharpAnalyzer.IsAdapterFillMethod(member.Name.Identifier.Text)
                    && call.SpanStart > creationStart)))
            .DistinctBy(call => call.SpanStart)
            .OrderBy(call => call.SpanStart)
            .ToList();
    }

    private static TerminalSinkResolution ResolveTerminalSink(
        IReadOnlyList<InvocationExpressionSyntax> terminalSinks,
        IReadOnlyList<string> candidateBranchContext)
    {
        var matchingSinks = terminalSinks
            .Where(sink =>
            {
                var sinkBranchContext = SyntaxBranchAnalyzer.GetBranchContext(sink);
                return SyntaxBranchAnalyzer.IsCompatible(candidateBranchContext, sinkBranchContext)
                    || SyntaxBranchAnalyzer.IsCompatible(sinkBranchContext, candidateBranchContext);
            })
            .ToList();
        var sinkNames = matchingSinks
            .Select(sink => ((MemberAccessExpressionSyntax)sink.Expression).Name.Identifier.Text)
            .Distinct(StringComparer.Ordinal)
            .ToList();

        if (sinkNames.Count != 1)
            return new TerminalSinkResolution(null, Array.Empty<string>());

        var branchContext = matchingSinks.Count == 1
            ? SyntaxBranchAnalyzer.GetBranchContext(matchingSinks[0])
            : Array.Empty<string>();
        return new TerminalSinkResolution(sinkNames[0], branchContext);
    }

    private static bool IsTerminalSink(string methodName)
        => methodName is "ExecuteNonQuery"
            or "ExecuteNonQueryAsync"
            or "ExecuteReader"
            or "ExecuteReaderAsync"
            or "ExecuteScalar"
            or "ExecuteScalarAsync";

    private static (string Kind, string? Text) ReadCommandText(ExpressionSyntax? expression)
    {
        if (expression is null)
            return ("unknown", null);
        if (expression is LiteralExpressionSyntax { Token.Value: string literalValue })
            return ("literal", literalValue);
        return ("dynamic", null);
    }

    private static IReadOnlyList<CommandTextCandidate> ReadCommandTextCandidates(
        ExpressionSyntax? expression,
        MethodDeclarationSyntax method,
        SyntaxNode anchor,
        int position,
        string? originalArgumentExpression = null)
    {
        var argumentExpression = originalArgumentExpression ?? expression?.ToString();
        if (expression is IdentifierNameSyntax identifier)
        {
            var assignments = method.DescendantNodes()
                .OfType<AssignmentExpressionSyntax>()
                .Where(assignment => assignment.Left is IdentifierNameSyntax left
                    && left.Identifier.Text == identifier.Identifier.Text
                    && assignment.SpanStart < position)
                .Select(assignment => (
                    Assignment: (SyntaxNode)assignment,
                    Value: assignment.Right))
                .ToList();
            var declarations = method.DescendantNodes()
                .OfType<VariableDeclaratorSyntax>()
                .Where(declaration => declaration.Identifier.Text == identifier.Identifier.Text
                    && declaration.Initializer is not null
                    && declaration.SpanStart < position)
                .Select(declaration => (
                    Assignment: (SyntaxNode)declaration,
                    Value: declaration.Initializer!.Value))
                .ToList();

            var resolved = SyntaxBranchAnalyzer.RemoveShadowedAssignments(
                assignments.Concat(declarations.Select(item => (item.Assignment, item.Value))))
                .SelectMany(item => ReadCommandTextCandidates(
                    item.Value,
                    method,
                    item.Assignment,
                    item.Assignment.SpanStart,
                    allowVariableLookup: false,
                    originalArgumentExpression: argumentExpression))
                .ToList();
            if (resolved.Count > 0)
                return resolved;
        }

        var (kind, text) = ReadCommandText(expression);
        return new[]
        {
            new CommandTextCandidate(
                kind,
                text,
                argumentExpression,
                SyntaxBranchAnalyzer.GetBranchContext(anchor),
                anchor.SpanStart,
                anchor.Span.End,
                BuildCommandTextProvenance(anchor, text)),
        };
    }

    private static IReadOnlyList<CommandTextCandidate> ReadCommandTextCandidates(
        ExpressionSyntax? expression,
        MethodDeclarationSyntax method,
        SyntaxNode anchor,
        int position,
        bool allowVariableLookup,
        string? originalArgumentExpression = null)
    {
        if (allowVariableLookup)
            return ReadCommandTextCandidates(
                expression,
                method,
                anchor,
                position,
                originalArgumentExpression);

        var (kind, text) = ReadCommandText(expression);
        return new[]
        {
            new CommandTextCandidate(
                kind,
                text,
                originalArgumentExpression ?? expression?.ToString(),
                SyntaxBranchAnalyzer.GetBranchContext(anchor),
                anchor.SpanStart,
                anchor.Span.End,
                BuildCommandTextProvenance(anchor, text)),
        };
    }

    private static string BuildCommandTextProvenance(SyntaxNode anchor, string? value)
        => anchor is VariableDeclaratorSyntax or AssignmentExpressionSyntax
            ? $"assignment:{anchor.ToString().Trim()}"
            : value is null
                ? "dynamic_expression"
                : "literal_expression";

    /// <summary>Matches an exact `CommandType.StoredProcedure` member access or an equivalent numeric cast, e.g. `(CommandType)4`.</summary>
    private static bool IsStoredProcedureCommandType(ExpressionSyntax expression)
        => expression is MemberAccessExpressionSyntax { Name.Identifier.Text: "StoredProcedure" }
            || CommandTypeCastRecognizer.ResolveNumericCastMember(expression) == "StoredProcedure";

    private static bool IsTextCommandType(ExpressionSyntax expression)
        => expression is MemberAccessExpressionSyntax { Name.Identifier.Text: "Text" }
            || CommandTypeCastRecognizer.ResolveNumericCastMember(expression) == "Text";

    private sealed record CommandTextCandidate(
        string CommandTextKind,
        string? CommandText,
        string? ArgumentExpression,
        IReadOnlyList<string> BranchContext,
        int? SourceStartOffset = null,
        int? SourceEndOffset = null,
        string ValueProvenance = "");

    private sealed record TerminalSinkResolution(
        string? Name,
        IReadOnlyList<string> BranchContext);
}

internal static class AdapterAnalyzer
{
    private static readonly HashSet<string> DapperMethods = new(StringComparer.OrdinalIgnoreCase)
    {
        "Query",
        "QueryAsync",
        "QueryFirst",
        "QueryFirstAsync",
        "QueryFirstOrDefault",
        "QueryFirstOrDefaultAsync",
        "QuerySingle",
        "QuerySingleAsync",
        "QuerySingleOrDefault",
        "QuerySingleOrDefaultAsync",
        "QueryMultiple",
        "QueryMultipleAsync",
        "Execute",
        "ExecuteAsync",
        "ExecuteScalar",
        "ExecuteScalarAsync",
    };

    private static readonly HashSet<string> EntityFrameworkMethods = new(StringComparer.OrdinalIgnoreCase)
    {
        "ExecuteSqlCommand",
        "ExecuteSqlCommandAsync",
        "ExecuteSqlRaw",
        "ExecuteSqlRawAsync",
        "SqlQuery",
        "SqlQueryRaw",
        "FromSqlRaw",
        "FromSqlInterpolated",
    };

    internal static bool IsRecognizedAdapterInvocation(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax method)
    {
        if (call.Expression is not MemberAccessExpressionSyntax member)
            return false;

        var methodName = member.Name.Identifier.Text;
        return DapperMethods.Contains(methodName)
            && LooksLikeDapperReceiver(member.Expression, method, call.SpanStart)
            || EntityFrameworkMethods.Contains(methodName)
            && LooksLikeEntityFrameworkReceiver(member.Expression, method, call.SpanStart);
    }

    internal static List<DirectSqlInvocation> Analyze(
        CompilationUnitSyntax root,
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var roots = sourceRoots.ToList();
        var wrapperDefinitions = WrapperAnalyzer.GetDefinitions(roots);
        var knownTypeIdentities = WrapperAnalyzer.GetKnownTypeIdentities(roots);
        var invocations = new List<DirectSqlInvocation>();
        foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            var className = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
            foreach (var call in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                if (call.Expression is not MemberAccessExpressionSyntax member)
                    continue;
                if (WrapperAnalyzer.IsSourceWrapperInvocation(
                    call,
                    method,
                    wrapperDefinitions,
                    knownTypeIdentities,
                    roots))
                    continue;

                var methodName = member.Name.Identifier.Text;
                if (DapperMethods.Contains(methodName)
                    && LooksLikeDapperReceiver(member.Expression, method, call.SpanStart))
                    invocations.AddRange(AnalyzeDapperCall(call, method, className, member));
                else if (EntityFrameworkMethods.Contains(methodName)
                    && LooksLikeEntityFrameworkReceiver(member.Expression, method, call.SpanStart))
                    invocations.AddRange(AnalyzeEntityFrameworkCall(call, method, className, member));
            }
        }
        return invocations;
    }

    private static IReadOnlyList<DirectSqlInvocation> AnalyzeDapperCall(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax method,
        string className,
        MemberAccessExpressionSyntax member)
    {
        var arguments = call.ArgumentList.Arguments;
        var commandTextExpression = arguments.ElementAtOrDefault(0)?.Expression;
        var mode = ResolveDapperMode(arguments, commandTextExpression);
        var candidates = ReadCommandTextCandidates(commandTextExpression, method, call, call.SpanStart);
        var callContext = SyntaxBranchAnalyzer.GetBranchContext(call);
        var connectionExpression = member.Expression.ToString().Trim();

        return candidates.Select(candidate => new DirectSqlInvocation(
            className,
            method.Identifier.Text,
            candidate.CommandTextKind,
            candidate.CommandText,
            mode == "stored_procedure",
            connectionExpression,
            call.SpanStart,
            call.Span.End,
            InvocationKind: "dapper",
            WrapperMode: mode,
            MethodChain: new[] { method.Identifier.Text, member.Name.Identifier.Text },
            BranchContext: SyntaxBranchAnalyzer.Combine(callContext, candidate.BranchContext),
            TerminalSink: ResolveTerminalSink(member.Name.Identifier.Text),
            CommandTextSourceStartOffset: candidate.SourceStartOffset,
            CommandTextSourceEndOffset: candidate.SourceEndOffset,
            CommandTextProvenance: candidate.ValueProvenance))
            .ToList();
    }

    private static IReadOnlyList<DirectSqlInvocation> AnalyzeEntityFrameworkCall(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax method,
        string className,
        MemberAccessExpressionSyntax member)
    {
        var expression = call.ArgumentList.Arguments.ElementAtOrDefault(0)?.Expression;
        var callContext = SyntaxBranchAnalyzer.GetBranchContext(call);
        var connectionExpression = member.Expression.ToString().Trim();
        return ReadCommandTextCandidates(expression, method, call, call.SpanStart)
            .Select(candidate =>
            {
                var mode = ResolveEntityFrameworkMode(
                    call.ArgumentList.Arguments,
                    candidate.CommandText);
                return new DirectSqlInvocation(
                    className,
                    method.Identifier.Text,
                    candidate.CommandTextKind,
                    candidate.CommandText,
                    mode == "stored_procedure",
                    connectionExpression,
                    call.SpanStart,
                    call.Span.End,
                    InvocationKind: "entity_framework",
                    WrapperMode: mode,
                    MethodChain: new[] { method.Identifier.Text, member.Name.Identifier.Text },
                    BranchContext: SyntaxBranchAnalyzer.Combine(
                        callContext,
                        candidate.BranchContext),
                    TerminalSink: ResolveTerminalSink(member.Name.Identifier.Text),
                    CommandTypeMode: mode switch
                    {
                        "stored_procedure" => "stored_procedure",
                        "inline_sql" => "text",
                        _ => "unknown",
                    },
                    CommandTextSourceStartOffset: candidate.SourceStartOffset,
                    CommandTextSourceEndOffset: candidate.SourceEndOffset,
                    CommandTextProvenance: candidate.ValueProvenance);
            })
            .ToList();
    }

    private static string ResolveEntityFrameworkMode(
        SeparatedSyntaxList<ArgumentSyntax> arguments,
        string? commandText)
    {
        var commandTypeArgument = arguments.FirstOrDefault(argument =>
            argument.NameColon?.Name.Identifier.Text.Equals("commandType", StringComparison.OrdinalIgnoreCase) == true);
        if (commandTypeArgument is not null)
        {
            if (IsCommandType(commandTypeArgument.Expression, "StoredProcedure"))
                return "stored_procedure";
            if (IsCommandType(commandTypeArgument.Expression, "Text"))
                return "inline_sql";
            return "unknown";
        }

        return commandText is not null && LooksLikeInlineSql(commandText)
            ? "inline_sql"
            : "unknown";
    }

    private static string ResolveTerminalSink(string methodName)
    {
        if (methodName.StartsWith("Query", StringComparison.OrdinalIgnoreCase)
            || methodName.StartsWith("FromSql", StringComparison.OrdinalIgnoreCase)
            || methodName.StartsWith("SqlQuery", StringComparison.OrdinalIgnoreCase))
            return "ExecuteReader";
        if (methodName.Contains("Scalar", StringComparison.OrdinalIgnoreCase))
            return "ExecuteScalar";
        return "ExecuteNonQuery";
    }

    private static string ResolveDapperMode(
        SeparatedSyntaxList<ArgumentSyntax> arguments,
        ExpressionSyntax? commandTextExpression)
    {
        var commandTypeArgument = arguments.FirstOrDefault(argument =>
            argument.NameColon?.Name.Identifier.Text.Equals("commandType", StringComparison.OrdinalIgnoreCase) == true);
        if (commandTypeArgument is not null)
        {
            if (IsCommandType(commandTypeArgument.Expression, "StoredProcedure"))
                return "stored_procedure";
            if (IsCommandType(commandTypeArgument.Expression, "Text"))
                return "inline_sql";
            return "unknown";
        }

        if (commandTextExpression is LiteralExpressionSyntax { Token.Value: string text }
            && LooksLikeInlineSql(text))
            return "inline_sql";
        return "unknown";
    }

    private static bool IsCommandType(ExpressionSyntax expression, string memberName)
        => expression is MemberAccessExpressionSyntax member
            && member.Name.Identifier.Text.Equals(memberName, StringComparison.Ordinal);

    private static bool LooksLikeDapperReceiver(
        ExpressionSyntax expression,
        MethodDeclarationSyntax method,
        int position)
    {
        var receiver = expression.ToString().Trim().Split('.').Last().TrimStart('_');
        return (receiver.Equals("connection", StringComparison.OrdinalIgnoreCase)
            || receiver.Equals("conn", StringComparison.OrdinalIgnoreCase)
            || receiver.Equals("db", StringComparison.OrdinalIgnoreCase)
            || receiver.Equals("database", StringComparison.OrdinalIgnoreCase)
            || receiver.EndsWith("connection", StringComparison.OrdinalIgnoreCase)
            || receiver.EndsWith("database", StringComparison.OrdinalIgnoreCase)
            || receiver.EndsWith("db", StringComparison.OrdinalIgnoreCase))
            && GetReceiverTypeNames(expression, method, position).Any(IsDatabaseConnectionType);
    }

    private static bool LooksLikeEntityFrameworkReceiver(
        ExpressionSyntax expression,
        MethodDeclarationSyntax method,
        int position)
        => GetReceiverTypeNames(expression, method, position).Any(IsEntityFrameworkContextType);

    private static IReadOnlyList<string> GetReceiverTypeNames(
        ExpressionSyntax expression,
        MethodDeclarationSyntax method,
        int position)
    {
        var receiverName = GetReceiverName(expression);
        if (receiverName is null)
            return Array.Empty<string>();

        var localTypes = method.DescendantNodes()
            .OfType<VariableDeclarationSyntax>()
            .Where(declaration => declaration.SpanStart < position)
            .SelectMany(declaration => declaration.Variables
                .Where(variable => variable.Identifier.Text == receiverName)
                .SelectMany(variable => GetVariableTypeNames(declaration, variable)))
            .ToList();
        if (localTypes.Count > 0)
            return localTypes;

        var parameterTypes = method.ParameterList.Parameters
            .Where(parameter => parameter.Identifier.Text == receiverName && parameter.Type is not null)
            .Select(parameter => parameter.Type!.ToString())
            .ToList();
        if (parameterTypes.Count > 0)
            return parameterTypes;

        var classDeclaration = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        if (classDeclaration is null)
            return Array.Empty<string>();

        var fieldTypes = classDeclaration.DescendantNodes()
            .OfType<FieldDeclarationSyntax>()
            .Where(field => field.Declaration.Variables.Any(variable => variable.Identifier.Text == receiverName))
            .Select(field => field.Declaration.Type.ToString())
            .ToList();
        if (fieldTypes.Count > 0)
            return fieldTypes;

        return classDeclaration.DescendantNodes()
            .OfType<PropertyDeclarationSyntax>()
            .Where(property => property.Identifier.Text == receiverName)
            .Select(property => property.Type.ToString())
            .ToList();
    }

    private static IEnumerable<string> GetVariableTypeNames(
        VariableDeclarationSyntax declaration,
        VariableDeclaratorSyntax variable)
    {
        if (!declaration.Type.ToString().Equals("var", StringComparison.Ordinal))
        {
            yield return declaration.Type.ToString();
            yield break;
        }

        if (variable.Initializer?.Value is ObjectCreationExpressionSyntax creation)
            yield return creation.Type.ToString();
    }

    private static string? GetReceiverName(ExpressionSyntax expression)
    {
        if (expression is IdentifierNameSyntax identifier)
            return identifier.Identifier.Text;
        if (expression is MemberAccessExpressionSyntax member)
        {
            if (member.Expression is ThisExpressionSyntax)
                return member.Name.Identifier.Text;
            return GetReceiverName(member.Expression);
        }
        return null;
    }

    private static bool IsDatabaseConnectionType(string typeName)
    {
        var name = typeName.Trim().TrimEnd('?').Split('.').Last();
        return name is "IDbConnection"
            or "DbConnection"
            or "SqlConnection"
            or "SqliteConnection"
            or "NpgsqlConnection"
            or "MySqlConnection"
            or "OracleConnection"
            or "OleDbConnection"
            or "OdbcConnection";
    }

    private static bool IsEntityFrameworkContextType(string typeName)
    {
        var name = typeName.Trim().TrimEnd('?').Split('.').Last();
        return name.Equals("DbContext", StringComparison.Ordinal)
            || name.EndsWith("DbContext", StringComparison.Ordinal);
    }

    private static bool LooksLikeInlineSql(string text)
        => SqlTextClassifier.LooksLikeInlineSql(text);

    private static IReadOnlyList<AdapterCommandTextCandidate> ReadCommandTextCandidates(
        ExpressionSyntax? expression,
        MethodDeclarationSyntax method,
        SyntaxNode anchor,
        int position)
    {
        if (expression is IdentifierNameSyntax identifier)
        {
            var assignments = method.DescendantNodes()
                .OfType<AssignmentExpressionSyntax>()
                .Where(assignment => assignment.Left is IdentifierNameSyntax left
                    && left.Identifier.Text == identifier.Identifier.Text
                    && assignment.SpanStart < position)
                .Select(assignment => (
                    Assignment: (SyntaxNode)assignment,
                    Value: assignment.Right));
            var declarations = method.DescendantNodes()
                .OfType<VariableDeclaratorSyntax>()
                .Where(declaration => declaration.Identifier.Text == identifier.Identifier.Text
                    && declaration.Initializer is not null
                    && declaration.SpanStart < position)
                .Select(declaration => (
                    Assignment: (SyntaxNode)declaration,
                    Value: declaration.Initializer!.Value))
                .ToList();
            var resolved = SyntaxBranchAnalyzer.RemoveShadowedAssignments(
                assignments.Concat(declarations))
                .Select(item => ReadCommandTextCandidate(
                    item.Value,
                    SyntaxBranchAnalyzer.GetBranchContext(item.Assignment),
                    item.Assignment))
                .ToList();
            if (resolved.Count > 0)
                return resolved;
        }

        return new[]
        {
            ReadCommandTextCandidate(
                expression,
                SyntaxBranchAnalyzer.GetBranchContext(anchor),
                anchor),
        };
    }

    private static AdapterCommandTextCandidate ReadCommandTextCandidate(
        ExpressionSyntax? expression,
        IReadOnlyList<string> branchContext,
        SyntaxNode anchor)
    {
        if (expression is LiteralExpressionSyntax { Token.Value: string text })
            return new AdapterCommandTextCandidate(
                "literal",
                text,
                branchContext,
                anchor.SpanStart,
                anchor.Span.End,
                anchor is VariableDeclaratorSyntax or AssignmentExpressionSyntax
                    ? $"assignment:{anchor.ToString().Trim()}"
                    : "literal_expression");
        return new AdapterCommandTextCandidate(
            "dynamic",
            null,
            branchContext,
            anchor.SpanStart,
            anchor.Span.End,
            "dynamic_expression");
    }

    private sealed record AdapterCommandTextCandidate(
        string CommandTextKind,
        string? CommandText,
        IReadOnlyList<string> BranchContext,
        int? SourceStartOffset = null,
        int? SourceEndOffset = null,
        string ValueProvenance = "");
}

internal sealed record CSharpAnalysis(string SourceId, List<MethodSourceSpan> Methods, List<DirectSqlInvocation> DbInvocations);
internal sealed record MethodSourceSpan(string ClassName, string MethodName, int StartOffset, int EndOffset);
internal sealed record CSharpSource(string InputPath, CompilationUnitSyntax Root);

/// <summary>Raw facts for one direct `SqlCommand` setup; evidence rating happens in the Python gateway.</summary>
internal sealed record DirectSqlInvocation(
    string ClassName,
    string MethodName,
    string CommandTextKind,
    string? CommandText,
    bool CommandTypeStoredProcedure,
    string? ConnectionExpression,
    int StartOffset,
    int EndOffset,
    string InvocationKind = "direct_sqlclient",
    string? WrapperClassName = null,
    string? WrapperMethodName = null,
    bool WrapperSourceAvailable = false,
    bool WrapperReachesStoredProcedureSink = false,
    string WrapperMode = "",
    IReadOnlyList<string>? MethodChain = null,
    IReadOnlyList<string>? BranchContext = null,
    string? WrapperReceiverType = null,
    string? ReceiverType = null,
    string? ReceiverName = null,
    string? CommandTextArgument = null,
    string? CommandTextLiteral = null,
    string? TerminalSink = null,
    string? CommandTypeMode = null,
    string? ReceiverExpression = null,
    string? ReceiverImplementationIdentity = null,
    string? ReceiverAssemblyIdentity = null,
    string? ReceiverAssemblyRevision = null,
    string? ReceiverBindingProvenance = null,
    IReadOnlyList<string>? ReceiverConstructionFacts = null,
    IReadOnlyList<string>? ReceiverAssignmentFacts = null,
    string? WrapperImplementationIdentity = null,
    string? WrapperAssemblyIdentity = null,
    string? WrapperAssemblyRevision = null,
    string? WrapperMethodIdentity = null,
    int? WrapperMethodArity = null,
    IReadOnlyList<string>? WrapperParameterTypes = null,
    string? WrapperMethodSemantics = null,
    string? WrapperTerminalSink = null,
    IReadOnlyList<WrapperOverloadCandidateFact>? WrapperOverloadCandidates = null,
    bool WrapperOverloadAmbiguous = false,
    string? WrapperUnresolvedReason = null,
    IReadOnlyList<string>? ConnectionExpressionCandidates = null,
    int? CommandTextSourceStartOffset = null,
    int? CommandTextSourceEndOffset = null,
    string? CommandTextProvenance = null,
    string? WrapperReceiverTypeProvenance = null,
    bool CommandTypeArgumentObserved = false);

/// <summary>One ambiguous/unavailable overload candidate's bound-implementation and signature facts.</summary>
internal sealed record WrapperOverloadCandidateFact(
    string? ImplementationIdentity,
    string? ReceiverType,
    string MethodName,
    int? MethodArity,
    IReadOnlyList<string> ParameterTypes,
    string MethodIdentity);

internal static class SyntaxBranchAnalyzer
{
    internal static IReadOnlyList<string> GetBranchContext(SyntaxNode node)
    {
        var context = new List<string>();
        foreach (var ancestor in node.Ancestors().Reverse())
        {
            if (ancestor is IfStatementSyntax ifStatement)
            {
                if (ifStatement.Statement.Span.Contains(node.Span))
                    context.Add($"if ({ifStatement.Condition})");
                else if (ifStatement.Else?.Statement.Span.Contains(node.Span) == true)
                    context.Add($"else ({ifStatement.Condition})");
            }
            else if (ancestor is ConditionalExpressionSyntax conditional)
            {
                if (conditional.WhenTrue.Span.Contains(node.Span))
                    context.Add($"when ({conditional.Condition})");
                else if (conditional.WhenFalse.Span.Contains(node.Span))
                    context.Add($"else ({conditional.Condition})");
            }
            else if (ancestor is SwitchSectionSyntax section)
            {
                foreach (var label in section.Labels)
                    context.Add(label.ToString().Trim());
            }
        }
        return context.Distinct(StringComparer.Ordinal).ToList();
    }

    internal static IReadOnlyList<string> Combine(
        IEnumerable<string> first,
        IEnumerable<string> second)
        => first.Concat(second).Distinct(StringComparer.Ordinal).ToList();

    internal static IReadOnlyList<(SyntaxNode Assignment, ExpressionSyntax Value)> RemoveShadowedAssignments(
        IEnumerable<(SyntaxNode Assignment, ExpressionSyntax Value)> assignments)
    {
        var ordered = assignments
            .OrderBy(item => item.Assignment.SpanStart)
            .ToList();
        return ordered
            .Where((candidate, index) => !ordered
                .Skip(index + 1)
                .Any(later => IsAlwaysOverridden(candidate.Assignment, later.Assignment)))
            .ToList();
    }

    internal static bool IsCompatible(
        IReadOnlyList<string> candidateContext,
        IReadOnlyList<string> assignmentContext)
    {
        if (assignmentContext.Count == 0)
            return true;
        return IsPrefix(assignmentContext, candidateContext);
    }

    private static bool IsPrefix(IReadOnlyList<string> prefix, IReadOnlyList<string> value)
        => prefix.Count <= value.Count && prefix.SequenceEqual(value.Take(prefix.Count));

    private static bool IsAlwaysOverridden(SyntaxNode candidate, SyntaxNode later)
    {
        var candidateContext = GetBranchContext(candidate);
        var laterContext = GetBranchContext(later);
        return laterContext.Count == 0 || IsPrefix(laterContext, candidateContext);
    }
}

internal static class WrapperAnalyzer
{
    // Three whole-corpus walks below -- GetKnownTypeIdentities, GetDefinitions, and
    // FindUsedWrapperMethodIdentities -- are pure functions of the parsed source roots. One
    // `csharp` invocation parses those roots once and then hands the same syntax-tree instances
    // to CSharpAnalyzer.Analyze for every --input file, so each walk produced an identical
    // result and was thrown away, making one scan cost O(inputs x corpus). On the 541-file
    // Y-Docs TTPUR project one ten-file batch ran for over five minutes without finishing, while
    // the 25-file STC project scanned fine -- a project 21 times larger was hundreds of times
    // slower. Batching could not help: every batch repeated the same walks.
    //
    // Memoize on the roots' object identity, not on their content: the analyzer never mutates a
    // syntax tree, so the same tree instances always yield the same corpus facts, and a caller
    // that parses fresh trees (the single-file Analyze overload, or a new host invocation) gets
    // a miss and a correct recompute. A memoized result is shared, so a caller must read it and
    // never mutate it. The assembly-identity GetDefinitions overload stays uncached: the
    // decompiler passes it one synthetic root per receiver type, not the project corpus.
    private static IReadOnlyList<CompilationUnitSyntax>? _knownTypeIdentitiesRoots;
    private static IReadOnlyList<string>? _knownTypeIdentitiesCache;
    private static IReadOnlyList<CompilationUnitSyntax>? _definitionsRoots;
    private static List<WrapperDefinition>? _definitionsCache;
    private static IReadOnlyList<CompilationUnitSyntax>? _usedWrapperMethodIdentitiesRoots;
    private static IReadOnlySet<string>? _usedWrapperMethodIdentitiesCache;
    private static readonly DeclarationIndex<ClassDeclarationSyntax> ClassDeclarationsByIdentity =
        new(CSharpAnalyzer.GetTypeIdentity);
    private static readonly DeclarationIndex<TypeDeclarationSyntax> TypeDeclarationsByName =
        new(declaration => declaration.Identifier.Text);

    /// <summary>
    /// One corpus-wide declaration index, grouped under whichever key its owner chose, and
    /// rebuilt only when a caller hands over a different set of syntax-tree instances.
    ///
    /// Every question this answers is asked once per candidate method or per call site, so
    /// answering it by walking every syntax tree each time costs O(sites x corpus) -- the shape
    /// that once left one ten-file TTPUR batch running for three and a half minutes. Memoize on
    /// the roots' object identity, not their content: the analyzer never mutates a syntax tree,
    /// so the same tree instances always yield the same index, a caller that parses fresh trees
    /// gets a miss and a correct rebuild, and a content comparison would cost more than the walk
    /// it guards. A returned list is the shared index's own, so a caller must read it and never
    /// mutate it.
    /// </summary>
    private sealed class DeclarationIndex<TDeclaration>
        where TDeclaration : SyntaxNode
    {
        private readonly Func<TDeclaration, string> _key;
        private IReadOnlyList<CompilationUnitSyntax>? _roots;
        private Dictionary<string, List<TDeclaration>>? _declarations;

        internal DeclarationIndex(Func<TDeclaration, string> key) => _key = key;

        internal IReadOnlyList<TDeclaration> Lookup(
            IReadOnlyList<CompilationUnitSyntax> roots,
            string key)
        {
            if (!SameRoots(roots, _roots))
            {
                // Deduplicated by (file, span start) so a partial declaration spread over
                // several files contributes each of its parts exactly once.
                _declarations = roots
                    .SelectMany(sourceRoot => sourceRoot.DescendantNodes().OfType<TDeclaration>())
                    .DistinctBy(candidate => (candidate.SyntaxTree?.FilePath ?? "", candidate.SpanStart))
                    .GroupBy(_key, StringComparer.Ordinal)
                    .ToDictionary(group => group.Key, group => group.ToList(), StringComparer.Ordinal);
                _roots = roots;
            }
            return _declarations!.TryGetValue(key, out var declarations)
                ? declarations
                : Array.Empty<TDeclaration>();
        }
    }

    /// <summary>Whether two root lists hold the very same syntax-tree instances in the same
    /// order. Reference identity is the point: a content comparison would cost more than the
    /// walk it guards.</summary>
    private static bool SameRoots(
        IReadOnlyList<CompilationUnitSyntax> roots,
        IReadOnlyList<CompilationUnitSyntax>? cachedRoots)
    {
        if (cachedRoots is null || cachedRoots.Count != roots.Count)
            return false;
        for (var index = 0; index < roots.Count; index++)
            if (!ReferenceEquals(roots[index], cachedRoots[index]))
                return false;
        return true;
    }

    private static IReadOnlyList<CompilationUnitSyntax> AsRootList(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
        => sourceRoots as IReadOnlyList<CompilationUnitSyntax> ?? sourceRoots.ToList();

    /// <summary>
    /// Every class declaration in the corpus that carries the given type identity, in corpus
    /// order. Command Source resolution asks this once per candidate method and once per call
    /// site; before the index behind it existed, one ten-file TTPUR batch ran for three and a
    /// half minutes, and afterwards took 14.6 seconds with the whole 541-file project at 2.1
    /// minutes.
    /// </summary>
    internal static IReadOnlyList<ClassDeclarationSyntax> GetClassDeclarations(
        IEnumerable<CompilationUnitSyntax> sourceRoots,
        string typeIdentity)
        => ClassDeclarationsByIdentity.Lookup(AsRootList(sourceRoots), typeIdentity);

    /// <summary>
    /// Every type declaration in the corpus carrying the given simple name -- the name a
    /// receiver's declared type is written under at a call site, which is all the syntax-only
    /// path has to look one up by. Its sibling above keys on the full type identity; nothing
    /// here can, because a receiver's declared type arrives as bare source text with no
    /// namespace attached.
    /// </summary>
    private static IReadOnlyList<TypeDeclarationSyntax> GetTypeDeclarationsByName(
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        string typeName)
        => TypeDeclarationsByName.Lookup(sourceRoots, typeName);

    internal static bool IsSourceWrapperInvocation(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        IReadOnlyList<WrapperDefinition> wrappers,
        IReadOnlyCollection<string> knownTypeIdentities,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(
            caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
        var resolution = ResolveDefinition(
            call,
            caller,
            callerTypeIdentity,
            wrappers,
            sourceRoots,
            knownTypeIdentities);
        var methodName = call.Expression switch
        {
            MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            _ => "",
        };
        var sourceCandidates = wrappers
            .Where(wrapper => wrapper.MethodName == methodName)
            .ToList();
        if (resolution is null || sourceCandidates.Count == 0)
            return false;
        if (resolution.Candidates.Count > 0)
            return true;
        if (!string.Equals(
                resolution.Reason,
                "receiver_binding_unresolved",
                StringComparison.Ordinal))
            return false;
        return sourceCandidates.Any(wrapper => ReceiverTypeMayBeWrapper(
            resolution.Binding.ReceiverType,
            wrapper,
            sourceRoots,
            knownTypeIdentities));
    }

    private static bool ReceiverTypeMayBeWrapper(
        string receiverType,
        WrapperDefinition wrapper,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        if (string.IsNullOrWhiteSpace(receiverType))
            return false;
        if (string.Equals(receiverType, wrapper.TypeIdentity, StringComparison.Ordinal))
            return true;

        return sourceRoots
            .SelectMany(sourceRoot => sourceRoot.DescendantNodes().OfType<TypeDeclarationSyntax>())
            .Where(typeDeclaration => string.Equals(
                CSharpAnalyzer.GetTypeIdentity(typeDeclaration),
                wrapper.TypeIdentity,
                StringComparison.Ordinal))
            .SelectMany(typeDeclaration => typeDeclaration
                .DescendantNodes()
                .OfType<MethodDeclarationSyntax>()
                .Where(method => method.Identifier.Text == wrapper.MethodName))
            .Any(method => method.Ancestors()
                .OfType<TypeDeclarationSyntax>()
                .FirstOrDefault()?
                .BaseList?
                .Types
                .Select(baseType => CSharpAnalyzer.ResolveKnownTypeIdentities(
                    baseType.Type.ToString(),
                    method,
                    knownTypeIdentities))
                .SelectMany(types => types)
                .Contains(receiverType, StringComparer.Ordinal) is true);
    }

    internal static IReadOnlySet<string> FindUsedWrapperMethodIdentities(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var rootList = AsRootList(sourceRoots);
        if (SameRoots(rootList, _usedWrapperMethodIdentitiesRoots))
            return _usedWrapperMethodIdentitiesCache!;
        var usedWrapperMethodIdentities = ComputeUsedWrapperMethodIdentities(rootList);
        _usedWrapperMethodIdentitiesRoots = rootList;
        _usedWrapperMethodIdentitiesCache = usedWrapperMethodIdentities;
        return usedWrapperMethodIdentities;
    }

    private static IReadOnlySet<string> ComputeUsedWrapperMethodIdentities(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var roots = sourceRoots.ToList();
        var wrappers = GetDefinitions(roots);
        var knownTypeIdentities = GetKnownTypeIdentities(roots);
        return roots
            .SelectMany(sourceRoot => sourceRoot.DescendantNodes().OfType<MethodDeclarationSyntax>())
            .SelectMany(method =>
            {
                    var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(
                    method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
                return method.DescendantNodes()
                    .OfType<InvocationExpressionSyntax>()
                            .Select(call => ResolveDefinition(
                                call,
                                method,
                                callerTypeIdentity,
                                wrappers,
                                roots,
                                knownTypeIdentities))
                        .Where(resolution => resolution is not null)
                        .SelectMany(resolution => resolution!.Candidates);
            })
                        .Select(definition => definition.MethodIdentity)
            .ToHashSet();
    }

                internal static string? GetMethodIdentity(
                    MethodDeclarationSyntax? method,
                    IReadOnlyCollection<string> knownTypeIdentities)
                {
                    if (method is null)
                        return null;
                    var classDeclaration = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
                    var typeIdentity = CSharpAnalyzer.GetTypeIdentity(classDeclaration);
                    if (string.IsNullOrWhiteSpace(typeIdentity))
                        return null;
                    return BuildMethodIdentity(
                        typeIdentity,
                        method.Identifier.Text,
                        ResolveParameterTypes(method, knownTypeIdentities));
                }

                private static IReadOnlyList<string> ResolveParameterTypes(
                    MethodDeclarationSyntax method,
                    IReadOnlyCollection<string> knownTypeIdentities)
                    => method.ParameterList.Parameters
                        .Select(parameter => parameter.Type is null
                            ? ""
                            : CSharpAnalyzer.ResolveKnownTypeIdentities(
                                parameter.Type.ToString(),
                                method,
                                knownTypeIdentities) is [var parameterType]
                                ? parameterType
                                : parameter.Type.ToString().Trim())
                        .ToList();

    internal static List<DirectSqlInvocation> Analyze(
        CompilationUnitSyntax root,
        IEnumerable<CompilationUnitSyntax> sourceRoots,
        CSharpCompilation? compilation = null)
    {
        var roots = sourceRoots.ToList();
        var wrappers = GetDefinitions(roots);
        var knownTypeIdentities = GetKnownTypeIdentities(roots);

        var invocations = new List<DirectSqlInvocation>();
        foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            var callerClass = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
            var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(
                method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
            foreach (var call in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var resolution = ResolveDefinition(
                    call,
                    method,
                    callerTypeIdentity,
                    wrappers,
                    roots,
                    knownTypeIdentities);
                var sourceWrapperInvocation = IsSourceWrapperInvocation(
                    call,
                    method,
                    wrappers,
                    knownTypeIdentities,
                    roots);
                if (resolution is not null
                    && sourceWrapperInvocation
                    && (resolution.Candidates.Count == 0
                        || !string.IsNullOrEmpty(resolution.Reason)))
                {
                    invocations.Add(CreateUnavailableSourceCandidate(
                        call,
                        method,
                        callerClass,
                        resolution));
                    continue;
                }
                if (resolution is null || resolution.Candidates.Count == 0)
                {
                    if (AdapterAnalyzer.IsRecognizedAdapterInvocation(call, method))
                        continue;
                    var unavailable = CreateUnavailableCandidate(
                        call,
                        method,
                        callerClass,
                        roots,
                        compilation);
                    if (unavailable is not null)
                        invocations.Add(unavailable);
                    continue;
                }

                if (!resolution.IsUnique)
                {
                    invocations.Add(CreateAmbiguousInvocation(
                        call,
                        method,
                        callerClass,
                        resolution));
                    continue;
                }

                var wrapper = resolution.Candidates[0];

                var mode = ResolveMode(call, wrapper);

                var connectionExpression = ResolveCallConnectionExpression(
                    call,
                    wrapper,
                    method,
                    roots,
                    knownTypeIdentities);
                foreach (var commandTextCandidate in ReadWrapperCommandTextCandidates(
                    call,
                    wrapper,
                    method))
                {
                    invocations.Add(new DirectSqlInvocation(
                        callerClass,
                        method.Identifier.Text,
                        commandTextCandidate.CommandTextKind,
                        commandTextCandidate.CommandText,
                        mode == "stored_procedure",
                        connectionExpression.Expression,
                        call.SpanStart,
                        call.Span.End,
                        "source_wrapper",
                        wrapper.ClassName,
                        wrapper.MethodName,
                        true,
                        wrapper.ReachesStoredProcedureSink,
                        mode,
                        new[] { method.Identifier.Text, wrapper.MethodName },
                        BranchContext: SyntaxBranchAnalyzer.Combine(
                            SyntaxBranchAnalyzer.GetBranchContext(call),
                            commandTextCandidate.BranchContext),
                        WrapperReceiverType: resolution.Binding.ReceiverType,
                        ReceiverType: resolution.Binding.ReceiverType,
                        ReceiverName: resolution.Binding.Expression,
                        CommandTextArgument: commandTextCandidate.ArgumentExpression,
                        CommandTextLiteral: commandTextCandidate.CommandText,
                        TerminalSink: wrapper.TerminalSink,
                        CommandTypeMode: ResolveCommandTypeMode(wrapper),
                        ReceiverExpression: resolution.Binding.Expression,
                        ReceiverImplementationIdentity: resolution.Binding.ImplementationIdentity,
                        ReceiverBindingProvenance: "source",
                        ReceiverConstructionFacts: resolution.Binding.ConstructionFacts,
                        ReceiverAssignmentFacts: resolution.Binding.AssignmentFacts,
                        WrapperImplementationIdentity: wrapper.TypeIdentity,
                        WrapperMethodIdentity: wrapper.MethodIdentity,
                        WrapperMethodArity: wrapper.Parameters.Count,
                        WrapperParameterTypes: wrapper.ParameterTypes,
                        WrapperMethodSemantics: wrapper.MethodSemantics,
                        WrapperTerminalSink: wrapper.TerminalSink,
                        WrapperAssemblyIdentity: wrapper.AssemblyIdentity,
                        WrapperAssemblyRevision: wrapper.AssemblyRevision,
                        WrapperUnresolvedReason: wrapper.UnresolvedReason,
                        ConnectionExpressionCandidates: connectionExpression.Candidates,
                        CommandTextSourceStartOffset: commandTextCandidate.SourceStartOffset,
                        CommandTextSourceEndOffset: commandTextCandidate.SourceEndOffset,
                        CommandTextProvenance: commandTextCandidate.ValueProvenance));
                }
            }
        }

        return invocations;
    }

    internal static List<WrapperDefinition> GetDefinitions(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var roots = AsRootList(sourceRoots);
        if (SameRoots(roots, _definitionsRoots))
            return _definitionsCache!;
        var definitions = GetDefinitions(roots, "", "");
        _definitionsRoots = roots;
        _definitionsCache = definitions;
        return definitions;
    }

    internal static List<WrapperDefinition> GetDefinitions(
        IEnumerable<CompilationUnitSyntax> sourceRoots,
        string assemblyIdentity,
        string assemblyRevision)
    {
        var roots = sourceRoots.ToList();
        var methods = roots
            .SelectMany(sourceRoot => sourceRoot.DescendantNodes().OfType<MethodDeclarationSyntax>())
            .ToList();
        var knownTypeIdentities = GetKnownTypeIdentities(roots);
        return methods
            .Select(method => CreateDefinition(
                method,
                roots,
                knownTypeIdentities,
                assemblyIdentity,
                assemblyRevision))
            .Where(definition => definition is not null)
            .Select(definition => definition!)
            .ToList();
    }

    internal static IReadOnlyList<string> GetKnownTypeIdentities(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var roots = AsRootList(sourceRoots);
        if (SameRoots(roots, _knownTypeIdentitiesRoots))
            return _knownTypeIdentitiesCache!;
        var knownTypeIdentities = ComputeKnownTypeIdentities(roots);
        _knownTypeIdentitiesRoots = roots;
        _knownTypeIdentitiesCache = knownTypeIdentities;
        return knownTypeIdentities;
    }

    private static IReadOnlyList<string> ComputeKnownTypeIdentities(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
        => sourceRoots
            .SelectMany(sourceRoot => sourceRoot.DescendantNodes().OfType<TypeDeclarationSyntax>())
            .Select(CSharpAnalyzer.GetTypeIdentity)
            .Where(typeIdentity => !string.IsNullOrWhiteSpace(typeIdentity))
            .Distinct(StringComparer.Ordinal)
            .ToList();

    /// <summary>
    /// Assigns every public method of a decompiled receiver type one of three states: classified
    /// (<paramref name="definitions"/> holds a <see cref="WrapperDefinition"/> for it), non-database
    /// (its body names no ADO.NET type), or unclassified (its body names an ADO.NET type, but the
    /// Command Source resolver found nothing usable for it). Returns only the unclassified method
    /// identities — the honest signal that the public database behavior surface is incomplete.
    /// </summary>
    /// <param name="root">
    /// The flat, namespace-less <c>class {ReceiverType} {{ ... }}</c> root
    /// <see cref="WrapperAssemblyDecompiler.Decompile"/> builds from one receiver type's own
    /// decompiled methods; only its direct class members are censused, deliberately not
    /// <c>DescendantNodes()</c>, so a compiler-generated nested type a decompiled method body
    /// happens to carry along is never mistaken for a public method of the receiver type itself.
    /// </param>
    internal static IReadOnlyList<string> GetUnclassifiedPublicMethods(
        CompilationUnitSyntax root,
        IReadOnlyList<WrapperDefinition> definitions)
    {
        var knownTypeIdentities = GetKnownTypeIdentities(new[] { root });
        var classifiedIdentities = definitions
            .Select(definition => definition.MethodIdentity)
            .Where(identity => !string.IsNullOrWhiteSpace(identity))
            .ToHashSet(StringComparer.Ordinal);

        var unclassified = new List<string>();
        foreach (var classDeclaration in root.Members.OfType<ClassDeclarationSyntax>())
        {
            foreach (var method in classDeclaration.Members.OfType<MethodDeclarationSyntax>())
            {
                if (!method.Modifiers.Any(modifier => modifier.IsKind(SyntaxKind.PublicKeyword)))
                    continue;
                // Blank only when the class itself has no resolvable identity; nothing durable
                // to name the method by, so it is left out rather than reported under a
                // fabricated blank-prefixed identity.
                var methodIdentity = GetMethodIdentity(method, knownTypeIdentities);
                if (methodIdentity is null || classifiedIdentities.Contains(methodIdentity))
                    continue;
                if (!method.DescendantNodes().OfType<TypeSyntax>().Any(CSharpAnalyzer.IsAdoNetType))
                    continue;
                unclassified.Add(methodIdentity);
            }
        }
        return unclassified.Distinct(StringComparer.Ordinal).ToList();
    }

    private static (ExpressionSyntax? Argument, string? Literal) ResolveCommandTextArgument(
        InvocationExpressionSyntax call,
        IReadOnlyList<WrapperDefinition> candidates)
    {
        var arguments = candidates
            .Select(candidate => ResolveInvocationArgument(
                call,
                candidate.Parameters,
                candidate.CommandTextParameterIndex))
            .Where(argument => argument is not null)
            .GroupBy(argument => argument!.ToString(), StringComparer.Ordinal)
            .Select(group => group.First()!)
            .ToList();
        if (arguments.Count == 1)
        {
            var argument = arguments[0];
            return (
                argument,
                argument is LiteralExpressionSyntax { Token.Value: string text }
                    ? text
                    : null);
        }

        var literals = candidates
            .Select(candidate => candidate.CommandTextLiteral)
            .Where(literal => !string.IsNullOrWhiteSpace(literal))
            .Distinct(StringComparer.Ordinal)
            .ToList();
        return literals.Count == 1 ? (null, literals[0]) : (null, null);
    }

    /// <summary>Each unresolved/ambiguous overload candidate's own bound-implementation and signature facts.</summary>
    private static List<WrapperOverloadCandidateFact> BuildOverloadCandidateFacts(
        WrapperResolution resolution)
        => resolution.Candidates
            .Select(candidate => new WrapperOverloadCandidateFact(
                candidate.TypeIdentity,
                resolution.Binding.ReceiverType,
                candidate.MethodName,
                candidate.Parameters.Count,
                candidate.ParameterTypes,
                candidate.MethodIdentity))
            .DistinctBy(fact => fact.MethodIdentity, StringComparer.Ordinal)
            .ToList();

    private static DirectSqlInvocation CreateUnavailableSourceCandidate(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        string callerClass,
        WrapperResolution resolution)
    {
        var methodName = call.Expression switch
        {
            MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            _ => "",
        };
        var commandTextResolution = ResolveCommandTextArgument(call, resolution.Candidates);
        var commandText = commandTextResolution.Argument;
        var literalText = commandTextResolution.Literal;
        var commandTextKind = literalText is not null ? "literal" : "dynamic";
        var candidateFacts = BuildOverloadCandidateFacts(resolution);
        var selectedCandidate = resolution.Candidates.Count == 1
            ? resolution.Candidates[0]
            : null;
        return new DirectSqlInvocation(
            callerClass,
            caller.Identifier.Text,
            commandTextKind,
            literalText,
            false,
            null,
            call.SpanStart,
            call.Span.End,
            "source_wrapper",
            selectedCandidate?.ClassName,
            methodName,
            true,
            false,
            "unknown",
            new[] { caller.Identifier.Text, methodName },
            SyntaxBranchAnalyzer.GetBranchContext(call),
            resolution.Binding.ReceiverType,
            resolution.Binding.ReceiverType,
            resolution.Binding.Expression,
            commandText?.ToString().Trim(),
            literalText,
            selectedCandidate?.TerminalSink,
            "unknown",
            resolution.Binding.Expression,
            resolution.Binding.ImplementationIdentity,
            selectedCandidate?.AssemblyIdentity,
            selectedCandidate?.AssemblyRevision,
            "source",
            resolution.Binding.ConstructionFacts,
            resolution.Binding.AssignmentFacts,
            selectedCandidate?.TypeIdentity,
            selectedCandidate?.AssemblyIdentity,
            selectedCandidate?.AssemblyRevision,
            selectedCandidate?.MethodIdentity,
            selectedCandidate?.Parameters.Count,
            selectedCandidate?.ParameterTypes,
            "unresolved",
            selectedCandidate?.TerminalSink,
            candidateFacts,
            WrapperUnresolvedReason: resolution.Reason);
    }

    private static DirectSqlInvocation? CreateUnavailableCandidate(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        string callerClass,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        CSharpCompilation? compilation)
    {
        if (call.Expression is not MemberAccessExpressionSyntax member)
            return null;

        var commandText = ResolveExternalCommandTextArgument(call);
        if (!LooksLikeCommandTextExpression(commandText, caller))
            return null;

        var mode = ResolveExternalSqlObjectMode(call, caller);
        var literalText = commandText is LiteralExpressionSyntax { Token.Value: string text }
            ? text
            : null;
        var boundSymbol = TryResolveBoundWrapperSymbol(call, compilation);

        return CreateUnavailableInvocation(
            caller,
            callerClass,
            member,
            literalText is null ? "dynamic" : "literal",
            literalText,
            mode == "stored_procedure",
            mode,
            call,
            boundSymbol,
            ResolveWrapperReceiverType(call, caller, boundSymbol, sourceRoots));
    }

    /// <summary>The receiver type one external wrapper call is keyed on, and where that answer
    /// came from. A blank <see cref="ReceiverType"/> is not an answer; the
    /// <see cref="Provenance"/> beside it says which absence it is.</summary>
    private sealed record ResolvedReceiverType(string? ReceiverType, string Provenance)
    {
        /// <summary>The syntax resolved no receiver type at all, so no new rule applied.</summary>
        internal static readonly ResolvedReceiverType None = new(null, "");

        /// <summary>The compiler named the type that declares the invoked method.</summary>
        internal static ResolvedReceiverType Declaring(string typeName)
            => new(typeName, "declaring_type");

        /// <summary>The receiver's own declared type declares the method, so it is the
        /// declaring type -- the answer this analyzer has always given.</summary>
        internal static ResolvedReceiverType ReceiverDeclaration(string typeName)
            => new(typeName, "receiver_declaration");

        /// <summary>A receiver type resolved, but it inherits the invoked method from a base
        /// this analysis cannot see, so which type declares it is unknown.</summary>
        internal static readonly ResolvedReceiverType Unresolved =
            new(null, "declaring_type_unresolved");
    }

    /// <summary>
    /// The receiver type one external wrapper call is keyed on.
    ///
    /// A Contract is keyed on the type that *declares* the invoked method, not on the type the
    /// receiver happens to be declared as. Every measured ASP.NET Core repository writes its
    /// data access as a local database context deriving from a base class in a shared external
    /// library, with the wrapper method declared on the base: keying on the local subclass
    /// matches no Contract, and the call is never recognised as a wrapper invocation at all.
    ///
    /// The rule only ever walks *from* a receiver type the syntax already resolved. Where none
    /// resolved -- `Path.Combine`, `File.Exists`, a static call on a type this method never sees
    /// declared -- nothing is reported, exactly as before. Filling those in would silently
    /// invalidate every reviewed wrapper exclusion keyed on an empty receiver type, which is a
    /// triage decision no analyzer change may quietly overturn.
    /// </summary>
    private static ResolvedReceiverType ResolveWrapperReceiverType(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        BoundWrapperSymbolFacts? boundSymbol,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        var declaredReceiverType = ResolveExternalReceiverType(call, caller);
        if (string.IsNullOrWhiteSpace(declaredReceiverType))
            return ResolvedReceiverType.None;

        if (!string.IsNullOrWhiteSpace(boundSymbol?.DeclaringTypeName))
            return ResolvedReceiverType.Declaring(boundSymbol!.DeclaringTypeName);

        var methodName = call.Expression is MemberAccessExpressionSyntax member
            ? member.Name.Identifier.Text
            : "";
        return InheritsTheInvokedMethod(declaredReceiverType, methodName, sourceRoots)
            ? ResolvedReceiverType.Unresolved
            : ResolvedReceiverType.ReceiverDeclaration(declaredReceiverType);
    }

    /// <summary>
    /// True when the corpus declares <paramref name="receiverType"/>, that declaration derives
    /// from something, and no part of it declares <paramref name="methodName"/> -- so the
    /// invoked method is inherited from a base this analysis cannot see, and the receiver's own
    /// type is not the type that declares it.
    ///
    /// A type the corpus does not declare at all is left alone: it is the external wrapper type
    /// itself, and reporting it is the answer this analyzer has always given.
    ///
    /// The lookup is by simple name, because a receiver's declared type arrives as bare source
    /// text with no namespace to qualify it. Two same-named types in different namespaces
    /// therefore share one bucket, and this errs deliberately in the safe direction: an
    /// unrelated namesake declaring the method makes this return false, which falls back to the
    /// answer the analyzer gave before this rule existed. A collision can cost the new rule, it
    /// can never make an answer worse than the old one.
    /// </summary>
    private static bool InheritsTheInvokedMethod(
        string receiverType,
        string methodName,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots)
    {
        if (string.IsNullOrEmpty(methodName))
            return false;
        var declarations = GetTypeDeclarationsByName(sourceRoots, receiverType.Trim());
        if (declarations.Count == 0)
            return false;
        if (declarations.Any(declaration => declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Any(method => method.Identifier.Text == methodName)))
            return false;
        return declarations.Any(declaration => declaration.BaseList is not null);
    }

    // Symbol acceptance rule (ticket 06): accept a bound method symbol only when the compiler
    // returned one resolved symbol and returned no candidate set. A non-empty candidate set
    // means overload resolution could not choose between two or more methods -- that is exactly
    // the ambiguity this system refuses to guess through, so it is treated the same as no
    // symbol at all, and the call falls back to the argument-count path unchanged. Whether the
    // bound symbol's own assembly matches the one the contract records is a decision for the
    // Python gateway, which is where the contract actually lives; this only reports the bound
    // symbol's own facts.
    private static BoundWrapperSymbolFacts? TryResolveBoundWrapperSymbol(
        InvocationExpressionSyntax call,
        CSharpCompilation? compilation)
    {
        if (compilation is null || !compilation.ContainsSyntaxTree(call.SyntaxTree))
            return null;

        var semanticModel = compilation.GetSemanticModel(call.SyntaxTree);
        var symbolInfo = semanticModel.GetSymbolInfo(call);
        if (symbolInfo.Symbol is not IMethodSymbol method || !symbolInfo.CandidateSymbols.IsEmpty)
            return null;

        var parameterTypes = method.Parameters
            .Select(parameter => parameter.Type.ToDisplayString(BoundParameterTypeFormat))
            .ToList();
        var methodIdentity = $"{method.ContainingType.Name}.{method.Name}({string.Join(",", parameterTypes)})";
        var assemblyIdentity = ResolveBoundAssemblyIdentity(compilation, method.ContainingAssembly);

        // The containing type of the resolved symbol is the type that *declares* the method:
        // for a call on a subclass that does not override it, the compiler resolves the base's
        // own symbol, which is exactly the type a Contract must be keyed on. Reported by simple
        // name, the shape the syntactic path has always reported and the shape a Contract's
        // `receiver_types` records.
        return new BoundWrapperSymbolFacts(
            methodIdentity,
            parameterTypes,
            assemblyIdentity,
            method.ContainingType.Name);
    }

    private static readonly SymbolDisplayFormat BoundParameterTypeFormat = new(
        globalNamespaceStyle: SymbolDisplayGlobalNamespaceStyle.Omitted,
        typeQualificationStyle: SymbolDisplayTypeQualificationStyle.NameAndContainingTypesAndNamespaces,
        miscellaneousOptions: SymbolDisplayMiscellaneousOptions.UseSpecialTypes);

    private static string? ResolveBoundAssemblyIdentity(CSharpCompilation compilation, IAssemblySymbol assembly)
    {
        if (compilation.GetMetadataReference(assembly) is not PortableExecutableReference
            {
                FilePath: { } path,
            }
            || !File.Exists(path))
            return null;
        try
        {
            return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static ExpressionSyntax? ResolveExternalCommandTextArgument(
        InvocationExpressionSyntax call)
    {
        var named = call.ArgumentList.Arguments.FirstOrDefault(argument =>
            argument.NameColon?.Name.Identifier.Text.Equals(
                "commandText",
                StringComparison.OrdinalIgnoreCase) is true);
        return named?.Expression
            ?? call.ArgumentList.Arguments.ElementAtOrDefault(0)?.Expression;
    }

    private static DirectSqlInvocation CreateUnavailableInvocation(
        MethodDeclarationSyntax caller,
        string callerClass,
        MemberAccessExpressionSyntax member,
        string commandTextKind,
        string? commandText,
        bool commandTypeStoredProcedure,
        string mode,
        InvocationExpressionSyntax call,
        BoundWrapperSymbolFacts? boundSymbol,
        ResolvedReceiverType receiverType)
        => new(
            callerClass,
            caller.Identifier.Text,
            commandTextKind,
            commandText,
            commandTypeStoredProcedure,
            member.Expression.ToString().Trim(),
            call.SpanStart,
            call.Span.End,
            "source_wrapper",
            null,
            member.Name.Identifier.Text,
            false,
            false,
            mode,
            new[] { caller.Identifier.Text, member.Name.Identifier.Text },
            WrapperReceiverType: receiverType.ReceiverType,
            WrapperMethodArity: call.ArgumentList.Arguments.Count,
            WrapperMethodIdentity: boundSymbol?.MethodIdentity,
            WrapperParameterTypes: boundSymbol?.ParameterTypes,
            WrapperAssemblyIdentity: boundSymbol?.AssemblyIdentity,
            WrapperReceiverTypeProvenance: receiverType.Provenance,
            CommandTypeArgumentObserved: HasModeLiteralArgument(call));

    /// <summary>One externally referenced wrapper call's uniquely bound method symbol facts —
    /// only ever built when the compiler resolved the call to exactly one method with no
    /// candidate set (see <see cref="TryResolveBoundWrapperSymbol"/>).</summary>
    private sealed record BoundWrapperSymbolFacts(
        string MethodIdentity,
        IReadOnlyList<string> ParameterTypes,
        string? AssemblyIdentity,
        string DeclaringTypeName);

    private static string? ResolveExternalReceiverType(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller)
    {
        if (call.Expression is not MemberAccessExpressionSyntax member)
            return null;

        var receiverName = member.Expression switch
        {
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax, Name: var name } => name.Identifier.Text,
            _ => null,
        };
        if (string.IsNullOrEmpty(receiverName))
            return null;

        foreach (var declaration in caller.DescendantNodes().OfType<VariableDeclarationSyntax>())
        {
            var variable = declaration.Variables.FirstOrDefault(item => item.Identifier.Text == receiverName);
            if (variable is null)
                continue;
            if (!declaration.Type.ToString().Equals("var", StringComparison.Ordinal))
                return declaration.Type.ToString();
            if (variable.Initializer?.Value is ObjectCreationExpressionSyntax creation)
                return creation.Type.ToString();
        }

        var parameter = caller.ParameterList.Parameters
            .FirstOrDefault(item => item.Identifier.Text == receiverName);
        if (parameter?.Type is not null)
            return parameter.Type.ToString();

        var containingClass = caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        if (containingClass is null)
            return null;

        var field = containingClass.DescendantNodes()
            .OfType<FieldDeclarationSyntax>()
            .FirstOrDefault(item => item.Declaration.Variables.Any(variable => variable.Identifier.Text == receiverName));
        if (field is not null)
            return field.Declaration.Type.ToString();

        return containingClass.DescendantNodes()
            .OfType<PropertyDeclarationSyntax>()
            .FirstOrDefault(item => item.Identifier.Text == receiverName)
            ?.Type.ToString();
    }

    private static string ResolveExternalSqlObjectMode(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller)
    {
        if (call.Expression is not MemberAccessExpressionSyntax member)
            return "unknown";

        var methodName = member.Name.Identifier.Text;
        if (methodName.Equals("ExeProcRead", StringComparison.OrdinalIgnoreCase)
            || methodName.Equals("ExeProcNon", StringComparison.OrdinalIgnoreCase))
            return "stored_procedure";
        if (methodName.Equals("CreateReader", StringComparison.OrdinalIgnoreCase)
            || methodName.Equals("GetFirstValue", StringComparison.OrdinalIgnoreCase))
            return "inline_sql";
        if (methodName.Equals("CreateTable", StringComparison.OrdinalIgnoreCase)
            || methodName.Equals("CreateDataSet", StringComparison.OrdinalIgnoreCase))
        {
            var resolvedMode = ResolveUnknownCallMode(call, caller);
            return resolvedMode != "unknown"
                ? resolvedMode
                : HasDynamicSqlObjectModeArgument(call, caller)
                    ? "unknown"
                    : "inline_sql";
        }
        return ResolveUnknownCallMode(call, caller);
    }

    private static bool HasDynamicSqlObjectModeArgument(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller)
    {
        var commandTextExpression = ResolveExternalCommandTextArgument(call);
        return call.ArgumentList.Arguments
            .Where(argument => commandTextExpression is null
                || argument.Expression.SpanStart != commandTextExpression.SpanStart)
            .Any(argument =>
                argument.NameColon?.Name.Identifier.Text.Equals(
                    "mode",
                    StringComparison.OrdinalIgnoreCase) is true
                || argument.Expression is InterpolatedStringExpressionSyntax
                || argument.Expression is IdentifierNameSyntax identifier
                    && IsStringIdentifier(identifier.Identifier.Text, caller)
                || argument.Expression is MemberAccessExpressionSyntax member
                    && IsStringMember(member, caller));
    }

    private static string ResolveUnknownCallMode(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller)
    {
        var commandTextExpression = ResolveExternalCommandTextArgument(call);
        if (!LooksLikeCommandTextExpression(commandTextExpression, caller))
            return "unknown";

        var hasStoredMode = call.ArgumentList.Arguments.Any(argument => IsStoredModeLiteral(argument.Expression));
        var hasInlineMode = call.ArgumentList.Arguments.Any(argument => IsInlineModeLiteral(argument.Expression));
        if (hasStoredMode)
            return "stored_procedure";
        if (hasInlineMode)
            return "inline_sql";
        return "unknown";
    }

    private static bool LooksLikeCommandTextExpression(
        ExpressionSyntax? expression,
        MethodDeclarationSyntax caller)
    {
        return expression switch
        {
            LiteralExpressionSyntax { Token.Value: string } => true,
            InterpolatedStringExpressionSyntax => true,
            IdentifierNameSyntax identifier => IsStringIdentifier(identifier.Identifier.Text, caller),
            MemberAccessExpressionSyntax member => IsStringMember(member, caller),
            ConditionalExpressionSyntax conditional =>
                LooksLikeCommandTextExpression(conditional.WhenTrue, caller)
                && LooksLikeCommandTextExpression(conditional.WhenFalse, caller),
            _ => false,
        };
    }

    private static bool IsStringIdentifier(string identifierName, MethodDeclarationSyntax caller)
    {
        foreach (var declaration in caller.DescendantNodes().OfType<VariableDeclarationSyntax>())
        {
            var variable = declaration.Variables.FirstOrDefault(
                item => item.Identifier.Text == identifierName);
            if (variable is null)
                continue;
            if (IsStringType(declaration.Type))
                return true;
            if (declaration.Type.ToString().Equals("var", StringComparison.Ordinal)
                && IsStringValueExpression(variable.Initializer?.Value))
                return true;
        }

        var parameter = caller.ParameterList.Parameters.FirstOrDefault(
            item => item.Identifier.Text == identifierName);
        if (parameter?.Type is not null && IsStringType(parameter.Type))
            return true;

        return IsStringMemberName(identifierName, caller);
    }

    private static bool IsStringMember(MemberAccessExpressionSyntax member, MethodDeclarationSyntax caller)
        => member.Expression is ThisExpressionSyntax
            && IsStringMemberName(member.Name.Identifier.Text, caller);

    private static bool IsStringMemberName(string memberName, MethodDeclarationSyntax caller)
    {
        var containingClass = caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        if (containingClass is null)
            return false;

        var field = containingClass.DescendantNodes()
            .OfType<FieldDeclarationSyntax>()
            .FirstOrDefault(item => item.Declaration.Variables.Any(
                variable => variable.Identifier.Text == memberName));
        if (field is not null && IsStringType(field.Declaration.Type))
            return true;

        var property = containingClass.DescendantNodes()
            .OfType<PropertyDeclarationSyntax>()
            .FirstOrDefault(item => item.Identifier.Text == memberName);
        return property is not null && IsStringType(property.Type);
    }

    private static bool IsStringValueExpression(ExpressionSyntax? expression)
        => expression is LiteralExpressionSyntax { Token.Value: string }
            || expression is InterpolatedStringExpressionSyntax;

    private static bool IsStringType(TypeSyntax type)
    {
        var typeName = type.ToString().Trim().TrimEnd('?');
        return typeName.Equals("string", StringComparison.Ordinal)
            || typeName.Equals("String", StringComparison.Ordinal)
            || typeName.EndsWith(".String", StringComparison.Ordinal);
    }

    /// <summary>True when this call really passes a command-type mode literal.
    /// `WrapperMode` cannot answer that: it is also set from the method name alone
    /// (ExeProcRead, CreateReader, ...) and falls back to inline_sql when no mode
    /// argument is found at all, so a reader of WrapperMode cannot tell a mode that
    /// was observed from one that was assumed.</summary>
    private static bool HasModeLiteralArgument(InvocationExpressionSyntax call)
        => call.ArgumentList.Arguments.Any(argument =>
            IsStoredModeLiteral(argument.Expression)
            || IsInlineModeLiteral(argument.Expression));

    private static bool IsStoredModeLiteral(ExpressionSyntax expression)
        => expression is LiteralExpressionSyntax literal
            && (literal.IsKind(SyntaxKind.TrueLiteralExpression)
                || literal.Token.Value is string text
                && (text.Equals("SP", StringComparison.OrdinalIgnoreCase)
                    || text.Equals("StoredProcedure", StringComparison.OrdinalIgnoreCase)));

    private static bool IsInlineModeLiteral(ExpressionSyntax expression)
        => expression is LiteralExpressionSyntax literal
            && (literal.IsKind(SyntaxKind.FalseLiteralExpression)
                || literal.Token.Value is string text
                && (text.Equals("SQL", StringComparison.OrdinalIgnoreCase)
                    || text.Equals("Text", StringComparison.OrdinalIgnoreCase)
                    || text.Equals("Inline", StringComparison.OrdinalIgnoreCase)));

    private static bool LooksLikeInlineSql(string text)
        => SqlTextClassifier.LooksLikeInlineSql(text);

    private static bool LooksLikeProcedureName(string text)
    {
        var bare = text.Trim().Replace("[", "").Replace("]", "").Split('.').Last();
        return bare.StartsWith("sp", StringComparison.OrdinalIgnoreCase)
            || bare.StartsWith("usp", StringComparison.OrdinalIgnoreCase)
            || bare.StartsWith("proc", StringComparison.OrdinalIgnoreCase);
    }

    private sealed record ReceiverBinding(
        string Expression,
        string ReceiverType,
        string ImplementationIdentity,
        IReadOnlyList<string> CandidateImplementations,
        IReadOnlyList<string> ConstructionFacts,
        IReadOnlyList<string> AssignmentFacts)
    {
        internal bool IsAmbiguous => CandidateImplementations.Count > 1;
    }

    private sealed record WrapperResolution(
        IReadOnlyList<WrapperDefinition> Candidates,
        ReceiverBinding Binding,
        string Reason = "")
    {
        internal bool IsUnique
            => Candidates.Count == 1
            && !Binding.IsAmbiguous
            && string.IsNullOrEmpty(Reason);
    }

    /// <summary>
    /// The construct that supplies one wrapper method's command text and terminal sink.
    /// </summary>
    /// <param name="Creation">The construction the rule recognized.</param>
    /// <param name="VariableName">The variable the construction is bound to, if any.</param>
    /// <param name="CommandPropertyReceiver">
    /// The receiver text whose <c>CommandText</c>/<c>CommandType</c>/<c>Connection</c> assignments
    /// govern this Command Source. Empty when the construction is bound to no variable.
    /// </param>
    /// <param name="PropertyInitializerOwner">
    /// The construction whose object initializer sets command properties, if any.
    /// </param>
    /// <param name="ResolveTerminalSinks">
    /// This Command Source's own terminal sink calls within the method. Each rule brings its own,
    /// so recognizing a further construct never reaches back into the classification flow.
    /// </param>
    private sealed record CommandSource(
        ObjectCreationExpressionSyntax Creation,
        string? VariableName,
        string CommandPropertyReceiver,
        ObjectCreationExpressionSyntax? PropertyInitializerOwner,
        Func<MethodDeclarationSyntax, IReadOnlyList<InvocationExpressionSyntax>> ResolveTerminalSinks);

    /// <summary>
    /// Resolves the Command Sources of one method. Every construct that can supply a command text
    /// and a terminal sink is recognized by exactly one rule in <see cref="Rules"/>; a further
    /// construct is one added entry there, not a change to the classification flow around it.
    /// </summary>
    private static class CommandSourceResolver
    {
        private static readonly IReadOnlyList<Func<MethodDeclarationSyntax, IEnumerable<CommandSource>>> Rules
            = new Func<MethodDeclarationSyntax, IEnumerable<CommandSource>>[]
            {
                ResolveCommandObjectSources,
                ResolveDataAdapterSources,
            };

        internal static IReadOnlyList<CommandSource> Resolve(MethodDeclarationSyntax method)
            => Rules
                .SelectMany(rule => rule(method))
                .OrderBy(source => source.Creation.SpanStart)
                .ToList();

        /// <summary>An explicit command object construction, e.g. <c>new SqlCommand(sql, conn)</c>.</summary>
        private static IEnumerable<CommandSource> ResolveCommandObjectSources(MethodDeclarationSyntax method)
            => method.DescendantNodes()
                .OfType<ObjectCreationExpressionSyntax>()
                .Where(creation => CSharpAnalyzer.IsSqlCommandType(creation.Type))
                .Select(creation =>
                {
                    var variable = ResolveVariableName(creation);
                    return new CommandSource(
                        creation,
                        variable,
                        variable ?? "",
                        creation,
                        method => variable is null
                            ? Array.Empty<InvocationExpressionSyntax>()
                            : ResolveCommandTerminalSinkInvocations(method, variable));
                });

        /// <summary>
        /// A data adapter construction that takes a command text argument and a connection
        /// argument, e.g. <c>new SqlDataAdapter(sql, conn)</c>. An adapter built from an existing
        /// command object is not a Command Source of its own: the command object rule covers it.
        /// </summary>
        private static IEnumerable<CommandSource> ResolveDataAdapterSources(MethodDeclarationSyntax method)
        {
            foreach (var creation in method.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            {
                if (!CSharpAnalyzer.IsDataAdapterType(creation.Type))
                    continue;
                // Every two-argument adapter constructor takes a command text and a connection;
                // the one-argument form takes a command object, which rule 1 already covers.
                var arguments = creation.ArgumentList?.Arguments;
                if (arguments is not { Count: 2 })
                    continue;
                // Stated rather than left to the arity above, so the rule that an existing command
                // object never yields a second Command Source holds for any adapter type.
                if (CSharpAnalyzer.IsSqlCommandExpression(arguments.Value[0].Expression, method))
                    continue;
                var variable = ResolveVariableName(creation);
                if (variable is null)
                    continue;
                yield return new CommandSource(
                    creation,
                    variable,
                    // An adapter has no CommandType of its own; the mode is whatever the method
                    // assigns to the command the adapter built for itself.
                    $"{variable}.SelectCommand",
                    null,
                    method => ResolveAdapterFillInvocations(method, variable));
            }
        }
    }

    private static WrapperDefinition? CreateDefinition(
        MethodDeclarationSyntax method,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        IReadOnlyCollection<string> knownTypeIdentities,
        string assemblyIdentity = "",
        string assemblyRevision = "")
    {
        var commandSources = CommandSourceResolver.Resolve(method);
        var commandSource = commandSources.FirstOrDefault();
        if (commandSource is null)
            return null;

        var commandVariable = commandSource.VariableName;
        if (commandVariable is null)
            return null;

        var commandTypeAssignments = GetCommandPropertyAssignments(
            method,
            commandSource,
            "CommandType");
        var terminalSinkInvocations = commandSource.ResolveTerminalSinks(method);
        if (terminalSinkInvocations.Count > 0)
        {
            commandTypeAssignments = commandTypeAssignments
                .Where(assignment => terminalSinkInvocations.Any(sink =>
                    assignment.SpanStart < sink.SpanStart
                    && (SyntaxBranchAnalyzer.IsCompatible(
                            SyntaxBranchAnalyzer.GetBranchContext(assignment),
                            SyntaxBranchAnalyzer.GetBranchContext(sink))
                        || SyntaxBranchAnalyzer.IsCompatible(
                            SyntaxBranchAnalyzer.GetBranchContext(sink),
                            SyntaxBranchAnalyzer.GetBranchContext(assignment)))))
                .ToList();
        }
        var classDeclaration = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        var className = classDeclaration?.Identifier.Text ?? "";
        var typeIdentity = CSharpAnalyzer.GetTypeIdentity(classDeclaration);
        var classDeclarations = GetClassDeclarations(sourceRoots, typeIdentity).ToList();
        if (classDeclaration is not null && !classDeclarations.Contains(classDeclaration))
            classDeclarations.Add(classDeclaration);
        var parameters = method.ParameterList.Parameters.Select(parameter => parameter.Identifier.Text).ToList();
        var parameterTypes = ResolveParameterTypes(method, knownTypeIdentities);
        var requiredParameterCount = method.ParameterList.Parameters.Count(parameter =>
            parameter.Default is null
            && !parameter.Modifiers.Any(modifier => modifier.IsKind(SyntaxKind.ParamsKeyword)));
        var commandTextExpression = commandSource.Creation.ArgumentList?.Arguments
            .ElementAtOrDefault(0)?.Expression;
        var connectionExpression = commandSource.Creation.ArgumentList?.Arguments
            .ElementAtOrDefault(1)?.Expression?.ToString().Trim();
        var commandTextAssignments = GetCommandPropertyAssignments(
            method,
            commandSource,
            "CommandText");
        if (terminalSinkInvocations.Count > 0)
        {
            commandTextAssignments = commandTextAssignments
                .Where(assignment => terminalSinkInvocations.Any(sink =>
                    assignment.SpanStart < sink.SpanStart
                    && (SyntaxBranchAnalyzer.IsCompatible(
                            SyntaxBranchAnalyzer.GetBranchContext(assignment),
                            SyntaxBranchAnalyzer.GetBranchContext(sink))
                        || SyntaxBranchAnalyzer.IsCompatible(
                            SyntaxBranchAnalyzer.GetBranchContext(sink),
                            SyntaxBranchAnalyzer.GetBranchContext(assignment)))))
                .ToList();
        }
        foreach (var assignment in commandTextAssignments)
        {
            commandTextExpression = assignment.Right;
        }
        foreach (var assignment in GetCommandPropertyAssignments(
            method,
            commandSource,
            "Connection"))
        {
            connectionExpression = assignment.Right.ToString().Trim();
        }

        var commandTextParameter = ResolveCommandTextParameterName(
            commandTextExpression,
            parameters);
        var commandTextParameterIndex = parameters.IndexOf(commandTextParameter ?? "");
        var modeParameter = FindModeParameter(method, commandTypeAssignments, parameters);
        var modeParameterIndex = parameters.IndexOf(modeParameter ?? "");
        var methodSemantics = commandSources.Count > 1
            ? "unresolved"
            : ResolveMethodSemantics(commandTypeAssignments, modeParameter);
        var terminalSink = commandSources.Count > 1
            ? null
            : ResolveTerminalSinkName(method, commandSource);
        var unresolvedReason = commandSources.Count > 1
            ? "multiple_sql_commands"
            : null;
        var constructorConnectionParameterIndex = FindConstructorConnectionParameterIndex(
            classDeclarations,
            connectionExpression);
        var methodIdentity = BuildMethodIdentity(typeIdentity, method.Identifier.Text, parameterTypes);

        return new WrapperDefinition(
            typeIdentity,
            className,
            method.Identifier.Text,
            parameters,
            parameterTypes,
            requiredParameterCount,
            commandTextParameterIndex,
            modeParameterIndex,
            connectionExpression,
            methodSemantics == "fixed_stored_procedure",
            terminalSink is not null,
            terminalSink,
            constructorConnectionParameterIndex,
            methodIdentity,
            methodSemantics,
            commandTextExpression is LiteralExpressionSyntax { Token.Value: string literal }
                ? literal
                : null,
            assemblyIdentity,
            assemblyRevision,
            unresolvedReason,
            DeclaresConnectionAsLocal: DeclaresConnectionAsLocal(method, connectionExpression),
            SourceFilePath: method.SyntaxTree?.FilePath ?? "");
    }

    /// <summary>
    /// True when <paramref name="connectionExpression"/> -- already known to name the
    /// method's connection -- is declared as a local of that method, rather than reaching it
    /// as a parameter, a field, or a constructor argument. Such a connection is the wrapper's
    /// own: every caller reaches whatever database it opens.
    /// </summary>
    private static bool DeclaresConnectionAsLocal(
        MethodDeclarationSyntax method,
        string? connectionExpression)
    {
        var connectionName = connectionExpression?.Trim();
        if (string.IsNullOrEmpty(connectionName))
            return false;
        if (method.ParameterList.Parameters.Any(
                parameter => parameter.Identifier.Text == connectionName))
            return false;
        return method.DescendantNodes()
            .OfType<VariableDeclaratorSyntax>()
            .Any(variable => variable.Identifier.Text == connectionName);
    }

    private static string? ResolveCommandTextParameterName(
        ExpressionSyntax? expression,
        IReadOnlyList<string> parameters)
    {
        var identifier = expression switch
        {
            IdentifierNameSyntax direct => direct.Identifier.Text,
            InvocationExpressionSyntax
            {
                Expression: MemberAccessExpressionSyntax
                {
                    Expression: IdentifierNameSyntax receiver,
                    Name.Identifier.Text: "ToString",
                },
            } => receiver.Identifier.Text,
            _ => null,
        };
        return identifier is not null && parameters.Contains(identifier)
            ? identifier
            : null;
    }

    // Binding placeholder for a call whose method name matches no wrapper at all: every caller
    // of ResolveDefinition either re-derives its own empty methodName filter and returns before
    // touching .Binding (IsSourceWrapperInvocation), reads only .Candidates
    // (ComputeUsedWrapperMethodIdentities), or ignores the resolution and rebuilds its own
    // receiver facts (WrapperAnalyzer.Analyze's CreateUnavailableCandidate) -- so this value is
    // never actually read, only cheaply constructed once.
    private static readonly ReceiverBinding NoMatchingWrapperMethodBinding = new(
        "", "", "", Array.Empty<string>(), Array.Empty<string>(), Array.Empty<string>());

    private static WrapperResolution? ResolveDefinition(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        string callerTypeIdentity,
        IReadOnlyList<WrapperDefinition> wrappers,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        var methodName = call.Expression switch
        {
            MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            _ => "",
        };
        if (string.IsNullOrEmpty(methodName))
            return null;

        // Almost every call site in a corpus names no wrapper method at all, so check that
        // cheap name filter before paying for ResolveReceiverBinding's walk of the caller's
        // locals/fields/assignments (and, for a class member, every partial-class declaration
        // sharing its type identity) -- a walk whose result no caller would even look at here.
        var methodCandidates = wrappers
            .Where(wrapper => wrapper.MethodName == methodName)
            .ToList();
        if (methodCandidates.Count == 0)
            return new WrapperResolution(Array.Empty<WrapperDefinition>(), NoMatchingWrapperMethodBinding);

        var binding = call.Expression is MemberAccessExpressionSyntax memberAccess
            ? ResolveReceiverBinding(
                memberAccess.Expression,
                caller,
                call.SpanStart,
                sourceRoots,
                knownTypeIdentities)
            : new ReceiverBinding(
                "this",
                callerTypeIdentity,
                callerTypeIdentity,
                string.IsNullOrEmpty(callerTypeIdentity)
                    ? Array.Empty<string>()
                    : new[] { callerTypeIdentity },
                Array.Empty<string>(),
                Array.Empty<string>());
        if (binding.CandidateImplementations.Count == 0)
            return new WrapperResolution(
                Array.Empty<WrapperDefinition>(),
                binding,
                "receiver_binding_unresolved");

        var candidates = methodCandidates
            .Where(wrapper => binding.CandidateImplementations.Contains(
                wrapper.TypeIdentity,
                StringComparer.Ordinal))
            .ToList();
        if (candidates.Count == 0)
            return new WrapperResolution(
                Array.Empty<WrapperDefinition>(),
                binding,
                "implementation_not_found");

        var argumentCount = call.ArgumentList.Arguments.Count;
        // The same admissibility rule the contract path applies to an external
        // wrapper, in `csharp_analysis_gateway._candidate_admits_arity`. What
        // follows diverges deliberately: here the call site's argument types are
        // in hand, so the tie-break is by type; the contract path has only the
        // registry, so it breaks the tie by Mode Argument Carriage instead.
        var matchingArity = candidates
            .Where(wrapper => wrapper.RequiredParameterCount <= argumentCount
                && argumentCount <= wrapper.Parameters.Count)
            .ToList();
        if (matchingArity.Count == 0)
            return new WrapperResolution(candidates, binding, "overload_not_found");
        candidates = matchingArity;

        var allArgumentTypesKnown = call.ArgumentList.Arguments
            .Select(argument => InferArgumentType(
                argument.Expression,
                caller,
                call.SpanStart,
                knownTypeIdentities))
            .All(type => !string.IsNullOrEmpty(type));
        if (allArgumentTypesKnown)
        {
            var matchingParameterTypes = candidates
                .Where(wrapper =>
                {
                    var arguments = MapInvocationArguments(call, wrapper.Parameters);
                    var providedArguments = arguments
                        .Select((argument, index) => (Argument: argument, Index: index))
                        .Where(item => item.Argument is not null)
                        .ToList();
                    var argumentTypes = providedArguments
                        .Select(item => InferArgumentType(
                            item.Argument!,
                            caller,
                            call.SpanStart,
                            knownTypeIdentities))
                        .ToList();
                    return argumentTypes.All(type => !string.IsNullOrEmpty(type))
                        && providedArguments
                            .Select((item, index) => (item.Index, Type: argumentTypes[index]))
                            .All(item => TypeNamesMatch(
                                wrapper.ParameterTypes[item.Index],
                                item.Type!));
                })
                .ToList();
            if (matchingParameterTypes.Count == 0
                && candidates.All(candidate =>
                    candidate.RequiredParameterCount <= argumentCount
                    && argumentCount <= candidate.Parameters.Count))
                return new WrapperResolution(candidates, binding, "overload_not_found");
            if (matchingParameterTypes.Count > 0)
                candidates = matchingParameterTypes;
        }

        return new WrapperResolution(candidates, binding);
    }

    private static ReceiverBinding ResolveReceiverBinding(
        ExpressionSyntax receiverExpression,
        MethodDeclarationSyntax caller,
        int position,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        var expression = receiverExpression.ToString().Trim();
        var receiverName = GetReceiverName(receiverExpression);
        if (receiverExpression is ObjectCreationExpressionSyntax creation)
        {
            var typeIdentities = CSharpAnalyzer.ResolveKnownTypeIdentities(
                creation.Type.ToString(),
                caller,
                knownTypeIdentities);
            var typeIdentity = typeIdentities.Count == 1
                ? typeIdentities[0]
                : CSharpAnalyzer.QualifyTypeIdentity(creation.Type.ToString(), caller);
            return new ReceiverBinding(
                expression,
                typeIdentity,
                typeIdentities.Count == 1 ? typeIdentity : "",
                typeIdentities,
                new[] { creation.ToString().Trim() },
                Array.Empty<string>());
        }

        if (string.IsNullOrEmpty(receiverName))
            return new ReceiverBinding(expression, "", "", Array.Empty<string>(), Array.Empty<string>(), Array.Empty<string>());

        var declaredTypes = new List<string>();
        var concreteTypes = new List<string>();
        var constructionFacts = new List<string>();
        var assignmentFacts = new List<string>();

        void AddConcreteTypes(string typeName)
            => concreteTypes.AddRange(CSharpAnalyzer.ResolveKnownTypeIdentities(
                typeName,
                caller,
                knownTypeIdentities));

        foreach (var declaration in caller.DescendantNodes().OfType<VariableDeclarationSyntax>())
        {
            foreach (var variable in declaration.Variables.Where(
                variable => variable.Identifier.Text == receiverName
                    && variable.SpanStart < position))
            {
                var declaredTypeIdentities = declaration.Type.ToString().Equals(
                    "var",
                    StringComparison.Ordinal)
                    ? variable.Initializer?.Value is ObjectCreationExpressionSyntax createdValue
                        ? CSharpAnalyzer.ResolveKnownTypeIdentities(
                            createdValue.Type.ToString(),
                            caller,
                            knownTypeIdentities)
                        : Array.Empty<string>()
                    : CSharpAnalyzer.ResolveKnownTypeIdentities(
                        declaration.Type.ToString(),
                        caller,
                        knownTypeIdentities);
                declaredTypes.AddRange(declaredTypeIdentities);
                if (variable.Initializer?.Value is ObjectCreationExpressionSyntax created)
                {
                    constructionFacts.Add(created.ToString().Trim());
                    AddConcreteTypes(created.Type.ToString());
                }
            }
        }

        foreach (var assignment in caller.DescendantNodes().OfType<AssignmentExpressionSyntax>()
            .Where(assignment => assignment.SpanStart < position
                && IsReceiverAssignment(assignment, receiverName)))
        {
            assignmentFacts.Add(assignment.ToString().Trim());
            if (assignment.Right is ObjectCreationExpressionSyntax assignedCreation)
            {
                AddConcreteTypes(assignedCreation.Type.ToString());
                constructionFacts.Add(assignedCreation.ToString().Trim());
            }
        }

        var parameter = caller.ParameterList.Parameters.FirstOrDefault(
            item => item.Identifier.Text == receiverName && item.Type is not null);
        if (parameter?.Type is not null)
            declaredTypes.AddRange(CSharpAnalyzer.ResolveKnownTypeIdentities(
                parameter.Type.ToString(),
                caller,
                knownTypeIdentities));

        var containingClass = caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(containingClass);
        var classDeclarations = GetClassDeclarations(sourceRoots, callerTypeIdentity).ToList();
        if (containingClass is not null && !classDeclarations.Contains(containingClass))
            classDeclarations.Add(containingClass);

        if (classDeclarations.Count > 0)
        {
            var callerHasLocalReceiver = caller.ParameterList.Parameters.Any(
                    parameter => parameter.Identifier.Text == receiverName)
                || caller.DescendantNodes().OfType<VariableDeclarationSyntax>().Any(
                    declaration => declaration.Variables.Any(
                        variable => variable.Identifier.Text == receiverName));
            var hasClassMemberReceiver = classDeclarations
                .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                .OfType<FieldDeclarationSyntax>()
                .Any(field => field.Declaration.Variables.Any(
                    variable => variable.Identifier.Text == receiverName))
                || classDeclarations
                    .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                    .OfType<PropertyDeclarationSyntax>()
                    .Any(property => property.Identifier.Text == receiverName);

            if (!callerHasLocalReceiver && hasClassMemberReceiver)
            {
                foreach (var field in classDeclarations
                    .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                    .OfType<FieldDeclarationSyntax>()
                    .Where(field => field.Declaration.Variables.Any(
                        variable => variable.Identifier.Text == receiverName)))
                {
                    declaredTypes.AddRange(CSharpAnalyzer.ResolveKnownTypeIdentities(
                        field.Declaration.Type.ToString(),
                        caller,
                        knownTypeIdentities));
                    foreach (var variable in field.Declaration.Variables.Where(
                        variable => variable.Identifier.Text == receiverName))
                    {
                        if (variable.Initializer?.Value is ObjectCreationExpressionSyntax created)
                        {
                            constructionFacts.Add(created.ToString().Trim());
                            AddConcreteTypes(created.Type.ToString());
                        }
                    }
                }

                foreach (var assignment in classDeclarations
                    .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                    .OfType<AssignmentExpressionSyntax>()
                    .Where(assignment => IsFieldReceiverAssignment(assignment, receiverName)))
                {
                    assignmentFacts.Add(assignment.ToString().Trim());
                    if (assignment.Right is ObjectCreationExpressionSyntax assignedCreation)
                    {
                        AddConcreteTypes(assignedCreation.Type.ToString());
                        constructionFacts.Add(assignedCreation.ToString().Trim());
                    }
                }
            }

            var property = classDeclarations
                .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                .OfType<PropertyDeclarationSyntax>()
                .FirstOrDefault(item => item.Identifier.Text == receiverName);
            if (property is not null)
            {
                declaredTypes.AddRange(CSharpAnalyzer.ResolveKnownTypeIdentities(
                    property.Type.ToString(),
                    caller,
                    knownTypeIdentities));
                if (property.Initializer?.Value is ObjectCreationExpressionSyntax initialized)
                {
                    constructionFacts.Add(initialized.ToString().Trim());
                    AddConcreteTypes(initialized.Type.ToString());
                }
                if (property.ExpressionBody?.Expression is ObjectCreationExpressionSyntax returned)
                {
                    constructionFacts.Add(returned.ToString().Trim());
                    AddConcreteTypes(returned.Type.ToString());
                }
            }
        }

        var distinctDeclaredTypes = declaredTypes
            .Where(type => !string.IsNullOrWhiteSpace(type))
            .Distinct(StringComparer.Ordinal)
            .ToList();
        var implementationTypes = concreteTypes
            .Where(type => !string.IsNullOrWhiteSpace(type))
            .Distinct(StringComparer.Ordinal)
            .ToList();
        var receiverType = distinctDeclaredTypes.Count == 1
            ? distinctDeclaredTypes[0]
            : implementationTypes.Count == 1
            ? implementationTypes[0]
            : "";
        var implementationIdentity = implementationTypes.Count == 1
            ? implementationTypes[0]
            : "";
        return new ReceiverBinding(
            expression,
            receiverType,
            implementationIdentity,
            implementationTypes,
            constructionFacts.Distinct(StringComparer.Ordinal).ToList(),
            assignmentFacts.Distinct(StringComparer.Ordinal).ToList());
    }

    private static string? ResolveDeclaredType(
        VariableDeclarationSyntax declaration,
        VariableDeclaratorSyntax variable,
        MethodDeclarationSyntax caller,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        if (!declaration.Type.ToString().Equals("var", StringComparison.Ordinal))
        {
            var declaredTypes = CSharpAnalyzer.ResolveKnownTypeIdentities(
                declaration.Type.ToString(),
                caller,
                knownTypeIdentities);
            return declaredTypes.Count == 1 ? declaredTypes[0] : null;
        }
        if (variable.Initializer?.Value is not ObjectCreationExpressionSyntax creation)
            return null;
        var createdTypes = CSharpAnalyzer.ResolveKnownTypeIdentities(
            creation.Type.ToString(),
            caller,
            knownTypeIdentities);
        return createdTypes.Count == 1 ? createdTypes[0] : null;
    }

    private static bool IsReceiverAssignment(AssignmentExpressionSyntax assignment, string receiverName)
    {
        var left = assignment.Left.ToString().Trim();
        return left == receiverName || left == $"this.{receiverName}";
    }

    private static string? GetReceiverName(ExpressionSyntax expression)
    {
        if (expression is IdentifierNameSyntax identifier)
            return identifier.Identifier.Text;
        if (expression is MemberAccessExpressionSyntax member)
        {
            if (member.Expression is ThisExpressionSyntax)
                return member.Name.Identifier.Text;
            return GetReceiverName(member.Expression);
        }
        return null;
    }

    private static string ResolveMethodSemantics(
        IReadOnlyList<AssignmentExpressionSyntax> commandTypeAssignments,
        string? modeParameter)
    {
        if (commandTypeAssignments.Count == 0)
            return "fixed_inline_sql";

        var effectiveAssignments = SyntaxBranchAnalyzer.RemoveShadowedAssignments(
            commandTypeAssignments.Select(assignment => (
                Assignment: (SyntaxNode)assignment,
                Value: assignment.Right)));
        var modes = new HashSet<string>(StringComparer.Ordinal);
        var conditional = false;
        foreach (var item in effectiveAssignments)
        {
            var assignment = item.Assignment;
            var value = item.Value;
            if (ContainsStoredProcedureMember(value))
                modes.Add("stored_procedure");
            if (ContainsTextMember(value))
                modes.Add("inline_sql");
            if (!ContainsStoredProcedureMember(value)
                && !ContainsTextMember(value))
                modes.Add("unresolved");
            conditional |= value.DescendantNodesAndSelf()
                .OfType<ConditionalExpressionSyntax>()
                .Any()
                || assignment.FirstAncestorOrSelf<IfStatementSyntax>() is not null;
        }

        if (modeParameter is not null
            && modes.Contains("stored_procedure")
            && (modes.Contains("inline_sql") || conditional))
            return "call_site";
        if (modes.SetEquals(new[] { "stored_procedure" }) && !conditional)
            return "fixed_stored_procedure";
        if (modes.All(mode => mode == "inline_sql"))
            return "fixed_inline_sql";
        return "unresolved";
    }

    private static string ResolveCommandTypeMode(WrapperDefinition wrapper)
        => wrapper.MethodSemantics switch
        {
            "fixed_stored_procedure" => "stored_procedure",
            "fixed_inline_sql" => "text",
            "call_site" => "unknown",
            _ => "unknown",
        };

    private static string BuildMethodIdentity(
        string typeIdentity,
        string methodName,
        IReadOnlyList<string> parameterTypes)
        => $"{typeIdentity}.{methodName}({string.Join(",", parameterTypes)})";

    private static string? InferArgumentType(
        ExpressionSyntax expression,
        MethodDeclarationSyntax caller,
        int position,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        if (expression is LiteralExpressionSyntax literal)
        {
            if (literal.Token.Value is string)
                return "string";
            if (literal.IsKind(SyntaxKind.TrueLiteralExpression)
                || literal.IsKind(SyntaxKind.FalseLiteralExpression))
                return "bool";
            if (literal.IsKind(SyntaxKind.NullLiteralExpression))
                return null;
            if (literal.Token.Value is int)
                return "int";
            if (literal.Token.Value is long)
                return "long";
            if (literal.Token.Value is double)
                return "double";
        }

        if (expression is ObjectCreationExpressionSyntax creation)
        {
            var createdTypes = CSharpAnalyzer.ResolveKnownTypeIdentities(
                creation.Type.ToString(),
                caller,
                knownTypeIdentities);
            return createdTypes.Count == 1 ? createdTypes[0] : null;
        }
        if (expression is CastExpressionSyntax cast)
        {
            var castTypes = CSharpAnalyzer.ResolveKnownTypeIdentities(
                cast.Type.ToString(),
                caller,
                knownTypeIdentities);
            return castTypes.Count == 1 ? castTypes[0] : null;
        }
        if (expression is IdentifierNameSyntax identifier)
        {
            var parameter = caller.ParameterList.Parameters.FirstOrDefault(
                item => item.Identifier.Text == identifier.Identifier.Text);
            if (parameter?.Type is not null)
            {
                if (parameter.Type.ToString().Equals("dynamic", StringComparison.Ordinal))
                    return null;
                var parameterTypes = CSharpAnalyzer.ResolveKnownTypeIdentities(
                    parameter.Type.ToString(),
                    caller,
                    knownTypeIdentities);
                return parameterTypes.Count == 1 ? parameterTypes[0] : null;
            }

            foreach (var declaration in caller.DescendantNodes().OfType<VariableDeclarationSyntax>()
                .Where(declaration => declaration.SpanStart < position))
            {
                var variable = declaration.Variables.FirstOrDefault(
                    item => item.Identifier.Text == identifier.Identifier.Text);
                if (variable is null)
                    continue;
                var declared = ResolveDeclaredType(
                    declaration,
                    variable,
                    caller,
                    knownTypeIdentities);
                if (declared is not null)
                    return declared.Equals("dynamic", StringComparison.Ordinal)
                        ? null
                        : declared;
            }
        }
        return null;
    }

    private static bool TypeNamesMatch(string expected, string actual)
    {
        var normalizedExpected = NormalizeTypeName(expected);
        var normalizedActual = NormalizeTypeName(actual);
        return normalizedExpected == normalizedActual;
    }

    private static string NormalizeTypeName(string typeName)
        => typeName.Trim().Replace("global::", "", StringComparison.Ordinal).TrimEnd('?');

    /// <summary>The adapter rule's terminal sink is the adapter's own fill call.</summary>
    private static IReadOnlyList<InvocationExpressionSyntax> ResolveAdapterFillInvocations(
        MethodDeclarationSyntax method,
        string adapterVariable)
        => method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression is MemberAccessExpressionSyntax member
                && member.Expression.ToString().Trim() == adapterVariable
                && CSharpAnalyzer.IsAdapterFillMethod(member.Name.Identifier.Text))
            .DistinctBy(invocation => invocation.SpanStart)
            .ToList();

    private static IReadOnlyList<InvocationExpressionSyntax> ResolveCommandTerminalSinkInvocations(
        MethodDeclarationSyntax method,
        string commandVariable)
    {
        var sinkInvocations = method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression is MemberAccessExpressionSyntax member
                && member.Expression.ToString().Trim() == commandVariable
                && IsAdoNetCommandExecutionMethod(member.Name.Identifier.Text))
            .ToList();

        var adapterVariables = method.DescendantNodes()
            .OfType<ObjectCreationExpressionSyntax>()
            .Where(creation => creation.Type.ToString().Split('.').Last() is
                "DbDataAdapter" or
                "SqlDataAdapter" or
                "OleDbDataAdapter" or
                "OdbcDataAdapter" or
                "NpgsqlDataAdapter" or
                "MySqlDataAdapter")
            .Where(creation => creation.ArgumentList?.Arguments.Any(argument =>
                argument.Expression.ToString().Trim() == commandVariable) is true)
            .Select(ResolveVariableName)
            .Where(variable => !string.IsNullOrWhiteSpace(variable))
            .Cast<string>()
            .ToHashSet(StringComparer.Ordinal);

        sinkInvocations.AddRange(method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression is MemberAccessExpressionSyntax member
                && adapterVariables.Contains(member.Expression.ToString().Trim())
                && CSharpAnalyzer.IsAdapterFillMethod(member.Name.Identifier.Text)));

        return sinkInvocations
            .DistinctBy(invocation => invocation.SpanStart)
            .ToList();
    }

    private static string? ResolveTerminalSinkName(
        MethodDeclarationSyntax method,
        CommandSource commandSource)
    {
        var sinkNames = commandSource.ResolveTerminalSinks(method)
            .Select(invocation => ((MemberAccessExpressionSyntax)invocation.Expression).Name.Identifier.Text)
            .Distinct(StringComparer.Ordinal)
            .ToList();
        return sinkNames.Count == 1 ? sinkNames[0] : null;
    }

    private static DirectSqlInvocation CreateAmbiguousInvocation(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        string callerClass,
        WrapperResolution resolution)
    {
        var methodName = call.Expression switch
        {
            MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            _ => "",
        };
        var commandTextResolution = ResolveCommandTextArgument(call, resolution.Candidates);
        var argument = commandTextResolution.Argument;
        var commandText = commandTextResolution.Literal;
        var commandTextKind = commandText is not null ? "literal" : "dynamic";
        var candidateFacts = BuildOverloadCandidateFacts(resolution);
        var sinkNames = resolution.Candidates
            .Select(candidate => candidate.TerminalSink)
            .Where(sink => !string.IsNullOrWhiteSpace(sink))
            .Distinct(StringComparer.Ordinal)
            .ToList();
        var implementationIdentities = resolution.Candidates
            .Select(candidate => candidate.TypeIdentity)
            .Distinct(StringComparer.Ordinal)
            .ToList();
        return new DirectSqlInvocation(
            callerClass,
            caller.Identifier.Text,
            commandTextKind,
            commandText,
            false,
            resolution.Binding.Expression,
            call.SpanStart,
            call.Span.End,
            "source_wrapper",
            implementationIdentities.Count == 1 ? resolution.Candidates[0].ClassName : null,
            methodName,
            true,
            false,
            "unknown",
            new[] { caller.Identifier.Text, methodName },
            SyntaxBranchAnalyzer.GetBranchContext(call),
            resolution.Binding.ReceiverType,
            resolution.Binding.ReceiverType,
            resolution.Binding.Expression,
            argument?.ToString(),
            commandText,
            sinkNames.Count == 1 ? sinkNames[0] : null,
            "unknown",
            ReceiverExpression: resolution.Binding.Expression,
            ReceiverImplementationIdentity: resolution.Binding.ImplementationIdentity,
            ReceiverBindingProvenance: "source",
            ReceiverConstructionFacts: resolution.Binding.ConstructionFacts,
            ReceiverAssignmentFacts: resolution.Binding.AssignmentFacts,
            WrapperImplementationIdentity: implementationIdentities.Count == 1
                ? implementationIdentities[0]
                : null,
            WrapperMethodSemantics: "unresolved",
            WrapperOverloadCandidates: candidateFacts,
            WrapperOverloadAmbiguous: true,
            WrapperTerminalSink: sinkNames.Count == 1 ? sinkNames[0] : null);
    }

    private static IReadOnlyList<ExpressionSyntax?> MapInvocationArguments(
        InvocationExpressionSyntax call,
        IReadOnlyList<string> parameterNames)
    {
        var mapped = new ExpressionSyntax?[parameterNames.Count];
        var assigned = new bool[parameterNames.Count];
        var nextPositionalIndex = 0;

        foreach (var argument in call.ArgumentList.Arguments)
        {
            var namedParameter = argument.NameColon?.Name.Identifier.Text;
            var parameterIndex = -1;
            if (!string.IsNullOrEmpty(namedParameter))
            {
                for (var index = 0; index < parameterNames.Count; index++)
                {
                    if (string.Equals(
                            parameterNames[index],
                            namedParameter,
                            StringComparison.Ordinal))
                    {
                        parameterIndex = index;
                        break;
                    }
                }
            }
            else
            {
                while (nextPositionalIndex < assigned.Length
                    && assigned[nextPositionalIndex])
                    nextPositionalIndex++;
                parameterIndex = nextPositionalIndex;
                nextPositionalIndex++;
            }

            if (parameterIndex < 0 || parameterIndex >= mapped.Length)
                continue;
            if (assigned[parameterIndex])
                continue;
            mapped[parameterIndex] = argument.Expression;
            assigned[parameterIndex] = true;
        }

        return mapped;
    }

    private static ExpressionSyntax? ResolveInvocationArgument(
        InvocationExpressionSyntax call,
        IReadOnlyList<string> parameterNames,
        int parameterIndex)
        => parameterIndex < 0
            ? null
            : MapInvocationArguments(call, parameterNames)
                .ElementAtOrDefault(parameterIndex);

    private static string ResolveMode(InvocationExpressionSyntax call, WrapperDefinition wrapper)
    {
        if (wrapper.MethodSemantics == "fixed_stored_procedure")
            return "stored_procedure";
        if (wrapper.MethodSemantics == "fixed_inline_sql")
            return "inline_sql";
        if (wrapper.ModeParameterIndex < 0)
            return "unknown";

        var argument = ResolveInvocationArgument(
            call,
            wrapper.Parameters,
            wrapper.ModeParameterIndex);
        if (argument is null)
            return "inline_sql";
        if (argument is LiteralExpressionSyntax literal)
        {
            if (literal.IsKind(SyntaxKind.TrueLiteralExpression))
                return "stored_procedure";
            if (literal.IsKind(SyntaxKind.FalseLiteralExpression))
                return "inline_sql";
            if (literal.Token.Value is string text)
            {
                if (text.Equals("SP", StringComparison.OrdinalIgnoreCase)
                    || text.Equals("StoredProcedure", StringComparison.OrdinalIgnoreCase))
                    return "stored_procedure";
                if (text.Equals("SQL", StringComparison.OrdinalIgnoreCase)
                    || text.Equals("Text", StringComparison.OrdinalIgnoreCase)
                    || text.Equals("Inline", StringComparison.OrdinalIgnoreCase))
                    return "inline_sql";
            }
        }
        return "unknown";
    }

    private static IReadOnlyList<WrapperCommandTextCandidate> ReadWrapperCommandTextCandidates(
        InvocationExpressionSyntax call,
        WrapperDefinition wrapper,
        MethodDeclarationSyntax caller)
    {
        if (wrapper.CommandTextParameterIndex < 0)
            return new[]
            {
                CreateWrapperCommandTextCandidate(
                    wrapper.CommandTextLiteral,
                    wrapper.CommandTextLiteral,
                    call),
            };

        var argument = ResolveInvocationArgument(
            call,
            wrapper.Parameters,
            wrapper.CommandTextParameterIndex);
        return ReadWrapperCommandTextCandidates(
            argument,
            caller,
            call,
            call.SpanStart,
            argument?.ToString());
    }

    private static IReadOnlyList<WrapperCommandTextCandidate> ReadWrapperCommandTextCandidates(
        ExpressionSyntax? expression,
        MethodDeclarationSyntax caller,
        SyntaxNode anchor,
        int position,
        string? originalArgumentExpression,
        bool resolveVariables = true)
    {
        if (resolveVariables && expression is IdentifierNameSyntax identifier)
        {
            var assignments = caller.DescendantNodes()
                .OfType<AssignmentExpressionSyntax>()
                .Where(assignment => assignment.Left is IdentifierNameSyntax left
                    && left.Identifier.Text == identifier.Identifier.Text
                    && assignment.SpanStart < position)
                .Select(assignment => (
                    Assignment: (SyntaxNode)assignment,
                    Value: assignment.Right));
            var declarations = caller.DescendantNodes()
                .OfType<VariableDeclaratorSyntax>()
                .Where(declaration => declaration.Identifier.Text == identifier.Identifier.Text
                    && declaration.Initializer is not null
                    && declaration.SpanStart < position)
                .Select(declaration => (
                    Assignment: (SyntaxNode)declaration,
                    Value: declaration.Initializer!.Value));
            var resolved = SyntaxBranchAnalyzer.RemoveShadowedAssignments(
                    assignments.Concat(declarations))
                .SelectMany(item => ReadWrapperCommandTextCandidates(
                    item.Value,
                    caller,
                    item.Assignment,
                    item.Assignment.SpanStart,
                    originalArgumentExpression,
                    resolveVariables: false))
                .ToList();
            if (resolved.Count > 0)
                return resolved;
        }

        if (expression is ConditionalExpressionSyntax conditional)
        {
            return ReadWrapperCommandTextCandidates(
                    conditional.WhenTrue,
                    caller,
                    conditional.WhenTrue,
                    position,
                    originalArgumentExpression,
                    resolveVariables)
                .Concat(ReadWrapperCommandTextCandidates(
                    conditional.WhenFalse,
                    caller,
                    conditional.WhenFalse,
                    position,
                    originalArgumentExpression,
                    resolveVariables))
                .ToList();
        }

        return new[]
        {
            CreateWrapperCommandTextCandidate(
                expression is LiteralExpressionSyntax { Token.Value: string text } ? text : null,
                originalArgumentExpression ?? expression?.ToString(),
                anchor),
        };
    }

    private static WrapperCommandTextCandidate CreateWrapperCommandTextCandidate(
        string? commandText,
        string? argumentExpression,
        SyntaxNode anchor)
        => new(
            commandText is null ? "dynamic" : "literal",
            commandText,
            argumentExpression,
            SyntaxBranchAnalyzer.GetBranchContext(anchor),
            anchor.SpanStart,
            anchor.Span.End,
            anchor is VariableDeclaratorSyntax or AssignmentExpressionSyntax
                ? $"assignment:{anchor.ToString().Trim()}"
                : commandText is null
                    ? "dynamic_expression"
                    : "literal_expression");

    private sealed record WrapperCommandTextCandidate(
        string CommandTextKind,
        string? CommandText,
        string? ArgumentExpression,
        IReadOnlyList<string> BranchContext,
        int? SourceStartOffset = null,
        int? SourceEndOffset = null,
        string ValueProvenance = "");

    private sealed record ConnectionResolution(
        string? Expression,
        IReadOnlyList<string> Candidates);

    private static string? FindModeParameter(
        MethodDeclarationSyntax method,
        IReadOnlyList<AssignmentExpressionSyntax> commandTypeAssignments,
        IReadOnlyList<string> parameters)
    {
        foreach (var assignment in commandTypeAssignments)
        {
            var conditional = assignment.Right.DescendantNodesAndSelf()
                .OfType<ConditionalExpressionSyntax>()
                .FirstOrDefault(expression =>
                    ContainsStoredProcedureMember(expression.WhenTrue)
                    || ContainsStoredProcedureMember(expression.WhenFalse));
            if (conditional is not null)
            {
                var parameter = FindModeParameterFromCondition(conditional.Condition, parameters);
                if (parameter is not null)
                    return parameter;
            }

            var enclosingIf = assignment.FirstAncestorOrSelf<IfStatementSyntax>();
            var ifParameter = FindModeParameterFromCondition(enclosingIf?.Condition, parameters);
            if (ifParameter is not null)
                return ifParameter;
        }
        return null;
    }

    private static string? FindModeParameterFromCondition(
        ExpressionSyntax? condition,
        IReadOnlyList<string> parameters)
    {
        if (condition is null)
            return null;

        foreach (var comparison in condition.DescendantNodesAndSelf().OfType<BinaryExpressionSyntax>())
        {
            if (!comparison.IsKind(SyntaxKind.EqualsExpression))
                continue;
            var left = comparison.Left as IdentifierNameSyntax;
            var right = comparison.Right as IdentifierNameSyntax;
            var leftText = comparison.Left as LiteralExpressionSyntax;
            var rightText = comparison.Right as LiteralExpressionSyntax;
            if (left is not null
                && rightText?.Token.Value is string rightValue
                && IsStoredProcedureModeText(rightValue)
                && parameters.Contains(left.Identifier.Text))
                return left.Identifier.Text;
            if (right is not null
                && leftText?.Token.Value is string leftValue
                && IsStoredProcedureModeText(leftValue)
                && parameters.Contains(right.Identifier.Text))
                return right.Identifier.Text;
        }

        if (condition is IdentifierNameSyntax identifier && parameters.Contains(identifier.Identifier.Text))
            return identifier.Identifier.Text;
        return null;
    }

    private static bool IsStoredProcedureModeText(string text)
        => text.Equals("SP", StringComparison.OrdinalIgnoreCase)
            || text.Equals("StoredProcedure", StringComparison.OrdinalIgnoreCase);

    private static bool IsMemberAssignment(
        AssignmentExpressionSyntax assignment,
        string variableName,
        string memberName)
        => assignment.Left is MemberAccessExpressionSyntax member
            && member.Expression.ToString() == variableName
            && member.Name.Identifier.Text == memberName;

    private static List<AssignmentExpressionSyntax> GetCommandPropertyAssignments(
        MethodDeclarationSyntax method,
        CommandSource commandSource,
        string propertyName)
    {
        var assignments = method.DescendantNodes()
            .OfType<AssignmentExpressionSyntax>()
            .Where(assignment => IsMemberAssignment(
                assignment,
                commandSource.CommandPropertyReceiver,
                propertyName))
            .ToList();
        if (commandSource.PropertyInitializerOwner?.Initializer is { } initializer)
        {
            assignments.AddRange(initializer.Expressions
                .OfType<AssignmentExpressionSyntax>()
                .Where(assignment => assignment.Left is IdentifierNameSyntax identifier
                    && identifier.Identifier.Text == propertyName));
        }
        return assignments
            .OrderBy(assignment => assignment.SpanStart)
            .ToList();
    }

    private static bool ContainsStoredProcedureMember(ExpressionSyntax expression)
        => ContainsCommandTypeMember(expression, "StoredProcedure");

    private static bool ContainsTextMember(ExpressionSyntax expression)
        => ContainsCommandTypeMember(expression, "Text");

    private static bool ContainsCommandTypeMember(
        ExpressionSyntax expression,
        string memberName)
        => expression.DescendantNodesAndSelf()
            .OfType<MemberAccessExpressionSyntax>()
            .Any(member => member.Name.Identifier.Text == memberName
                && IsCommandTypeIdentity(member.Expression))
            || expression.DescendantNodesAndSelf()
                .OfType<CastExpressionSyntax>()
                .Any(cast => CommandTypeCastRecognizer.ResolveNumericCastMember(cast) == memberName);

    private static bool IsCommandTypeIdentity(ExpressionSyntax expression)
        => CommandTypeCastRecognizer.IsCommandTypeIdentity(expression);

    private static string? ResolveVariableName(ObjectCreationExpressionSyntax creation)
    {
        if (creation.Parent is EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax declarator })
            return declarator.Identifier.Text;
        if (creation.Parent is AssignmentExpressionSyntax { Left: IdentifierNameSyntax identifier })
            return identifier.Identifier.Text;
        return null;
    }

    private static ConnectionResolution ResolveCallConnectionExpression(
        InvocationExpressionSyntax call,
        WrapperDefinition wrapper,
        MethodDeclarationSyntax caller,
        IReadOnlyList<CompilationUnitSyntax> sourceRoots,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        // A wrapper that opens its own connection reaches one fixed database whatever the
        // call site is, so the call site inherits the wrapper's connection expression. It is
        // also the call site's one connection candidate: an expression that resolves to no
        // database then still reads as one unresolved connection source, never as a call
        // with no connection source to rate.
        if (wrapper.SuppliesConnectionTo(call.SyntaxTree?.FilePath))
        {
            return new(
                wrapper.ConnectionExpression,
                new[] { wrapper.ConnectionExpression! });
        }

        if (call.Expression is not MemberAccessExpressionSyntax member)
            return new(null, Array.Empty<string>());

        var receiverExpression = member.Expression;
        if (receiverExpression is ObjectCreationExpressionSyntax directCreation)
        {
            if (!IsWrapperConstruction(
                    directCreation,
                    wrapper,
                    caller,
                    knownTypeIdentities))
                return new(null, Array.Empty<string>());
            var expression = ReadConnectionArgument(
                directCreation,
                wrapper.ConstructorConnectionParameterIndex);
            return new(expression, Array.Empty<string>());
        }

        var receiver = receiverExpression.ToString().Trim();
        var receiverName = GetReceiverName(receiverExpression);
        if (string.IsNullOrWhiteSpace(receiverName))
            return new(null, Array.Empty<string>());
        if (wrapper.ConstructorConnectionParameterIndex < 0)
            return new(null, Array.Empty<string>());

        var candidates = new List<(string Scope, string? Expression)>();
        void AddCandidate(ObjectCreationExpressionSyntax creation, string scope)
        {
            if (!IsWrapperConstruction(creation, wrapper, caller, knownTypeIdentities))
                return;
            candidates.Add((scope, ReadConnectionArgument(
                creation,
                wrapper.ConstructorConnectionParameterIndex)));
        }

        foreach (var creation in caller.DescendantNodes()
            .OfType<ObjectCreationExpressionSyntax>()
            .Where(candidate => candidate.SyntaxTree != call.SyntaxTree
                || candidate.SpanStart < call.SpanStart)
            .Where(candidate => IsReceiverConstruction(candidate, receiverName)))
        {
            AddCandidate(creation, $"caller:{caller.SpanStart}");
        }

        var containingClass = caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(containingClass);
        var classDeclarations = GetClassDeclarations(sourceRoots, callerTypeIdentity).ToList();
        if (containingClass is not null
            && !classDeclarations.Contains(containingClass))
            classDeclarations.Add(containingClass);
        var callerHasLocalReceiver = caller.ParameterList.Parameters.Any(
                parameter => parameter.Identifier.Text == receiverName)
            || caller.DescendantNodes().OfType<VariableDeclarationSyntax>().Any(
                declaration => declaration.Variables.Any(
                    variable => variable.Identifier.Text == receiverName));
        var hasClassMemberReceiver = classDeclarations
            .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
            .OfType<FieldDeclarationSyntax>()
            .Any(field => field.Declaration.Variables.Any(
                variable => variable.Identifier.Text == receiverName)) is true
            || classDeclarations
                .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                .OfType<PropertyDeclarationSyntax>()
                .Any(property => property.Identifier.Text == receiverName) is true;
        if (!callerHasLocalReceiver && hasClassMemberReceiver)
        {
            foreach (var field in classDeclarations
                .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                .OfType<FieldDeclarationSyntax>()
                .Where(field => field.Declaration.Variables.Any(
                    variable => variable.Identifier.Text == receiverName)))
            {
                foreach (var variable in field.Declaration.Variables.Where(
                    variable => variable.Identifier.Text == receiverName))
                {
                    if (variable.Initializer?.Value is ObjectCreationExpressionSyntax creation)
                        AddCandidate(creation, $"field:{field.SpanStart}");
                }
            }

            foreach (var assignment in classDeclarations
                .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                .OfType<AssignmentExpressionSyntax>()
                .Where(candidate => IsFieldReceiverAssignment(candidate, receiverName)))
            {
                if (assignment.Right is not ObjectCreationExpressionSyntax creation)
                    continue;
                var scope = assignment.Ancestors()
                    .OfType<MethodDeclarationSyntax>()
                    .Select(method => $"method:{method.SpanStart}")
                    .FirstOrDefault()
                    ?? assignment.Ancestors()
                        .OfType<ConstructorDeclarationSyntax>()
                        .Select(constructor => $"constructor:{constructor.SpanStart}")
                        .FirstOrDefault()
                    ?? $"assignment:{assignment.SpanStart}";
                AddCandidate(creation, scope);
            }

            foreach (var property in classDeclarations
                .SelectMany(classDeclaration => classDeclaration.DescendantNodes())
                .OfType<PropertyDeclarationSyntax>()
                .Where(property => property.Identifier.Text == receiverName))
            {
                if (property.Initializer?.Value is ObjectCreationExpressionSyntax initialized)
                    AddCandidate(initialized, $"property:{property.SpanStart}");
                if (property.ExpressionBody?.Expression is ObjectCreationExpressionSyntax returned)
                    AddCandidate(returned, $"property:{property.SpanStart}");
            }
        }

        if (candidates.Count == 0)
            return new(null, Array.Empty<string>());

        var distinctCandidates = candidates.Distinct().ToList();
        if (distinctCandidates.Count == 1 && distinctCandidates[0].Expression is not null)
            return new(distinctCandidates[0].Expression, Array.Empty<string>());

        var candidateFacts = distinctCandidates
            .Select(candidate =>
                $"{candidate.Scope}:{candidate.Expression ?? "<null>"}")
            .Distinct(StringComparer.Ordinal)
            .ToList();
        return new(null, candidateFacts);
    }

    private static bool IsWrapperConstruction(
        ObjectCreationExpressionSyntax creation,
        WrapperDefinition wrapper,
        MethodDeclarationSyntax caller,
        IReadOnlyCollection<string> knownTypeIdentities)
    {
        var candidateMethod = creation.Ancestors()
            .OfType<MethodDeclarationSyntax>()
            .FirstOrDefault() ?? caller;
        return CSharpAnalyzer.ResolveKnownTypeIdentities(
                creation.Type.ToString(),
                candidateMethod,
                knownTypeIdentities)
            .Contains(wrapper.TypeIdentity, StringComparer.Ordinal);
    }

    private static string? ReadConnectionArgument(
        ObjectCreationExpressionSyntax creation,
        int parameterIndex)
    {
        var argument = creation.ArgumentList?.Arguments.ElementAtOrDefault(parameterIndex)?.Expression;
        if (argument is null
            || argument is LiteralExpressionSyntax literal
                && literal.IsKind(SyntaxKind.NullLiteralExpression))
            return null;
        var expression = argument.ToString().Trim();
        return string.IsNullOrWhiteSpace(expression) ? null : expression;
    }

    private static bool IsReceiverConstruction(
        ObjectCreationExpressionSyntax creation,
        string receiver)
    {
        if (creation.Parent is EqualsValueClauseSyntax
            {
                Parent: VariableDeclaratorSyntax declarator,
            })
            return declarator.Identifier.Text == receiver;
        if (creation.Parent is AssignmentExpressionSyntax assignment)
        {
            var left = assignment.Left.ToString().Trim();
            return left == receiver || left == $"this.{receiver}";
        }
        return false;
    }

    private static bool IsFieldReceiverAssignment(
        AssignmentExpressionSyntax assignment,
        string receiverName)
    {
        var left = assignment.Left.ToString().Trim();
        if (left == $"this.{receiverName}")
            return true;
        if (left != receiverName)
            return false;

        var containingMethod = assignment.Ancestors()
            .OfType<MethodDeclarationSyntax>()
            .FirstOrDefault();
        if (containingMethod is not null)
        {
            if (containingMethod.ParameterList.Parameters.Any(
                    parameter => parameter.Identifier.Text == receiverName))
                return false;
            if (containingMethod.DescendantNodes().OfType<VariableDeclarationSyntax>().Any(
                    declaration => declaration.Variables.Any(
                        variable => variable.Identifier.Text == receiverName)))
                return false;
        }
        return true;
    }

    private static int FindConstructorConnectionParameterIndex(
        IReadOnlyList<ClassDeclarationSyntax> classDeclarations,
        string? connectionExpression)
    {
        if (classDeclarations.Count == 0 || string.IsNullOrWhiteSpace(connectionExpression))
            return -1;

        var fieldName = connectionExpression.Trim();
        if (fieldName.StartsWith("this.", StringComparison.Ordinal))
            fieldName = fieldName[5..];

        foreach (var constructor in classDeclarations
            .SelectMany(classDeclaration => classDeclaration.Members.OfType<ConstructorDeclarationSyntax>()))
        {
            foreach (var assignment in constructor.DescendantNodes().OfType<AssignmentExpressionSyntax>())
            {
                var leftName = assignment.Left.ToString().Trim();
                if (leftName.StartsWith("this.", StringComparison.Ordinal))
                    leftName = leftName[5..];
                if (leftName != fieldName || assignment.Right is not IdentifierNameSyntax parameter)
                    continue;

                for (var index = 0; index < constructor.ParameterList.Parameters.Count; index++)
                {
                    if (constructor.ParameterList.Parameters[index].Identifier.Text == parameter.Identifier.Text)
                        return index;
                }
            }
        }
        return -1;
    }

    private static bool IsAdoNetCommandExecutionMethod(string methodName)
        => methodName is "ExecuteNonQuery"
            or "ExecuteNonQueryAsync"
            or "ExecuteReader"
            or "ExecuteReaderAsync"
            or "ExecuteScalar"
            or "ExecuteScalarAsync";

    internal sealed record WrapperDefinition(
        string TypeIdentity,
        string ClassName,
        string MethodName,
        IReadOnlyList<string> Parameters,
        IReadOnlyList<string> ParameterTypes,
        int RequiredParameterCount,
        int CommandTextParameterIndex,
        int ModeParameterIndex,
        string? ConnectionExpression,
        bool AlwaysStoredProcedure,
        bool ReachesStoredProcedureSink,
        string? TerminalSink,
        int ConstructorConnectionParameterIndex,
        string MethodIdentity,
        string MethodSemantics,
        string? CommandTextLiteral,
        string AssemblyIdentity,
        string AssemblyRevision,
        string? UnresolvedReason,
        bool DeclaresConnectionAsLocal,
        string SourceFilePath)
    {
        /// <summary>
        /// True when this wrapper supplies the connection for a call made from
        /// <paramref name="callFilePath"/>. The connection expression is a variable name and
        /// connection_sources is keyed per file, so a wrapper only supplies a connection to
        /// calls in the file it is declared in -- never to a wrapper body read from a tree
        /// with no file of its own, such as a decompiled one.
        /// </summary>
        internal bool SuppliesConnectionTo(string? callFilePath)
            => DeclaresConnectionAsLocal
                && !string.IsNullOrWhiteSpace(ConnectionExpression)
                && !string.IsNullOrEmpty(SourceFilePath)
                && SourceFilePath == callFilePath;
    }
}