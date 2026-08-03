using System.Security.Cryptography;
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
            .Select(creation => (Creation: creation, Invocation: DirectSqlClientAnalyzer.Analyze(creation)))
            .Where(item => item.Invocation is not null)
            .Where(item => !wrapperMethods.Contains((
                GetTypeIdentity(item.Creation.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()),
                item.Invocation!.MethodName)))
            .Select(item => item.Invocation!)
            .ToList();
        dbInvocations.AddRange(WrapperAnalyzer.Analyze(root, sourceRoots));

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
    internal static DirectSqlInvocation? Analyze(ObjectCreationExpressionSyntax creation)
    {
        var method = creation.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault();
        if (method is null)
            return null;

        var className = method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "";
        var variableName = ResolveVariableName(creation);
        var arguments = creation.ArgumentList?.Arguments ?? default;
        var textArgument = arguments.Count > 0 ? arguments[0].Expression : null;
        var connectionArgument = arguments.Count > 1 ? arguments[1].Expression : null;

        var (commandTextKind, commandText) = ReadCommandText(textArgument);
        var connectionExpression = connectionArgument?.ToString().Trim();
        var commandTypeStoredProcedure = false;

        var relevantStatements = new List<StatementSyntax>();
        var creationStatement = creation.FirstAncestorOrSelf<StatementSyntax>();
        if (creationStatement is not null)
            relevantStatements.Add(creationStatement);

        if (variableName is not null)
        {
            var assignments = method.DescendantNodes().OfType<AssignmentExpressionSyntax>()
                .Where(assignment => assignment.Left is MemberAccessExpressionSyntax member
                    && member.Expression.ToString() == variableName);

            foreach (var assignment in assignments)
            {
                var propertyName = ((MemberAccessExpressionSyntax)assignment.Left).Name.Identifier.Text;
                var statement = assignment.FirstAncestorOrSelf<StatementSyntax>();

                if (propertyName == "CommandType")
                {
                    if (IsStoredProcedureCommandType(assignment.Right))
                    {
                        commandTypeStoredProcedure = true;
                        if (statement is not null)
                            relevantStatements.Add(statement);
                    }
                }
                else if (propertyName == "CommandText")
                {
                    (commandTextKind, commandText) = ReadCommandText(assignment.Right);
                    if (statement is not null)
                        relevantStatements.Add(statement);
                }
                else if (propertyName == "Connection")
                {
                    connectionExpression = assignment.Right.ToString().Trim();
                    if (statement is not null)
                        relevantStatements.Add(statement);
                }
            }
        }

        SyntaxNode fallbackSpan = (SyntaxNode?)creation.FirstAncestorOrSelf<StatementSyntax>() ?? creation;
        var startOffset = relevantStatements.Count > 0
            ? relevantStatements.Min(statement => statement.SpanStart)
            : fallbackSpan.SpanStart;
        var endOffset = relevantStatements.Count > 0
            ? relevantStatements.Max(statement => statement.Span.End)
            : fallbackSpan.Span.End;

        return new DirectSqlInvocation(
            className,
            method.Identifier.Text,
            commandTextKind,
            commandText,
            commandTypeStoredProcedure,
            connectionExpression,
            startOffset,
            endOffset);
    }

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

    /// <summary>Matches only an exact `CommandType.StoredProcedure` member access, not any value containing the substring.</summary>
    private static bool IsStoredProcedureCommandType(ExpressionSyntax expression)
        => expression is MemberAccessExpressionSyntax { Name.Identifier.Text: "StoredProcedure" };
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
    IReadOnlyList<string>? MethodChain = null);

internal static class WrapperAnalyzer
{
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

    private static List<WrapperDefinition> GetDefinitions(
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
        if (commandText is not LiteralExpressionSyntax { Token.Value: string text }
            || LooksLikeInlineSql(text))
            return null;

        var mode = ResolveUnknownCallMode(call);
        if (mode == "inline_sql")
            return null;
        if (mode == "unknown" && !LooksLikeProcedureName(text))
            return null;

        return new DirectSqlInvocation(
            callerClass,
            caller.Identifier.Text,
            "literal",
            text,
            mode == "stored_procedure",
            member.Expression.ToString().Trim(),
            call.SpanStart,
            call.Span.End,
            "source_wrapper",
            null,
            member.Name.Identifier.Text,
            false,
            false,
            mode,
            new[] { caller.Identifier.Text, member.Name.Identifier.Text });
    }

    private static string ResolveUnknownCallMode(InvocationExpressionSyntax call)
    {
        var hasStoredMode = call.ArgumentList.Arguments.Any(argument => IsStoredModeLiteral(argument.Expression));
        var hasInlineMode = call.ArgumentList.Arguments.Any(argument => IsInlineModeLiteral(argument.Expression));
        if (hasStoredMode)
            return "stored_procedure";
        if (hasInlineMode)
            return "inline_sql";
        return "unknown";
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

    private sealed record WrapperDefinition(
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