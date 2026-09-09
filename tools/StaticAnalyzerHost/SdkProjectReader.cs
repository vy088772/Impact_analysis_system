using System.Text;
using System.Text.RegularExpressions;

// One MSBuild item pattern, serving the two things an SDK-style project's source items ask of it:
// expanding a pattern into files, and excluding files by one. It carries MSBuild's whole wildcard
// vocabulary, because a project file may write any of it: `**` spans any number of directories,
// while `*` and `?` never cross one. Matching ignores case, because MSBuild's own item evaluation
// does.
internal sealed class MsBuildItemPattern
{
    private static readonly char[] WildcardCharacters = { '*', '?' };

    private readonly Regex _matcher;

    private MsBuildItemPattern(Regex matcher) => _matcher = matcher;

    internal static bool HasWildcard(string pattern) => pattern.IndexOfAny(WildcardCharacters) >= 0;

    internal static MsBuildItemPattern Parse(string pattern)
    {
        var normalized = Normalize(pattern);
        var expression = new StringBuilder("^");
        for (var index = 0; index < normalized.Length; index++)
        {
            if (normalized[index] == '*' && index + 1 < normalized.Length && normalized[index + 1] == '*')
            {
                // "**/" stands for zero or more whole directories, so "**/*.cs" must also match a
                // file at the top. A "**" with nothing after it stands for everything below the
                // directory it follows, which is the shape "HisFiles\**" takes.
                if (index + 2 < normalized.Length && normalized[index + 2] == '/')
                {
                    expression.Append("(?:[^/]+/)*");
                    index += 2;
                }
                else
                {
                    expression.Append(".*");
                    index += 1;
                }
                continue;
            }
            expression.Append(normalized[index] switch
            {
                '*' => "[^/]*",
                '?' => "[^/]",
                var character => Regex.Escape(character.ToString()),
            });
        }
        expression.Append('$');
        return new MsBuildItemPattern(new Regex(
            expression.ToString(), RegexOptions.IgnoreCase | RegexOptions.CultureInvariant));
    }

    internal bool Matches(string projectRelativePath) => _matcher.IsMatch(Normalize(projectRelativePath));

    // A project file writes its patterns with a backslash separator and the filesystem hands back
    // whichever separator it uses; both sides are normalized to "/" so one matcher serves either.
    private static string Normalize(string path) => path.Replace('\\', '/');
}

// Reads the source file list and the package reference list from an SDK-style project file, whose
// shape is nothing like the old-style one it sits beside: source files come from implicit globbing
// over the project's own directory rather than from explicit <Compile Include> items, and
// references are package references resolved through the project's restore assets rather than
// assemblies named at a HintPath.
internal static class SdkProjectReader
{
    // MSBuild's own DefaultItemExcludes, reduced to what a `.cs` glob can actually hit: the two
    // build output directories, and every dot-directory (.git, .vs) below the project. Without
    // them a stale copy of a type in `obj` would be compiled beside the type itself.
    private static readonly string[] DefaultExcludes = { "bin/**", "obj/**", "**/.*/**" };

    /// <summary>The name of the SDK this project builds with, or null when it declares none and
    /// so is an old-style project. A project names its SDK either on the &lt;Project&gt; element
    /// itself (the common form) or on an &lt;Import&gt; element (the form a project written before
    /// that attribute existed uses).</summary>
    internal static string? SdkName(ProjectXml project)
        => project.RootAttribute("Sdk")
            ?? project.Elements("Import")
                .Select(element => element.Attribute("Sdk")?.Value)
                .FirstOrDefault(sdk => !string.IsNullOrWhiteSpace(sdk));

    internal static IReadOnlyList<string> DiscoverCompileItems(
        string projectDirectory, ProjectXml project)
    {
        var excludes = DefaultExcludes
            .Concat(project.ItemValues("Compile", "Remove"))
            .Select(MsBuildItemPattern.Parse)
            .ToList();

        var candidates = new List<string>();
        if (DefaultCompileItemsEnabled(project))
            candidates.AddRange(
                Directory.EnumerateFiles(projectDirectory, "*.cs", SearchOption.AllDirectories));
        // An explicit <Compile Include> adds to the implicit glob in an SDK-style project rather
        // than replacing it, which is why both lists are gathered before either is filtered.
        foreach (var include in project.ItemValues("Compile", "Include"))
            candidates.AddRange(Expand(projectDirectory, include));

        return candidates
            .Select(Path.GetFullPath)
            .Where(path => !excludes.Any(
                exclude => exclude.Matches(Path.GetRelativePath(projectDirectory, path))))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    internal static IReadOnlyList<string> ReadPackageReferences(ProjectXml project)
        => project.ItemValues("PackageReference", "Include")
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

    private static IEnumerable<string> Expand(string projectDirectory, string include)
    {
        if (!MsBuildItemPattern.HasWildcard(include))
        {
            var named = Path.GetFullPath(Path.Combine(
                projectDirectory, include.Replace('\\', Path.DirectorySeparatorChar)));
            return File.Exists(named) ? new[] { named } : Array.Empty<string>();
        }
        var pattern = MsBuildItemPattern.Parse(include);
        return Directory.EnumerateFiles(projectDirectory, "*", SearchOption.AllDirectories)
            .Where(path => pattern.Matches(Path.GetRelativePath(projectDirectory, path)));
    }

    // A project that turns the default items off lists every source file itself, exactly as an
    // old-style project does. Honour that rather than globbing files the project deliberately
    // excluded from its own compilation. EnableDefaultCompileItems speaks only for source files
    // and so decides on its own; EnableDefaultItems speaks for every item kind at once and is
    // consulted only when the narrower property says nothing.
    private static bool DefaultCompileItemsEnabled(ProjectXml project)
    {
        var compileItems = project.Property("EnableDefaultCompileItems");
        var allItems = project.Property("EnableDefaultItems");
        return !string.Equals(compileItems ?? allItems, "false", StringComparison.OrdinalIgnoreCase);
    }
}

// The .NET SDK writes a global using directive into every project that enables implicit usings,
// and generates it at build time -- so it exists nowhere in a repository a maintainer clones, and
// nowhere this reader could find it. Every measured ASP.NET Core project enables it, and its
// source relies on it: an interface declaring `Task<object> Query(...)` with no using directive
// above it binds to nothing without these. Reproducing the SDK's own list is what makes the
// compilation this ticket builds a semantic model rather than a pile of unresolved names.
internal static class SdkImplicitUsings
{
    private static readonly string[] EveryProject =
    {
        "System",
        "System.Collections.Generic",
        "System.IO",
        "System.Linq",
        "System.Net.Http",
        "System.Threading",
        "System.Threading.Tasks",
    };

    private static readonly string[] WebProject =
    {
        "System.Net.Http.Json",
        "Microsoft.AspNetCore.Builder",
        "Microsoft.AspNetCore.Hosting",
        "Microsoft.AspNetCore.Http",
        "Microsoft.AspNetCore.Routing",
        "Microsoft.Extensions.Configuration",
        "Microsoft.Extensions.DependencyInjection",
        "Microsoft.Extensions.Hosting",
        "Microsoft.Extensions.Logging",
    };

    private static readonly string[] WorkerProject =
    {
        "Microsoft.Extensions.Configuration",
        "Microsoft.Extensions.DependencyInjection",
        "Microsoft.Extensions.Hosting",
        "Microsoft.Extensions.Logging",
    };

    /// <summary>
    /// The global using directives this project compiles with, as C# source, or null when the
    /// project imports nothing implicitly and so needs no such source file at all.
    /// </summary>
    internal static string? SourceFor(ProjectXml project)
    {
        var namespaces = new List<string>();
        if (IsEnabled(project))
        {
            namespaces.AddRange(EveryProject);
            // The SDK name is read the same way the project reader reads it, so a project that
            // names its SDK on an <Import> element keeps its web namespaces too.
            var sdk = SdkProjectReader.SdkName(project) ?? "";
            if (sdk.Contains("Microsoft.NET.Sdk.Web", StringComparison.OrdinalIgnoreCase))
                namespaces.AddRange(WebProject);
            else if (sdk.Contains("Microsoft.NET.Sdk.Worker", StringComparison.OrdinalIgnoreCase))
                namespaces.AddRange(WorkerProject);
        }
        // A <Using> item adds one namespace to the implicit set, or takes one out of it, exactly
        // as a <Compile> item adds or removes a source file.
        namespaces.AddRange(project.ItemValues("Using", "Include"));
        var removed = project.ItemValues("Using", "Remove").ToHashSet(StringComparer.Ordinal);

        var directives = namespaces
            .Where(name => !removed.Contains(name))
            .Distinct(StringComparer.Ordinal)
            .OrderBy(name => name, StringComparer.Ordinal)
            .Select(name => $"global using global::{name};")
            .ToList();
        return directives.Count == 0 ? null : string.Join(Environment.NewLine, directives);
    }

    private static bool IsEnabled(ProjectXml project)
        => string.Equals(
            project.Property("ImplicitUsings"), "enable", StringComparison.OrdinalIgnoreCase);
}
