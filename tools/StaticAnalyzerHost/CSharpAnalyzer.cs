using System.Security.Cryptography;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

internal static class CSharpAnalyzer
{
    internal static CSharpAnalysis Analyze(string inputPath)
    {
        var bytes = File.ReadAllBytes(inputPath);
        var source = File.ReadAllText(inputPath);
        var root = CSharpSyntaxTree.ParseText(source, path: inputPath).GetCompilationUnitRoot();
        var methods = root.DescendantNodes().OfType<MethodDeclarationSyntax>().Select(method => new MethodSourceSpan(
            method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "",
            method.Identifier.Text,
            method.SpanStart,
            method.Span.End)).ToList();

        var dbInvocations = root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
            .Where(creation => IsSqlCommandType(creation.Type))
            .Select(DirectSqlClientAnalyzer.Analyze)
            .Where(invocation => invocation is not null)
            .Select(invocation => invocation!)
            .ToList();

        return new CSharpAnalysis(
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            methods,
            dbInvocations);
    }

    /// <summary>Matches only the exact type name `SqlCommand`, not unrelated types sharing the suffix (e.g. MySqlCommand).</summary>
    private static bool IsSqlCommandType(TypeSyntax type)
    {
        var typeName = type.ToString();
        var lastSegment = typeName.Split('.').Last();
        return lastSegment == "SqlCommand";
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

/// <summary>Raw facts for one direct `SqlCommand` setup; evidence rating happens in the Python gateway.</summary>
internal sealed record DirectSqlInvocation(
    string ClassName,
    string MethodName,
    string CommandTextKind,
    string? CommandText,
    bool CommandTypeStoredProcedure,
    string? ConnectionExpression,
    int StartOffset,
    int EndOffset);