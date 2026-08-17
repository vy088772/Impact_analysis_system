using System.Xml.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

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
            var projectFiles = Directory.Exists(scanRoot)
                ? Directory.EnumerateFiles(scanRoot, "*.csproj", SearchOption.AllDirectories)
                    .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                    .ToList()
                : new List<string>();
            if (projectFiles.Count == 0)
            {
                results.Add(ProjectSemanticBinding.Unavailable(
                    scanRoot, null, "unavailable_no_project_file"));
                continue;
            }
            foreach (var projectFile in projectFiles)
                results.Add(ResolveProject(scanRoot, projectFile));
        }
        return results;
    }

    private static ProjectSemanticBinding ResolveProject(string scanRoot, string projectFile)
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

        var references = new List<MetadataReference>();
        var unresolved = new List<string>();
        // A <ProjectReference> names another project's own output, which this ticket does not
        // build (that would mean compiling that project's project file too, recursively). Report
        // it as unresolved rather than silently building an incomplete compilation that still
        // claims `available` — a degraded analysis must never look like a confident one.
        unresolved.AddRange(description.ProjectReferences);
        foreach (var reference in description.References)
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

        if (unresolved.Count > 0)
            return ProjectSemanticBinding.Unavailable(
                scanRoot, projectFile, "unavailable_reference_resolution_failed", unresolved);

        var syntaxTrees = description.CompileItems
            .Select(path => CSharpSyntaxTree.ParseText(File.ReadAllText(path), path: path))
            .ToList();
        var compilation = CSharpCompilation.Create(
            Path.GetFileNameWithoutExtension(projectFile),
            syntaxTrees,
            references,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

        return ProjectSemanticBinding.Available(scanRoot, projectFile, compilation);
    }

    // The HintPath in an old-style .csproj Reference item conventionally points at the
    // referencing project's own output/bin folder (e.g. "bin\SQLFunc.dll"): resolve it relative
    // to the project file's directory, exactly as AssemblyReferenceResolver already does for the
    // wrapper decompiler's single named receiver type.
    private static string? ResolveExternalReference(string projectFile, ProjectReferenceItem reference)
    {
        var projectDirectory = Path.GetDirectoryName(Path.GetFullPath(projectFile)) ?? "";
        var candidate = Path.GetFullPath(Path.Combine(
            projectDirectory,
            reference.HintPath!.Replace('\\', Path.DirectorySeparatorChar)));
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
