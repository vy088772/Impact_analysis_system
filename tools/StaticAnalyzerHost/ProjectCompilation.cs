using System.Xml.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

// Shared by ProjectCompilationResolver and PackageRestorer: both need a project file's own
// directory, and both resolve a HintPath-style relative path against it.
internal static class ProjectPaths
{
    internal static string Directory(string projectFile)
        => Path.GetDirectoryName(Path.GetFullPath(projectFile)) ?? "";

    internal static string ResolveRelative(string projectFile, string relativePath)
        => Path.GetFullPath(Path.Combine(
            Directory(projectFile), relativePath.Replace('\\', Path.DirectorySeparatorChar)));
}

// Builds one Roslyn Compilation per MSBuild project file found under a scan root, so a later
// ticket can bind a wrapper call to an exact method symbol through a real semantic model. This
// ticket only builds the compilation and reports the result of that attempt — Semantic Binding
// Availability — as a named, always-visible fact. No classification result changes here, and
// nothing yet consumes the compilation this resolver produces.
internal static class ProjectCompilationResolver
{
    /// <summary>
    /// Resolves one Semantic Binding Availability attempt for each project file found under each
    /// scan root. A scan root with no project file yields exactly one
    /// `unavailable_no_project_file` entry (no project file to name). A scan root with N project
    /// files yields N entries, one compilation attempt each — never one compilation for the whole
    /// scan root, and never one per source file.
    /// </summary>
    internal static IReadOnlyList<ProjectSemanticBinding> Resolve(IEnumerable<string> scanRoots)
    {
        var results = new List<ProjectSemanticBinding>();
        foreach (var scanRoot in scanRoots.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var projectFiles = DiscoverProjectFiles(scanRoot);
            if (projectFiles.Count == 0)
            {
                results.Add(ProjectSemanticBinding.Unavailable(
                    scanRoot, null, "unavailable_no_project_file"));
                continue;
            }
            foreach (var projectFile in projectFiles)
                results.Add(ResolveProject(scanRoot, projectFile, null));
        }
        return results;
    }

    /// <summary>
    /// Ticket 06: the `csharp` command reuses project reference resolution to build one
    /// compilation from the exact syntax trees it already parsed for its own analysis context,
    /// rather than re-parsing the project's `&lt;Compile&gt;` items into fresh tree instances.
    /// Roslyn's semantic APIs require a queried node to belong to a tree the compilation
    /// actually holds, so reusing the same tree instances is what lets a wrapper call site be
    /// bound to a symbol at all. Ambiguous project ownership -- zero or more than one project
    /// file resolves across the given scan roots -- is treated the same as "no semantic model":
    /// the syntax-only path, never a guess at which project's references apply.
    /// </summary>
    internal static CSharpCompilation? ResolveCompilationForAnalysis(
        IEnumerable<string> scanRoots,
        IReadOnlyList<SyntaxTree> syntaxTrees)
    {
        if (syntaxTrees.Count == 0)
            return null;
        var projectFiles = scanRoots
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .SelectMany(DiscoverProjectFiles)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (projectFiles.Count != 1)
            return null;
        // ScanRoot is discarded below (only Availability/Compilation matter here), so which of
        // the given scan roots actually owns this one project file is deliberately not tracked.
        var binding = ResolveProject(scanRoot: "", projectFiles[0], syntaxTrees);
        return binding.Availability == "available" ? binding.Compilation : null;
    }

    private static List<string> DiscoverProjectFiles(string scanRoot)
        => Directory.Exists(scanRoot)
            ? Directory.EnumerateFiles(scanRoot, "*.csproj", SearchOption.AllDirectories)
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                .ToList()
            : new List<string>();

    private static ProjectSemanticBinding ResolveProject(
        string scanRoot, string projectFile, IReadOnlyList<SyntaxTree>? overrideSyntaxTrees)
    {
        ProjectFileDescription description;
        try
        {
            description = ProjectFileReader.Read(projectFile);
        }
        catch (Exception exception)
        {
            return ProjectSemanticBinding.Unavailable(
                scanRoot,
                projectFile,
                "unavailable_reference_resolution_failed",
                new[] { $"csproj_unreadable: {exception.Message}" });
        }

        // An SDK-style project (every ASP.NET Core project in the catalog) declares no explicit
        // <Compile> items -- its source files come from implicit globbing, which this reader
        // does not understand yet (Ticket 05). Without this check, zero source files and zero
        // explicit references both read as "nothing unresolved", and the project below falls
        // through to `available` holding an empty compilation: a degraded analysis that looks
        // like a confident one. Report unavailable here, named distinctly from a project that
        // failed to parse, so a maintainer can tell an unreadable project from an empty one.
        // Skipped when the caller already supplied its own parsed trees (Ticket 06's
        // ResolveCompilationForAnalysis): those trees are real source found by the caller's own
        // globbing, so an empty explicit <Compile> list there is not an empty compilation.
        if (overrideSyntaxTrees is null && description.CompileItems.Count == 0)
            return ProjectSemanticBinding.Unavailable(
                scanRoot,
                projectFile,
                "unavailable_reference_resolution_failed",
                new[] { "no_compile_items: project declares no <Compile> source items" });

        var (references, unresolvedExternal) = ResolveExternalReferences(projectFile, description.References);

        // An old-style project's declared package assemblies live under a packages directory
        // that a fresh clone never populated. One restore attempt, then one re-resolution pass —
        // never a retry loop, and never touched at all when every reference already resolves or
        // the project declares no packages.config to restore from.
        if (unresolvedExternal.Count > 0)
        {
            var packagesConfigPath = Path.Combine(ProjectPaths.Directory(projectFile), "packages.config");
            if (File.Exists(packagesConfigPath))
            {
                var restoreFailure = PackageRestorer.RestoreDeclaredPackages(
                    projectFile, packagesConfigPath, description.References);
                // Re-resolve regardless of outcome: RestoreDeclaredPackages restores whatever it
                // can before reporting a failure, so a package that landed on disk this run must
                // stop being named unresolved even when a later package in the same restore failed.
                (references, unresolvedExternal) = ResolveExternalReferences(projectFile, description.References);
                if (restoreFailure is not null)
                    unresolvedExternal.Add(restoreFailure);
            }
        }

        var unresolved = new List<string>();
        // A <ProjectReference> names another project's own output, which this ticket does not
        // build (that would mean compiling that project's project file too, recursively). Report
        // it as unresolved rather than silently building an incomplete compilation that still
        // claims `available` — a degraded analysis must never look like a confident one.
        unresolved.AddRange(description.ProjectReferences);
        unresolved.AddRange(unresolvedExternal);

        // An old-style (non-SDK) .csproj never lists mscorlib as an explicit <Reference>: csc.exe
        // adds it implicitly to every compilation. Ticket 05 never needed it (it only checked
        // whether each declared reference resolves as a file), but a real semantic model does --
        // without it, every built-in type (object, string, ...) fails to bind and every call site
        // becomes an unresolvable error, defeating the whole point of building a compilation.
        var mscorlibPath = ResolveFrameworkReference(new ProjectReferenceItem("mscorlib", null));
        if (mscorlibPath is null)
            unresolved.Add("mscorlib");
        else
            references.Add(MetadataReference.CreateFromFile(mscorlibPath));

        if (unresolved.Count > 0)
            return ProjectSemanticBinding.Unavailable(
                scanRoot, projectFile, "unavailable_reference_resolution_failed", unresolved);

        var syntaxTrees = overrideSyntaxTrees ?? description.CompileItems
            .Select(path => (SyntaxTree)CSharpSyntaxTree.ParseText(File.ReadAllText(path), path: path))
            .ToList();
        var compilation = CSharpCompilation.Create(
            Path.GetFileNameWithoutExtension(projectFile),
            syntaxTrees,
            references,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

        return ProjectSemanticBinding.Available(scanRoot, projectFile, compilation);
    }

    // Resolves every declared <Reference> against what is on disk right now, without touching
    // packages.config -- called once before any restore attempt, and once more after (Ticket 01)
    // if that attempt ran, so both passes share exactly the same resolution rule.
    private static (List<MetadataReference> References, List<string> Unresolved) ResolveExternalReferences(
        string projectFile, IReadOnlyList<ProjectReferenceItem> referenceItems)
    {
        var references = new List<MetadataReference>();
        var unresolved = new List<string>();
        foreach (var reference in referenceItems)
        {
            var resolvedPath = reference.HintPath is not null
                ? ResolveExternalReference(projectFile, reference)
                : ResolveFrameworkReference(reference);
            if (resolvedPath is null)
            {
                unresolved.Add(reference.AssemblyName);
                continue;
            }
            references.Add(MetadataReference.CreateFromFile(resolvedPath));
        }
        return (references, unresolved);
    }

    // The HintPath in an old-style .csproj Reference item conventionally points at the
    // referencing project's own output/bin folder (e.g. "bin\SQLFunc.dll"): resolve it relative
    // to the project file's directory, exactly as AssemblyReferenceResolver already does for the
    // wrapper decompiler's single named receiver type.
    private static string? ResolveExternalReference(string projectFile, ProjectReferenceItem reference)
    {
        var candidate = ProjectPaths.ResolveRelative(projectFile, reference.HintPath!);
        return File.Exists(candidate) ? candidate : null;
    }

    private static string? ResolveFrameworkReference(ProjectReferenceItem reference)
        => WrapperAssemblyDecompiler.ReferenceAssemblyDirectories()
            .Select(directory => Path.Combine(directory, reference.AssemblyName + ".dll"))
            .FirstOrDefault(File.Exists);
}

// Reads the source file list and the reference list straight from an old-style (non-SDK) .csproj:
// its explicit <Compile Include> items and <Reference Include> entries. A <Reference> with a
// <HintPath> names an external assembly; one with no <HintPath> names a bare framework reference
// (e.g. "System", "System.Data") that the GAC would have resolved at build time.
internal static class ProjectFileReader
{
    internal static ProjectFileDescription Read(string projectFile)
    {
        var document = XDocument.Load(projectFile);
        var ns = document.Root?.Name.Namespace ?? XNamespace.None;
        var projectDirectory = Path.GetDirectoryName(Path.GetFullPath(projectFile)) ?? "";

        var compileItems = document.Descendants(ns + "Compile")
            .Select(element => element.Attribute("Include")?.Value)
            .Where(include => !string.IsNullOrWhiteSpace(include))
            .Select(include => Path.GetFullPath(Path.Combine(
                projectDirectory,
                include!.Replace('\\', Path.DirectorySeparatorChar))))
            .Where(File.Exists)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var references = document.Descendants(ns + "Reference")
            .Select(element => new ProjectReferenceItem(
                (element.Attribute("Include")?.Value ?? "").Split(',')[0].Trim(),
                element.Element(ns + "HintPath")?.Value))
            .Where(reference => !string.IsNullOrWhiteSpace(reference.AssemblyName))
            .ToList();

        // <ProjectReference> names another project by path, not an assembly on disk; this ticket
        // does not resolve it (see ProjectCompilationResolver.ResolveProject), but it must still
        // be visible so its project isn't silently dropped from the reference list.
        var projectReferences = document.Descendants(ns + "ProjectReference")
            .Select(element => element.Attribute("Include")?.Value)
            .Where(include => !string.IsNullOrWhiteSpace(include))
            .Select(include => Path.GetFileNameWithoutExtension(
                include!.Trim().Replace('\\', Path.DirectorySeparatorChar)))
            .ToList();

        return new ProjectFileDescription(compileItems, references, projectReferences);
    }
}

internal sealed record ProjectReferenceItem(string AssemblyName, string? HintPath);

internal sealed record ProjectFileDescription(
    IReadOnlyList<string> CompileItems,
    IReadOnlyList<ProjectReferenceItem> References,
    IReadOnlyList<string> ProjectReferences);

/// <summary>One Semantic Binding Availability attempt for one project file (or, when a scan root
/// holds no project file, for the scan root itself).</summary>
internal sealed record ProjectSemanticBinding(
    string ScanRoot,
    string? ProjectFile,
    string Availability,
    IReadOnlyList<string> UnresolvedReferences,
    CSharpCompilation? Compilation)
{
    internal static ProjectSemanticBinding Available(
        string scanRoot, string projectFile, CSharpCompilation compilation)
        => new(scanRoot, projectFile, "available", Array.Empty<string>(), compilation);

    internal static ProjectSemanticBinding Unavailable(
        string scanRoot,
        string? projectFile,
        string availability,
        IReadOnlyList<string>? unresolvedReferences = null)
        => new(scanRoot, projectFile, availability, unresolvedReferences ?? Array.Empty<string>(), null);
}
