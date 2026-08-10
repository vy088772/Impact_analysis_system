using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

internal static class CSharpAnalyzer
{
    internal static CSharpAnalysis Analyze(string inputPath)
        => Analyze(inputPath, new[] { ReadSource(inputPath) });

    internal static CSharpAnalysis Analyze(string inputPath, IReadOnlyList<CSharpSource> sourceFiles)
    {
        var bytes = File.ReadAllBytes(inputPath);
        var source = File.ReadAllText(inputPath);
        var root = sourceFiles.FirstOrDefault(sourceFile =>
            string.Equals(sourceFile.InputPath, inputPath, StringComparison.OrdinalIgnoreCase))?.Root
            ?? CSharpSyntaxTree.ParseText(source, path: inputPath).GetCompilationUnitRoot();
        var sourceRoots = sourceFiles.Select(sourceFile => sourceFile.Root).ToList();
        var wrapperMethods = WrapperAnalyzer.FindUsedWrapperMethods(sourceRoots);
        var methods = root.DescendantNodes().OfType<MethodDeclarationSyntax>().Select(method => new MethodSourceSpan(
            method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "",
            method.Identifier.Text,
            method.SpanStart,
            method.Span.End)).ToList();

        var dbInvocations = root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
            .Where(creation => IsSqlCommandType(creation.Type))
            .SelectMany(creation =>
            {
                var typeIdentity = GetTypeIdentity(
                    creation.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
                return DirectSqlClientAnalyzer.Analyze(creation)
                    .Where(invocation => !wrapperMethods.Contains((typeIdentity, invocation.MethodName)));
            })
            .ToList();
        dbInvocations.AddRange(WrapperAnalyzer.Analyze(root, sourceRoots));
        dbInvocations.AddRange(AdapterAnalyzer.Analyze(root, sourceRoots));

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

    internal static string GetTypeIdentity(ClassDeclarationSyntax? classDeclaration)
    {
        if (classDeclaration is null)
            return "";

        var namespaceParts = classDeclaration.Ancestors()
            .OfType<BaseNamespaceDeclarationSyntax>()
            .Reverse()
            .Select(namespaceDeclaration => namespaceDeclaration.Name.ToString());
        var typeParts = classDeclaration.AncestorsAndSelf()
            .OfType<TypeDeclarationSyntax>()
            .Reverse()
            .Select(typeDeclaration => typeDeclaration.Identifier.Text);
        return string.Join(".", namespaceParts.Concat(typeParts));
    }

    internal static string QualifyTypeIdentity(string typeName, MethodDeclarationSyntax caller)
    {
        var normalizedTypeName = typeName.Trim().Replace("global::", "", StringComparison.Ordinal);
        if (normalizedTypeName.Contains('.', StringComparison.Ordinal))
            return normalizedTypeName;

        var namespaceParts = caller.Ancestors()
            .OfType<BaseNamespaceDeclarationSyntax>()
            .Reverse()
            .Select(namespaceDeclaration => namespaceDeclaration.Name.ToString())
            .ToList();
        return string.Join(".", namespaceParts.Append(normalizedTypeName));
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

        var storedProcedureAssignments = propertyAssignments
            .Where(assignment => ((MemberAccessExpressionSyntax)assignment.Left).Name.Identifier.Text == "CommandType")
            .Where(assignment => IsStoredProcedureCommandType(assignment.Right))
            .ToList();

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
            var matchingStoredProcedureAssignments = storedProcedureAssignments
                .Where(assignment => SyntaxBranchAnalyzer.IsCompatible(
                    candidate.BranchContext,
                    SyntaxBranchAnalyzer.GetBranchContext(assignment)))
                .ToList();

            if (matchingStoredProcedureAssignments.Count == 0)
            {
                invocations.Add(CreateInvocation(
                    className,
                    method.Identifier.Text,
                    candidate,
                    false,
                    connectionExpression,
                    startOffset,
                    endOffset));
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
                    SyntaxBranchAnalyzer.Combine(
                        candidate.BranchContext,
                        SyntaxBranchAnalyzer.GetBranchContext(assignment))));
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

    private static DirectSqlInvocation CreateInvocation(
        string className,
        string methodName,
        CommandTextCandidate candidate,
        bool commandTypeStoredProcedure,
        string? connectionExpression,
        int startOffset,
        int endOffset,
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
            BranchContext: branchContext ?? candidate.BranchContext);

    private static string? ResolveVariableName(ObjectCreationExpressionSyntax creation)
    {
        if (creation.Parent is EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax declarator })
            return declarator.Identifier.Text;
        if (creation.Parent is AssignmentExpressionSyntax { Left: IdentifierNameSyntax identifier } assignment
            && assignment.Right == creation)
            return identifier.Identifier.Text;
        return null;
    }

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
                    allowVariableLookup: false))
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
                SyntaxBranchAnalyzer.GetBranchContext(anchor)),
        };
    }

    private static IReadOnlyList<CommandTextCandidate> ReadCommandTextCandidates(
        ExpressionSyntax? expression,
        MethodDeclarationSyntax method,
        SyntaxNode anchor,
        int position,
        bool allowVariableLookup)
    {
        if (allowVariableLookup)
            return ReadCommandTextCandidates(expression, method, anchor, position);

        var (kind, text) = ReadCommandText(expression);
        return new[]
        {
            new CommandTextCandidate(
                kind,
                text,
                SyntaxBranchAnalyzer.GetBranchContext(anchor)),
        };
    }

    /// <summary>Matches only an exact `CommandType.StoredProcedure` member access, not any value containing the substring.</summary>
    private static bool IsStoredProcedureCommandType(ExpressionSyntax expression)
        => expression is MemberAccessExpressionSyntax { Name.Identifier.Text: "StoredProcedure" };

    private sealed record CommandTextCandidate(
        string CommandTextKind,
        string? CommandText,
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

    internal static List<DirectSqlInvocation> Analyze(
        CompilationUnitSyntax root,
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var wrapperDefinitions = WrapperAnalyzer.GetDefinitions(sourceRoots);
        var invocations = new List<DirectSqlInvocation>();
        foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            var className = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
            foreach (var call in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                if (call.Expression is not MemberAccessExpressionSyntax member)
                    continue;
                if (WrapperAnalyzer.IsSourceWrapperInvocation(call, method, wrapperDefinitions))
                    continue;

                var methodName = member.Name.Identifier.Text;
                if (DapperMethods.Contains(methodName)
                    && LooksLikeDapperReceiver(member.Expression, method, call.SpanStart))
                    invocations.AddRange(AnalyzeDapperCall(call, method, className, member));
                else if (EntityFrameworkMethods.Contains(methodName)
                    && LooksLikeEntityFrameworkReceiver(member.Expression, method, call.SpanStart))
                    invocations.Add(AnalyzeEntityFrameworkCall(call, method, className, member));
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
            BranchContext: SyntaxBranchAnalyzer.Combine(callContext, candidate.BranchContext)))
            .ToList();
    }

    private static DirectSqlInvocation AnalyzeEntityFrameworkCall(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax method,
        string className,
        MemberAccessExpressionSyntax member)
    {
        var expression = call.ArgumentList.Arguments.ElementAtOrDefault(0)?.Expression;
        var (kind, text, mode) = ReadEntityFrameworkCommandText(expression);
        return new DirectSqlInvocation(
            className,
            method.Identifier.Text,
            kind,
            text,
            mode == "stored_procedure",
            member.Expression.ToString().Trim(),
            call.SpanStart,
            call.Span.End,
            InvocationKind: "entity_framework",
            WrapperMode: mode,
            MethodChain: new[] { method.Identifier.Text, member.Name.Identifier.Text },
            BranchContext: SyntaxBranchAnalyzer.GetBranchContext(call));
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

    private static (string Kind, string? Text, string Mode) ReadEntityFrameworkCommandText(
        ExpressionSyntax? expression)
    {
        if (expression is LiteralExpressionSyntax { Token.Value: string text })
        {
            var match = Regex.Match(
                text,
                @"^\s*EXEC(?:UTE)?\s+(?<name>(?:(?:\[[^\]]+\]|[A-Za-z_][\w$]*)\s*\.)*(?:\[[^\]]+\]|[A-Za-z_][\w$]*))",
                RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
            if (match.Success)
                return ("literal", match.Groups["name"].Value, "stored_procedure");
            return ("literal", text, LooksLikeInlineSql(text) ? "inline_sql" : "unknown");
        }

        return ("dynamic", null, "unknown");
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
    {
        var normalized = text.TrimStart();
        return normalized.StartsWith("SELECT ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("INSERT ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("UPDATE ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("DELETE ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("MERGE ", StringComparison.OrdinalIgnoreCase);
    }

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
                    SyntaxBranchAnalyzer.GetBranchContext(item.Assignment)))
                .ToList();
            if (resolved.Count > 0)
                return resolved;
        }

        return new[]
        {
            ReadCommandTextCandidate(expression, SyntaxBranchAnalyzer.GetBranchContext(anchor)),
        };
    }

    private static AdapterCommandTextCandidate ReadCommandTextCandidate(
        ExpressionSyntax? expression,
        IReadOnlyList<string> branchContext)
    {
        if (expression is LiteralExpressionSyntax { Token.Value: string text })
            return new AdapterCommandTextCandidate("literal", text, branchContext);
        return new AdapterCommandTextCandidate("dynamic", null, branchContext);
    }

    private sealed record AdapterCommandTextCandidate(
        string CommandTextKind,
        string? CommandText,
        IReadOnlyList<string> BranchContext);
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
    string? WrapperReceiverType = null);

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
    internal static bool IsSourceWrapperInvocation(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        IReadOnlyList<WrapperDefinition> wrappers)
    {
        var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(
            caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
        return ResolveDefinition(call, caller, callerTypeIdentity, wrappers) is not null;
    }

    internal static IReadOnlySet<(string ClassName, string MethodName)> FindUsedWrapperMethods(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var roots = sourceRoots.ToList();
        var wrappers = GetDefinitions(roots);
        return roots
            .SelectMany(sourceRoot => sourceRoot.DescendantNodes().OfType<MethodDeclarationSyntax>())
            .SelectMany(method =>
            {
                    var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(
                    method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
                return method.DescendantNodes()
                    .OfType<InvocationExpressionSyntax>()
                        .Select(call => ResolveDefinition(call, method, callerTypeIdentity, wrappers));
            })
            .Where(definition => definition is not null)
                    .Select(definition => (definition!.TypeIdentity, definition.MethodName))
            .ToHashSet();
    }

    internal static List<DirectSqlInvocation> Analyze(
        CompilationUnitSyntax root,
        IEnumerable<CompilationUnitSyntax> sourceRoots)
    {
        var wrappers = GetDefinitions(sourceRoots);

        var invocations = new List<DirectSqlInvocation>();
        foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            var callerClass = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
            var callerTypeIdentity = CSharpAnalyzer.GetTypeIdentity(
                method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault());
            foreach (var call in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var wrapper = ResolveDefinition(call, method, callerTypeIdentity, wrappers);
                if (wrapper is null)
                {
                    var unavailable = CreateUnavailableCandidate(call, method, callerClass);
                    if (unavailable is not null)
                        invocations.Add(unavailable);
                    continue;
                }

                var mode = ResolveMode(call, wrapper);
                if (mode == "inline_sql")
                    continue;

                var (commandTextKind, commandText) = ReadCommandText(call, wrapper);
                invocations.Add(new DirectSqlInvocation(
                    callerClass,
                    method.Identifier.Text,
                    commandTextKind,
                    commandText,
                    mode == "stored_procedure",
                    ResolveCallConnectionExpression(call, wrapper, method),
                    call.SpanStart,
                    call.Span.End,
                    "source_wrapper",
                    wrapper.ClassName,
                    wrapper.MethodName,
                    true,
                    wrapper.ReachesStoredProcedureSink,
                    mode,
                    new[] { method.Identifier.Text, wrapper.MethodName }));
            }
        }

        return invocations;
    }

    internal static List<WrapperDefinition> GetDefinitions(
        IEnumerable<CompilationUnitSyntax> sourceRoots)
        => sourceRoots.SelectMany(sourceRoot => sourceRoot.DescendantNodes()
            .OfType<MethodDeclarationSyntax>()
            .Select(CreateDefinition)
            .Where(definition => definition is not null)
            .Select(definition => definition!)
        ).ToList();

    private static DirectSqlInvocation? CreateUnavailableCandidate(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        string callerClass)
    {
        if (call.Expression is not MemberAccessExpressionSyntax member)
            return null;

        var commandText = call.ArgumentList.Arguments.ElementAtOrDefault(0)?.Expression;
        var mode = ResolveExternalSqlObjectMode(call, caller);
        if (mode == "inline_sql")
            return null;

        if (mode == "stored_procedure")
        {
            if (commandText is LiteralExpressionSyntax { Token.Value: string literalText })
            {
                if (LooksLikeInlineSql(literalText))
                    return null;

                return CreateUnavailableInvocation(
                    caller,
                    callerClass,
                    member,
                    "literal",
                    literalText,
                    true,
                    mode,
                    call);
            }

            return CreateUnavailableInvocation(
                caller,
                callerClass,
                member,
                "dynamic",
                null,
                true,
                mode,
                call);
        }

        if (commandText is not LiteralExpressionSyntax { Token.Value: string text }
            || LooksLikeInlineSql(text))
            return null;
        if (mode == "unknown" && !LooksLikeProcedureName(text))
            return null;

        return CreateUnavailableInvocation(
            caller,
            callerClass,
            member,
            "literal",
            text,
            false,
            mode,
            call);
    }

    private static DirectSqlInvocation CreateUnavailableInvocation(
        MethodDeclarationSyntax caller,
        string callerClass,
        MemberAccessExpressionSyntax member,
        string commandTextKind,
        string? commandText,
        bool commandTypeStoredProcedure,
        string mode,
        InvocationExpressionSyntax call)
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
            WrapperReceiverType: ResolveExternalReceiverType(call, caller));

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
        return ResolveUnknownCallMode(call, caller);
    }

    private static string ResolveUnknownCallMode(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller)
    {
        var commandTextExpression = call.ArgumentList.Arguments
            .ElementAtOrDefault(0)
            ?.Expression;
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
    {
        var normalized = text.TrimStart();
        return normalized.StartsWith("SELECT ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("INSERT ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("UPDATE ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("DELETE ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("EXEC ", StringComparison.OrdinalIgnoreCase)
            || normalized.StartsWith("EXECUTE ", StringComparison.OrdinalIgnoreCase);
    }

    private static bool LooksLikeProcedureName(string text)
    {
        var bare = text.Trim().Replace("[", "").Replace("]", "").Split('.').Last();
        return bare.StartsWith("sp", StringComparison.OrdinalIgnoreCase)
            || bare.StartsWith("usp", StringComparison.OrdinalIgnoreCase)
            || bare.StartsWith("proc", StringComparison.OrdinalIgnoreCase);
    }

    private static WrapperDefinition? CreateDefinition(MethodDeclarationSyntax method)
    {
        var command = method.DescendantNodes()
            .OfType<ObjectCreationExpressionSyntax>()
            .FirstOrDefault(creation => CSharpAnalyzer.IsSqlCommandType(creation.Type));
        if (command is null)
            return null;

        var commandVariable = ResolveVariableName(command);
        if (commandVariable is null)
            return null;

        var commandTypeAssignments = method.DescendantNodes()
            .OfType<AssignmentExpressionSyntax>()
            .Where(assignment => IsMemberAssignment(assignment, commandVariable, "CommandType"))
            .ToList();
        if (!commandTypeAssignments.Any(assignment => ContainsStoredProcedureMember(assignment.Right)))
            return null;

        var classDeclaration = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        var className = classDeclaration?.Identifier.Text ?? "";
        var typeIdentity = CSharpAnalyzer.GetTypeIdentity(classDeclaration);
        var parameters = method.ParameterList.Parameters.Select(parameter => parameter.Identifier.Text).ToList();
        var commandTextExpression = command.ArgumentList?.Arguments.ElementAtOrDefault(0)?.Expression;
        var connectionExpression = command.ArgumentList?.Arguments.ElementAtOrDefault(1)?.Expression?.ToString().Trim();
        foreach (var assignment in method.DescendantNodes().OfType<AssignmentExpressionSyntax>())
        {
            if (assignment.Left is not MemberAccessExpressionSyntax member
                || member.Expression.ToString().Trim() != commandVariable)
                continue;
            if (member.Name.Identifier.Text == "CommandText")
                commandTextExpression = assignment.Right;
            else if (member.Name.Identifier.Text == "Connection")
                connectionExpression = assignment.Right.ToString().Trim();
        }
        var commandTextParameter = commandTextExpression is IdentifierNameSyntax identifier
            ? identifier.Identifier.Text
            : null;
        var commandTextParameterIndex = parameters.IndexOf(commandTextParameter ?? "");
        var modeParameter = FindModeParameter(method, commandTypeAssignments, parameters);
        var modeParameterIndex = parameters.IndexOf(modeParameter ?? "");
        var alwaysStoredProcedure = modeParameter is null && commandTypeAssignments
            .Any(assignment => ContainsStoredProcedureMember(assignment.Right)
                && assignment.FirstAncestorOrSelf<IfStatementSyntax>() is null
                && assignment.FirstAncestorOrSelf<ConditionalExpressionSyntax>() is null);
        var constructorConnectionParameterIndex = FindConstructorConnectionParameterIndex(
            classDeclaration,
            connectionExpression);

        return new WrapperDefinition(
            typeIdentity,
            className,
            method.Identifier.Text,
            parameters,
            commandTextParameterIndex,
            modeParameterIndex,
            connectionExpression,
            alwaysStoredProcedure,
            ReachesStoredProcedureSink(method, commandVariable),
            constructorConnectionParameterIndex);
    }

    private static WrapperDefinition? ResolveDefinition(
        InvocationExpressionSyntax call,
        MethodDeclarationSyntax caller,
        string callerTypeIdentity,
        IReadOnlyList<WrapperDefinition> wrappers)
    {
        var methodName = call.Expression switch
        {
            MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
            IdentifierNameSyntax identifier => identifier.Identifier.Text,
            _ => "",
        };
        if (string.IsNullOrEmpty(methodName))
            return null;

        var receiverType = call.Expression is MemberAccessExpressionSyntax memberAccess
            ? ResolveReceiverType(memberAccess.Expression.ToString(), caller)
            : callerTypeIdentity;
        var candidates = wrappers
            .Where(wrapper => wrapper.MethodName == methodName)
            .Where(wrapper => string.IsNullOrEmpty(receiverType)
                || wrapper.TypeIdentity == receiverType
                || wrapper.ClassName == receiverType)
            .ToList();
        if (candidates.Count == 0 && !string.IsNullOrEmpty(receiverType))
        {
            var simpleTypeName = receiverType.Split('.').Last();
            candidates = wrappers
                .Where(wrapper => wrapper.MethodName == methodName && wrapper.ClassName == simpleTypeName)
                .ToList();
        }

        if (candidates.Count > 1)
        {
            var matchingArity = candidates
                .Where(wrapper => wrapper.Parameters.Count == call.ArgumentList.Arguments.Count)
                .ToList();
            if (matchingArity.Count == 1)
                return matchingArity[0];
        }
        return candidates.Count == 1 ? candidates[0] : null;
    }

    private static string? ResolveReceiverType(string receiver, MethodDeclarationSyntax caller)
    {
        receiver = receiver.Trim();
        if (receiver.StartsWith("this.", StringComparison.Ordinal))
            receiver = receiver[5..];

        var local = caller.DescendantNodes()
            .OfType<VariableDeclaratorSyntax>()
            .FirstOrDefault(variable => variable.Identifier.Text == receiver);
        if (local?.Initializer?.Value is ObjectCreationExpressionSyntax creation)
            return CSharpAnalyzer.QualifyTypeIdentity(creation.Type.ToString(), caller);

        var containingClass = caller.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
        var field = containingClass?.DescendantNodes()
            .OfType<FieldDeclarationSyntax>()
            .FirstOrDefault(declaration => declaration.Declaration.Variables.Any(variable => variable.Identifier.Text == receiver));
        return field is null
            ? null
            : CSharpAnalyzer.QualifyTypeIdentity(field.Declaration.Type.ToString(), caller);
    }

    private static string ResolveMode(InvocationExpressionSyntax call, WrapperDefinition wrapper)
    {
        if (wrapper.AlwaysStoredProcedure)
            return "stored_procedure";
        if (wrapper.ModeParameterIndex < 0)
            return "unknown";

        var argument = call.ArgumentList.Arguments.ElementAtOrDefault(wrapper.ModeParameterIndex)?.Expression;
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

    private static (string Kind, string? Text) ReadCommandText(
        InvocationExpressionSyntax call,
        WrapperDefinition wrapper)
    {
        var argument = call.ArgumentList.Arguments.ElementAtOrDefault(wrapper.CommandTextParameterIndex)?.Expression;
        if (argument is LiteralExpressionSyntax { Token.Value: string literalValue })
            return ("literal", literalValue);
        return ("dynamic", null);
    }

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

    private static bool ContainsStoredProcedureMember(ExpressionSyntax expression)
        => expression.DescendantNodesAndSelf()
            .OfType<MemberAccessExpressionSyntax>()
            .Any(member => member.Name.Identifier.Text == "StoredProcedure");

    private static string? ResolveVariableName(ObjectCreationExpressionSyntax creation)
    {
        if (creation.Parent is EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax declarator })
            return declarator.Identifier.Text;
        if (creation.Parent is AssignmentExpressionSyntax { Left: IdentifierNameSyntax identifier })
            return identifier.Identifier.Text;
        return null;
    }

    private static string? ResolveCallConnectionExpression(
        InvocationExpressionSyntax call,
        WrapperDefinition wrapper,
        MethodDeclarationSyntax caller)
    {
        if (call.Expression is not MemberAccessExpressionSyntax member)
            return wrapper.ConnectionExpression;

        var receiver = member.Expression.ToString().Trim();
        if (wrapper.ConstructorConnectionParameterIndex < 0)
            return receiver;

        var creation = caller.DescendantNodes()
            .OfType<VariableDeclaratorSyntax>()
            .Where(variable => variable.Identifier.Text == receiver)
            .Select(variable => variable.Initializer?.Value)
            .OfType<ObjectCreationExpressionSyntax>()
            .FirstOrDefault(candidate => LastTypeSegment(candidate.Type.ToString()) == wrapper.ClassName);
        var argument = creation?.ArgumentList?.Arguments.ElementAtOrDefault(
            wrapper.ConstructorConnectionParameterIndex)?.Expression;
        if (argument is LiteralExpressionSyntax literal && literal.IsKind(SyntaxKind.NullLiteralExpression))
            return receiver;
        return argument?.ToString().Trim() ?? receiver;
    }

    private static int FindConstructorConnectionParameterIndex(
        ClassDeclarationSyntax? classDeclaration,
        string? connectionExpression)
    {
        if (classDeclaration is null || string.IsNullOrWhiteSpace(connectionExpression))
            return -1;

        var fieldName = connectionExpression.Trim();
        if (fieldName.StartsWith("this.", StringComparison.Ordinal))
            fieldName = fieldName[5..];

        foreach (var constructor in classDeclaration.Members.OfType<ConstructorDeclarationSyntax>())
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

    private static bool ReachesStoredProcedureSink(MethodDeclarationSyntax method, string commandVariable)
        => method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Any(invocation => invocation.Expression is MemberAccessExpressionSyntax member
                && member.Expression.ToString().Trim() == commandVariable
                && IsAdoNetExecutionMethod(member.Name.Identifier.Text));

    private static bool IsAdoNetExecutionMethod(string methodName)
        => methodName.StartsWith("Execute", StringComparison.Ordinal)
            || methodName.Equals("Fill", StringComparison.Ordinal);

    private static string LastTypeSegment(string typeName)
        => typeName.Split('.').Last().Trim();

    internal sealed record WrapperDefinition(
        string TypeIdentity,
        string ClassName,
        string MethodName,
        IReadOnlyList<string> Parameters,
        int CommandTextParameterIndex,
        int ModeParameterIndex,
        string? ConnectionExpression,
        bool AlwaysStoredProcedure,
        bool ReachesStoredProcedureSink,
        int ConstructorConnectionParameterIndex);
}