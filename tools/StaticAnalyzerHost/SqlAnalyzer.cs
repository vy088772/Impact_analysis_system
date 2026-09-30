using System.Collections;
using System.Reflection;
using Microsoft.SqlServer.TransactSql.ScriptDom;

internal static class SqlAnalyzer
{
    internal static SqlAnalysis Analyze(string inputPath)
    {
        var source = File.ReadAllText(inputPath);
        using var reader = new StringReader(source);
        var fragment = new TSql160Parser(initialQuotedIdentifiers: true).Parse(reader, out var errors);
        var operations = fragment is null
            ? new List<SqlOperation>()
            : new SqlOperationExtractor(source, inputPath).Extract(fragment);

        return new SqlAnalysis(
            operations,
            errors.Select(error => new SqlParseError(error.Line, error.Message)).ToList());
    }
}

internal sealed class SqlOperationExtractor
{
    private readonly string _source;
    private readonly string _sourcePath;

    internal SqlOperationExtractor(string source, string sourcePath)
    {
        _source = source;
        _sourcePath = sourcePath;
    }

    internal List<SqlOperation> Extract(TSqlFragment root)
    {
        var module = FindModule(root) ?? new SqlModuleIdentity(
            "unknown",
            "",
            Path.GetFileNameWithoutExtension(_sourcePath));
        var candidates = new List<SqlOperationCandidate>();
        Visit(root, module, new List<string>(), candidates);

        return candidates
            .OrderBy(candidate => candidate.Fragment.StartOffset)
            .Select((candidate, index) => candidate.ToOperation(index + 1, module, CreateLocation))
            .ToList();
    }

    private void Visit(
        TSqlFragment fragment,
        SqlModuleIdentity module,
        IReadOnlyList<string> branchPath,
        ICollection<SqlOperationCandidate> candidates)
    {
        if (fragment is null)
            return;

        if (IsExecute(fragment))
        {
            candidates.Add(CreateExecuteCandidate(fragment, module, branchPath));
            return;
        }

        if (IsDml(fragment))
        {
            candidates.Add(CreateCandidate(fragment, module, branchPath));
            return;
        }

        if (fragment.GetType().Name == "IfStatement")
        {
            var predicate = GetFragmentProperty(fragment, "Predicate");
            var predicateText = predicate is null ? "" : Text(predicate);
            var thenStatement = GetFragmentProperty(fragment, "ThenStatement");
            var elseStatement = GetFragmentProperty(fragment, "ElseStatement");

            if (thenStatement is not null)
                Visit(thenStatement, module, Append(branchPath, $"IF {predicateText}".Trim()), candidates);
            if (elseStatement is not null)
            {
                var elseCondition = predicateText.Length == 0
                    ? "ELSE"
                    : $"ELSE (NOT ({predicateText}))";
                Visit(elseStatement, module, Append(branchPath, elseCondition), candidates);
            }
            return;
        }

        if (fragment.GetType().Name == "TryCatchStatement")
        {
            var tryStatements = GetFragmentProperty(fragment, "TryStatements");
            var catchStatements = GetFragmentProperty(fragment, "CatchStatements");
            if (tryStatements is not null)
                Visit(tryStatements, module, Append(branchPath, "TRY"), candidates);
            if (catchStatements is not null)
                Visit(catchStatements, module, Append(branchPath, "CATCH"), candidates);
            return;
        }

        if (fragment.GetType().Name == "WhileStatement")
        {
            var predicate = GetFragmentProperty(fragment, "Predicate");
            var statement = GetFragmentProperty(fragment, "Statement");
            var predicateText = predicate is null ? "" : Text(predicate);
            if (statement is not null)
                Visit(statement, module, Append(branchPath, $"WHILE {predicateText}".Trim()), candidates);
            return;
        }

        foreach (var child in ChildFragments(fragment).OrderBy(child => child.StartOffset))
            Visit(child, module, branchPath, candidates);
    }

    private SqlOperationCandidate CreateCandidate(
        TSqlFragment fragment,
        SqlModuleIdentity module,
        IReadOnlyList<string> branchPath)
    {
        var operationType = fragment.GetType().Name switch
        {
            "SelectStatement" => "SELECT",
            "InsertStatement" => "INSERT",
            "UpdateStatement" => "UPDATE",
            "DeleteStatement" => "DELETE",
            _ => "UNKNOWN",
        };
        var readTables = new List<SqlObjectReference>();
        var writeTables = new List<SqlObjectReference>();
        var unresolvedWriteTargets = new List<string>();
        var readColumns = new List<string>();
        var writtenColumns = new List<string>();
        var functionReferences = new List<SqlObjectReference>();
        string? where = null;
        // The CTE names come from the whole statement, so its main query, its INSERT source,
        // and its UPDATE or DELETE FROM clause skip them as well as the WITH clause does.
        var cteNames = ReadCteNames(fragment);

        switch (operationType)
        {
            case "SELECT":
            {
                var queryExpression = GetFragmentProperty(fragment, "QueryExpression");
                CollectReferences(queryExpression, readTables, cteNames);
                CollectColumns(queryExpression, readColumns);
                CollectFunctionReferences(queryExpression, functionReferences);
                var selectCtes = GetFragmentProperty(fragment, "WithCtesAndXmlNamespaces");
                CollectReferences(selectCtes, readTables, cteNames);
                CollectColumns(selectCtes, readColumns);
                CollectFunctionReferences(selectCtes, functionReferences);
                var into = GetFragmentProperty(fragment, "Into");
                if (into is not null)
                {
                    operationType = "SELECT_INTO";
                    AddObjectName(into, writeTables);
                }
                where = ExtractWhere(queryExpression);
                break;
            }
            case "INSERT":
            {
                var specification = GetFragmentProperty(fragment, "InsertSpecification");
                AddObjectName(GetFragmentProperty(specification, "Target"), writeTables);
                CollectColumns(GetPropertyValue(specification, "Columns"), writtenColumns);
                var source = GetFragmentProperty(specification, "InsertSource");
                CollectReferences(source, readTables, cteNames);
                CollectColumns(source, readColumns);
                CollectFunctionReferences(source, functionReferences);
                CollectReferences(GetFragmentProperty(fragment, "WithCtesAndXmlNamespaces"), readTables, cteNames);
                CollectColumns(GetFragmentProperty(fragment, "WithCtesAndXmlNamespaces"), readColumns);
                CollectFunctionReferences(GetFragmentProperty(fragment, "WithCtesAndXmlNamespaces"), functionReferences);
                break;
            }
            case "UPDATE":
            {
                var specification = GetFragmentProperty(fragment, "UpdateSpecification");
                var fromClause = GetFragmentProperty(specification, "FromClause");
                AddWriteTarget(GetFragmentProperty(specification, "Target"), fromClause, cteNames, writeTables, unresolvedWriteTargets);
                CollectReferences(fromClause, readTables, cteNames);
                CollectColumns(fromClause, readColumns);
                CollectFunctionReferences(fromClause, functionReferences);
                var whereClause = GetFragmentProperty(specification, "WhereClause");
                where = ExtractWhereClause(whereClause);
                CollectColumns(whereClause, readColumns);
                CollectFunctionReferences(whereClause, functionReferences);
                CollectColumns(GetPropertyValue(specification, "SetClauses"), readColumns);
                CollectFunctionReferences(GetPropertyValue(specification, "SetClauses"), functionReferences);
                var updateCtes = GetFragmentProperty(fragment, "WithCtesAndXmlNamespaces");
                CollectReferences(updateCtes, readTables, cteNames);
                CollectColumns(updateCtes, readColumns);
                CollectFunctionReferences(updateCtes, functionReferences);
                CollectWrittenUpdateColumns(GetPropertyValue(specification, "SetClauses"), writtenColumns);
                RemoveWrittenTables(readTables, writeTables);
                break;
            }
            case "DELETE":
            {
                var specification = GetFragmentProperty(fragment, "DeleteSpecification");
                var fromClause = GetFragmentProperty(specification, "FromClause");
                AddWriteTarget(GetFragmentProperty(specification, "Target"), fromClause, cteNames, writeTables, unresolvedWriteTargets);
                CollectReferences(fromClause, readTables, cteNames);
                CollectColumns(fromClause, readColumns);
                CollectFunctionReferences(fromClause, functionReferences);
                var whereClause = GetFragmentProperty(specification, "WhereClause");
                where = ExtractWhereClause(whereClause);
                CollectColumns(whereClause, readColumns);
                CollectFunctionReferences(whereClause, functionReferences);
                var deleteCtes = GetFragmentProperty(fragment, "WithCtesAndXmlNamespaces");
                CollectReferences(deleteCtes, readTables, cteNames);
                CollectColumns(deleteCtes, readColumns);
                CollectFunctionReferences(deleteCtes, functionReferences);
                RemoveWrittenTables(readTables, writeTables);
                break;
            }
        }

        return new SqlOperationCandidate(
            fragment,
            operationType,
            new List<string>(branchPath),
            where,
            readTables,
            writeTables,
            readColumns,
            writtenColumns,
            functionReferences: functionReferences,
            unresolvedWriteTargets: unresolvedWriteTargets);
    }

    private SqlOperationCandidate CreateExecuteCandidate(
        TSqlFragment fragment,
        SqlModuleIdentity module,
        IReadOnlyList<string> branchPath)
    {
        var specification = GetFragmentProperty(fragment, "ExecuteSpecification");
        var executableEntity = GetFragmentProperty(specification, "ExecutableEntity");
        var callTargets = new List<SqlObjectReference>();
        if (executableEntity is not null)
        {
            var procedureReferenceName = GetFragmentProperty(executableEntity, "ProcedureReference");
            var procedureReference = GetFragmentProperty(procedureReferenceName, "ProcedureReference")
                ?? procedureReferenceName;
            AddObjectName(GetFragmentProperty(procedureReference, "Name"), callTargets);
        }
        var dynamicSql = callTargets.Count == 0;

        return new SqlOperationCandidate(
            fragment,
            dynamicSql ? "DYNAMIC_SQL" : "CALL",
            new List<string>(branchPath),
            null,
            new List<SqlObjectReference>(),
            new List<SqlObjectReference>(),
            new List<string>(),
            new List<string>(),
            callTargets,
            dynamicSql);
    }

    private SqlModuleIdentity? FindModule(TSqlFragment root)
    {
        var moduleFragment = Descendants(root)
            .FirstOrDefault(fragment => IsModule(fragment));
        if (moduleFragment is null)
            return null;

        var moduleType = moduleFragment.GetType().Name switch
        {
            "CreateProcedureStatement" or "AlterProcedureStatement" or "CreateOrAlterProcedureStatement" => "stored_procedure",
            "CreateViewStatement" or "AlterViewStatement" or "CreateOrAlterViewStatement" => "view",
            "CreateFunctionStatement" or "AlterFunctionStatement" or "CreateOrAlterFunctionStatement" => "function",
            _ => "unknown",
        };
        var nameFragment = moduleType switch
        {
            "stored_procedure" => GetFragmentProperty(moduleFragment, "ProcedureReference") is { } reference
                ? GetFragmentProperty(reference, "Name")
                : null,
            "view" => GetFragmentProperty(moduleFragment, "SchemaObjectName"),
            "function" => GetFragmentProperty(moduleFragment, "Name"),
            _ => null,
        };
        // A module cannot name the Database that holds it, so its identity keeps no database.
        var moduleName = ReadObjectName(nameFragment);
        return new SqlModuleIdentity(moduleType, moduleName.Schema, moduleName.Name);
    }

    private static bool IsModule(TSqlFragment fragment)
        => fragment.GetType().Name is
            "CreateProcedureStatement" or "AlterProcedureStatement" or "CreateOrAlterProcedureStatement" or
            "CreateViewStatement" or "AlterViewStatement" or "CreateOrAlterViewStatement" or
            "CreateFunctionStatement" or "AlterFunctionStatement" or "CreateOrAlterFunctionStatement";

    private static bool IsDml(TSqlFragment fragment)
        => fragment.GetType().Name is "SelectStatement" or "InsertStatement" or "UpdateStatement" or "DeleteStatement";

    private static bool IsExecute(TSqlFragment fragment)
        => fragment.GetType().Name == "ExecuteStatement";

    private IEnumerable<TSqlFragment> Descendants(TSqlFragment fragment)
    {
        yield return fragment;
        foreach (var child in ChildFragments(fragment).OrderBy(child => child.StartOffset))
        {
            foreach (var descendant in Descendants(child))
                yield return descendant;
        }
    }

    // The target of an UPDATE or DELETE can name an alias of the FROM clause. A bare target
    // that matches an alias becomes the object behind that alias. A subquery or a CTE gives
    // no table, so the alias goes to the unresolved targets and the analyzer guesses nothing.
    private void AddWriteTarget(
        TSqlFragment? target,
        TSqlFragment? fromClause,
        ISet<string> cteNames,
        ICollection<SqlObjectReference> writeTables,
        ICollection<string> unresolvedWriteTargets)
    {
        var targetName = ReadObjectName(GetFragmentProperty(target, "SchemaObject"));
        if (target?.GetType().Name != "NamedTableReference" || !IsBare(targetName))
        {
            AddObjectName(target, writeTables);
            return;
        }

        var aliased = FindFromClauseAlias(fromClause, targetName.Name);
        if (aliased is null)
        {
            // A bare target that names a CTE writes through the CTE, so no table is known.
            if (cteNames.Contains(targetName.Name))
                AddUnique(unresolvedWriteTargets, targetName.Name);
            else
                AddObjectName(target, writeTables);
            return;
        }

        // A direct write to an @table variable writes nothing, and so does its alias.
        if (aliased.GetType().Name == "VariableTableReference")
            return;
        var behind = aliased.GetType().Name == "NamedTableReference"
            ? ReadObjectName(GetFragmentProperty(aliased, "SchemaObject"))
            : null;
        if (behind is null || (IsBare(behind) && cteNames.Contains(behind.Name)))
            AddUnique(unresolvedWriteTargets, targetName.Name);
        else if (behind.Name.Length > 0)
            AddUnique(writeTables, behind);
    }

    private static bool IsBare(SqlObjectReference reference)
        => reference.Server.Length == 0 && reference.Database.Length == 0 && reference.Schema.Length == 0;

    private static TSqlFragment? FindFromClauseAlias(TSqlFragment? fromClause, string aliasName)
        => Fragments(GetPropertyValue(fromClause, "TableReferences"))
            .SelectMany(JoinedTableReferences)
            .FirstOrDefault(reference =>
                string.Equals(
                    ReadIdentifierText(GetPropertyValue(reference, "Alias")),
                    aliasName,
                    StringComparison.OrdinalIgnoreCase));

    // The table references that one item of a FROM clause joins. A join holds two table
    // references, and a join in parentheses holds one join. Any other table reference is one
    // source with its own alias. A derived table is a scope of its own, so the walk stops there.
    private static IEnumerable<TSqlFragment> JoinedTableReferences(TSqlFragment tableReference)
    {
        var joined = new[] { "FirstTableReference", "SecondTableReference", "Join" }
            .Select(property => GetFragmentProperty(tableReference, property))
            .OfType<TSqlFragment>()
            .ToList();
        return joined.Count == 0 ? new[] { tableReference } : joined.SelectMany(JoinedTableReferences);
    }

    private ISet<string> ReadCteNames(TSqlFragment statement)
        => Descendants(statement)
            .Where(child => child.GetType().Name == "CommonTableExpression")
            .Select(child => ReadIdentifierText(GetPropertyValue(child, "ExpressionName")))
            .Where(name => name.Length > 0)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

    private void CollectReferences(
        object? value,
        ICollection<SqlObjectReference> references,
        ISet<string> cteNames)
    {
        if (value is not TSqlFragment fragment)
            return;

        foreach (var child in Descendants(fragment))
        {
            var typeName = child.GetType().Name;
            if (typeName == "NamedTableReference")
            {
                AddObjectName(GetFragmentProperty(child, "SchemaObject"), references, cteNames);
            }
            else if (typeName == "SchemaObjectFunctionTableReference")
            {
                AddObjectName(GetFragmentProperty(child, "SchemaObject"), references, cteNames);
            }
        }
    }

    private void CollectColumns(object? value, ICollection<string> columns)
    {
        foreach (var fragment in Fragments(value))
        {
            foreach (var child in Descendants(fragment))
            {
                if (child.GetType().Name != "ColumnReferenceExpression")
                    continue;
                var multipart = GetPropertyValue(child, "MultiPartIdentifier");
                var name = ReadLastIdentifier(multipart);
                AddUnique(columns, name);
            }
        }
    }

    private void CollectFunctionReferences(object? value, ICollection<SqlObjectReference> references)
    {
        foreach (var fragment in Fragments(value))
        {
            foreach (var child in Descendants(fragment))
            {
                if (child.GetType().Name != "FunctionCall")
                    continue;
                var functionName = ReadIdentifierText(GetPropertyValue(child, "FunctionName"));
                var callTarget = GetFragmentProperty(child, "CallTarget");
                var identifiers = GetPropertyValue(GetPropertyValue(callTarget, "MultiPartIdentifier"), "Identifiers") as IEnumerable;
                var targetParts = identifiers is null
                    ? new List<string>()
                    : identifiers.Cast<object?>().Select(ReadIdentifierText).ToList();
                if (functionName.Length == 0 || targetParts.All(part => part.Length == 0))
                    continue;
                // The call target's identifiers fill server, database, and schema from the right.
                string PartFromRight(int offset) => targetParts.Count >= offset ? targetParts[^offset] : "";
                AddUnique(references, new SqlObjectReference(PartFromRight(3), PartFromRight(2), PartFromRight(1), functionName));
            }
        }
    }

    private static void CollectWrittenUpdateColumns(object? value, ICollection<string> columns)
    {
        if (value is not IEnumerable items)
            return;

        foreach (var item in items)
        {
            if (item is not TSqlFragment fragment || fragment.GetType().Name != "AssignmentSetClause")
                continue;
            var column = GetFragmentProperty(fragment, "Column");
            AddUnique(columns, ReadLastIdentifier(GetPropertyValue(column, "MultiPartIdentifier")));
        }
    }

    private string? ExtractWhere(object? queryExpression)
        => queryExpression is TSqlFragment fragment && fragment.GetType().Name == "QuerySpecification"
            ? ExtractWhereClause(GetFragmentProperty(fragment, "WhereClause"))
            : null;

    private string? ExtractWhereClause(TSqlFragment? whereClause)
    {
        var searchCondition = GetFragmentProperty(whereClause, "SearchCondition");
        return searchCondition is null ? null : Text(searchCondition);
    }

    private void AddObjectName(object? value, ICollection<SqlObjectReference> target, ISet<string>? excluded = null)
    {
        if (value is TSqlFragment fragment && fragment.GetType().Name is "NamedTableReference" or "SchemaObjectFunctionTableReference")
            value = GetFragmentProperty(fragment, "SchemaObject");
        var reference = ReadObjectName(value);
        if (reference.Name.Length == 0 || reference.Name.StartsWith("@", StringComparison.Ordinal))
            return;
        // The excluded names are common-table-expression names, and T-SQL cannot qualify one,
        // so only a bare name can match.
        if (IsBare(reference) && excluded?.Contains(reference.Name) == true)
            return;
        AddUnique(target, reference);
    }

    // The named ScriptDom properties tell `database..name` from `schema.name`; the identifier
    // list omits an unstated part, so its positions cannot. An unstated part stays empty.
    private static SqlObjectReference ReadObjectName(object? value)
        => new(
            ReadIdentifierText(GetPropertyValue(value, "ServerIdentifier")),
            ReadIdentifierText(GetPropertyValue(value, "DatabaseIdentifier")),
            ReadIdentifierText(GetPropertyValue(value, "SchemaIdentifier")),
            ReadIdentifierText(GetPropertyValue(value, "BaseIdentifier")));

    private static string ReadLastIdentifier(object? value)
    {
        var identifiers = GetPropertyValue(value, "Identifiers") as IEnumerable;
        if (identifiers is null)
            return "";
        var values = identifiers.Cast<object?>().Select(ReadIdentifierText).Where(name => name.Length > 0).ToList();
        return values.Count == 0 ? "" : values[^1];
    }

    private static string ReadIdentifierText(object? value)
    {
        if (value is null)
            return "";
        var identifierValue = GetPropertyValue(value, "Value")?.ToString();
        return CleanIdentifier(identifierValue ?? value.ToString() ?? "");
    }

    private string Text(TSqlFragment fragment)
    {
        var start = Math.Clamp(fragment.StartOffset, 0, _source.Length);
        var length = Math.Clamp(fragment.FragmentLength, 0, _source.Length - start);
        return _source.Substring(start, length).Trim();
    }

    private SqlSourceLocation CreateLocation(TSqlFragment fragment)
    {
        var start = Math.Clamp(fragment.StartOffset, 0, _source.Length);
        var length = Math.Clamp(fragment.FragmentLength, 0, _source.Length - start);
        var (endLine, endColumn) = PositionAt(start + length);
        return new SqlSourceLocation(
            _sourcePath,
            fragment.StartLine,
            fragment.StartColumn,
            start,
            length,
            endLine,
            endColumn);
    }

    private (int Line, int Column) PositionAt(int offset)
    {
        var line = 1;
        var column = 1;
        for (var index = 0; index < offset; index++)
        {
            if (_source[index] == '\n')
            {
                line++;
                column = 1;
            }
            else
            {
                column++;
            }
        }
        return (line, column);
    }

    private static IReadOnlyList<string> Append(IReadOnlyList<string> values, string value)
    {
        var result = values.ToList();
        if (value.Length > 0)
            result.Add(value);
        return result;
    }

    private static IEnumerable<TSqlFragment> ChildFragments(TSqlFragment fragment)
    {
        foreach (var property in fragment.GetType().GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (!property.CanRead || property.Name == "ScriptTokenStream" || property.GetIndexParameters().Length > 0)
                continue;

            object? value;
            try
            {
                value = property.GetValue(fragment);
            }
            catch
            {
                continue;
            }

            if (value is TSqlFragment child)
            {
                yield return child;
                continue;
            }

            if (value is not IEnumerable items)
                continue;
            foreach (var item in items)
            {
                if (item is TSqlFragment childItem)
                    yield return childItem;
            }
        }
    }

    private static IEnumerable<TSqlFragment> Fragments(object? value)
    {
        if (value is TSqlFragment fragment)
        {
            yield return fragment;
            yield break;
        }

        if (value is not IEnumerable items)
            yield break;
        foreach (var item in items)
        {
            foreach (var child in Fragments(item))
                yield return child;
        }
    }

    private static TSqlFragment? GetFragmentProperty(object? value, string propertyName)
        => GetPropertyValue(value, propertyName) as TSqlFragment;

    private static object? GetPropertyValue(object? value, string propertyName)
        => value?.GetType().GetProperty(propertyName, BindingFlags.Public | BindingFlags.Instance)?.GetValue(value);

    private static void RemoveWrittenTables(ICollection<SqlObjectReference> reads, IEnumerable<SqlObjectReference> writes)
    {
        var written = writes.ToList();
        foreach (var read in reads.Where(read => written.Any(write => write.SameParts(read))).ToList())
            reads.Remove(read);
    }

    private static void AddUnique(ICollection<string> values, string value)
    {
        if (value.Length > 0 && !values.Contains(value, StringComparer.OrdinalIgnoreCase))
            values.Add(value);
    }

    private static void AddUnique(ICollection<SqlObjectReference> values, SqlObjectReference value)
    {
        if (!values.Any(existing => existing.SameParts(value)))
            values.Add(value);
    }

    private static string CleanIdentifier(string value)
        => value.Trim().Trim('[', ']', '"');
}

internal sealed class SqlOperationCandidate
{
    internal SqlOperationCandidate(
        TSqlFragment fragment,
        string operationType,
        List<string> branchPath,
        string? where,
        List<SqlObjectReference> readTables,
        List<SqlObjectReference> writeTables,
        List<string> readColumns,
        List<string> writtenColumns,
        List<SqlObjectReference>? callTargets = null,
        bool dynamicSql = false,
        List<SqlObjectReference>? functionReferences = null,
        List<string>? unresolvedWriteTargets = null)
    {
        Fragment = fragment;
        OperationType = operationType;
        BranchPath = branchPath;
        Where = where;
        ReadTables = readTables;
        WriteTables = writeTables;
        ReadColumns = readColumns;
        WrittenColumns = writtenColumns;
        CallTargets = callTargets ?? new List<SqlObjectReference>();
        DynamicSql = dynamicSql;
        FunctionReferences = functionReferences ?? new List<SqlObjectReference>();
        UnresolvedWriteTargets = unresolvedWriteTargets ?? new List<string>();
    }

    internal TSqlFragment Fragment { get; }
    private string OperationType { get; }
    private List<string> BranchPath { get; }
    private string? Where { get; }
    private List<SqlObjectReference> ReadTables { get; }
    private List<SqlObjectReference> WriteTables { get; }
    private List<string> ReadColumns { get; }
    private List<string> WrittenColumns { get; }
    private List<SqlObjectReference> CallTargets { get; }
    private bool DynamicSql { get; }
    private List<SqlObjectReference> FunctionReferences { get; }
    private List<string> UnresolvedWriteTargets { get; }

    internal SqlOperation ToOperation(
        int sequence,
        SqlModuleIdentity module,
        Func<TSqlFragment, SqlSourceLocation> locationFactory)
        => new(
            OperationType,
            module,
            sequence,
            BranchPath,
            Conditions(),
            Where,
            ReadTables,
            WriteTables,
            UnresolvedWriteTargets,
            ReadColumns,
            WrittenColumns,
            FunctionReferences,
            CallTargets,
            DynamicSql,
            locationFactory(Fragment));

    private List<string> Conditions()
    {
        var conditions = BranchPath.ToList();
        if (!string.IsNullOrWhiteSpace(Where))
            conditions.Add(Where!);
        return conditions;
    }
}

internal sealed record SqlAnalysis(List<SqlOperation> Operations, List<SqlParseError> ParseErrors);
internal sealed record SqlParseError(int Line, string Message);
internal sealed record SqlModuleIdentity(string Type, string Schema, string Name);

// One object reference as the statement writes it. All four parts are always present, and an
// unstated part is an empty string: the host reads syntax only, so it never fills one.
internal sealed record SqlObjectReference(string Server, string Database, string Schema, string Name)
{
    internal bool SameParts(SqlObjectReference other)
        => string.Equals(Server, other.Server, StringComparison.OrdinalIgnoreCase)
            && string.Equals(Database, other.Database, StringComparison.OrdinalIgnoreCase)
            && string.Equals(Schema, other.Schema, StringComparison.OrdinalIgnoreCase)
            && string.Equals(Name, other.Name, StringComparison.OrdinalIgnoreCase);
}
internal sealed record SqlSourceLocation(
    string SourcePath,
    int StartLine,
    int StartColumn,
    int StartOffset,
    int Length,
    int EndLine,
    int EndColumn);
internal sealed record SqlOperation(
    string OperationType,
    SqlModuleIdentity Module,
    int Sequence,
    List<string> BranchPath,
    List<string> Conditions,
    string? Where,
    List<SqlObjectReference> ReadTables,
    List<SqlObjectReference> WriteTables,
    List<string> UnresolvedWriteTargets,
    List<string> ReadColumns,
    List<string> WrittenColumns,
    List<SqlObjectReference> FunctionReferences,
    List<SqlObjectReference> CallTargets,
    bool DynamicSql,
    SqlSourceLocation Source);