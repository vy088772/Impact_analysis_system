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

// One loaded project file, together with the XML namespace its elements carry -- an old-style
// project declares one and an SDK-style project declares none, and every reader below would
// otherwise have to carry both halves around to ask a single question. The two project shapes
// differ in almost everything else, but both are read through exactly these four questions.
internal sealed class ProjectXml
{
    private readonly XDocument _document;
    private readonly XNamespace _namespace;

    private ProjectXml(XDocument document)
    {
        _document = document;
        _namespace = document.Root?.Name.Namespace ?? XNamespace.None;
    }

    internal static ProjectXml Load(string projectFile) => new(XDocument.Load(projectFile));

    internal string? RootAttribute(string name) => _document.Root?.Attribute(name)?.Value;

    internal IEnumerable<XElement> Elements(string name) => _document.Descendants(_namespace + name);

    internal string? ChildValue(XElement element, string name)
        => element.Element(_namespace + name)?.Value;

    /// <summary>The value of one MSBuild property, or null when the project declares none. The
    /// last declaration wins, which is how MSBuild evaluates a property.</summary>
    internal string? Property(string name) => Elements(name).LastOrDefault()?.Value.Trim();

    /// <summary>Every value one item attribute carries across the whole project file. A single
    /// attribute may hold several values separated by semicolons, which MSBuild treats as
    /// separate items, so they are yielded separately here too.</summary>
    internal IEnumerable<string> ItemValues(string itemName, string attributeName)
        => Elements(itemName)
            .Select(element => element.Attribute(attributeName)?.Value)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .SelectMany(value => value!.Split(';', StringSplitOptions.RemoveEmptyEntries))
            .Select(value => value.Trim())
            .Where(value => value.Length > 0);
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

        // A project that yields no source files at all holds an empty compilation, and zero source
        // files plus zero references would otherwise read as "nothing unresolved" and fall through
        // to `available`: a degraded analysis that looks like a confident one. Report unavailable
        // here, named distinctly from a project that failed to parse, so a maintainer can tell an
        // unreadable project from an empty one. Skipped when the caller already supplied its own
        // parsed trees (Ticket 06's ResolveCompilationForAnalysis): those trees are real source
        // found by the caller's own globbing.
        if (overrideSyntaxTrees is null && description.CompileItems.Count == 0)
            return ProjectSemanticBinding.Unavailable(
                scanRoot,
                projectFile,
                "unavailable_reference_resolution_failed",
                new[] { "no_compile_items: project contributes no C# source file" });

        var sourceFileCount = overrideSyntaxTrees?.Count ?? description.CompileItems.Count;

        // A <ProjectReference> names another project's own output, which this ticket does not
        // build (that would mean compiling that project's project file too, recursively). Report
        // it as unresolved rather than silently building an incomplete compilation that still
        // claims `available` — a degraded analysis must never look like a confident one. Nothing
        // below can change that answer, so it is settled before any reference resolution runs:
        // a project already known unavailable must never pay for a package restore.
        if (description.ProjectReferences.Count > 0)
            return ProjectSemanticBinding.Unavailable(
                scanRoot,
                projectFile,
                "unavailable_reference_resolution_failed",
                description.ProjectReferences,
                sourceFileCount);

        var (references, unresolved) = description.IsSdkStyle
            ? ResolveSdkStyleReferences(projectFile, description)
            : ResolveOldStyleReferences(projectFile, description);

        if (unresolved.Count > 0)
            return ProjectSemanticBinding.Unavailable(
                scanRoot,
                projectFile,
                "unavailable_reference_resolution_failed",
                unresolved,
                sourceFileCount);

        var syntaxTrees = overrideSyntaxTrees?.ToList() ?? description.CompileItems
            .Select(path => (SyntaxTree)CSharpSyntaxTree.ParseText(File.ReadAllText(path), path: path))
            .ToList();
        // The implicit using directives belong to the project, not to any one of its files, so
        // they join the compilation as their own tree -- the same place the .NET SDK's own
        // generated global usings file occupies in a real build. It carries no declaration, so it
        // is never a source file a caller could ask a question about, and never counted as one.
        if (description.GlobalUsingsSource is not null)
            syntaxTrees.Insert(0, CSharpSyntaxTree.ParseText(description.GlobalUsingsSource));
        var compilation = CSharpCompilation.Create(
            Path.GetFileNameWithoutExtension(projectFile),
            syntaxTrees,
            references,
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));

        return ProjectSemanticBinding.Available(scanRoot, projectFile, compilation, sourceFileCount);
    }

    // An SDK-style project's package references name no file on disk: they resolve through the
    // restore assets NuGet writes beside the project. Its <Reference> items, when it has any, name
    // an assembly at a HintPath exactly as an old-style project's do.
    private static (List<MetadataReference> References, List<string> Unresolved)
        ResolveSdkStyleReferences(string projectFile, ProjectFileDescription description)
    {
        var (references, unresolved) = ResolveExternalReferences(
            projectFile, description.References, isSdkStyle: true);
        var resolution = ResolveRestoredReferences(projectFile, description);
        references.AddRange(resolution.AssemblyPaths.Select(
            path => (MetadataReference)MetadataReference.CreateFromFile(path)));
        unresolved.AddRange(resolution.Unresolved);
        return (references, unresolved);
    }

    // An old-style project's declared package assemblies live under a packages directory that a
    // fresh clone never populated. One restore attempt, then one re-resolution pass — never a
    // retry loop, and never touched at all when every reference already resolves or the project
    // declares no packages.config to restore from.
    private static (List<MetadataReference> References, List<string> Unresolved)
        ResolveOldStyleReferences(string projectFile, ProjectFileDescription description)
    {
        var (references, unresolved) = ResolveExternalReferences(
            projectFile, description.References, isSdkStyle: false);
        var packagesConfigPath = Path.Combine(ProjectPaths.Directory(projectFile), "packages.config");
        if (unresolved.Count > 0 && File.Exists(packagesConfigPath))
        {
            var restoreFailure = PackageRestorer.RestoreDeclaredPackages(
                projectFile, packagesConfigPath, description.References);
            // Re-resolve regardless of outcome: RestoreDeclaredPackages restores whatever it can
            // before reporting a failure, so a package that landed on disk this run must stop
            // being named unresolved even when a later package in the same restore failed.
            (references, unresolved) = ResolveExternalReferences(
                projectFile, description.References, isSdkStyle: false);
            if (restoreFailure is not null)
                unresolved.Add(restoreFailure);
        }

        // An old-style (non-SDK) .csproj never lists mscorlib as an explicit <Reference>: csc.exe
        // adds it implicitly to every compilation. Without it, every built-in type (object,
        // string, ...) fails to bind and every call site becomes an unresolvable error, defeating
        // the whole point of building a compilation. An SDK-style project needs no such addition
        // and must not get one: its own framework references already carry every built-in type,
        // and a .NET Framework mscorlib beside them would declare every one of them twice.
        var mscorlibPath = ResolveFrameworkReference(new ProjectReferenceItem("mscorlib", null));
        if (mscorlibPath is null)
            unresolved.Add("mscorlib");
        else
            references.Add(MetadataReference.CreateFromFile(mscorlibPath));
        return (references, unresolved);
    }

    // A fresh clone carries no restore assets, so the project is restored once — never a retry
    // loop, and never at all for a project that already has them.
    private static SdkReferenceResolution ResolveRestoredReferences(
        string projectFile, ProjectFileDescription description)
    {
        var assetsPath = RestoreAssetsReader.AssetsPath(ProjectPaths.Directory(projectFile));
        if (!File.Exists(assetsPath))
        {
            var restoreFailure = SdkPackageRestorer.Restore(projectFile);
            if (restoreFailure is not null)
                return SdkReferenceResolution.Failed(restoreFailure);
            if (!File.Exists(assetsPath))
                return SdkReferenceResolution.Failed(
                    "restore_produced_no_assets: the restore reported success but wrote no "
                    + "project.assets.json");
        }
        return RestoreAssetsReader.Read(assetsPath, description.PackageReferences);
    }

    // Resolves every declared <Reference> against what is on disk right now, without touching
    // packages.config -- called once before any restore attempt, and once more after (Ticket 01)
    // if that attempt ran, so both passes share exactly the same resolution rule.
    private static (List<MetadataReference> References, List<string> Unresolved) ResolveExternalReferences(
        string projectFile, IReadOnlyList<ProjectReferenceItem> referenceItems, bool isSdkStyle)
    {
        var references = new List<MetadataReference>();
        var unresolved = new List<string>();
        foreach (var reference in referenceItems)
        {
            // A bare <Reference> with no HintPath names a .NET Framework assembly the GAC would
            // have resolved at build time. An SDK-style project targets .NET, where no such
            // assembly exists, so one there names something this reader cannot resolve at all.
            var resolvedPath = reference.HintPath is not null
                ? ResolveExternalReference(projectFile, reference)
                : isSdkStyle ? null : ResolveFrameworkReference(reference);
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

// Reads the source file list and the reference list from a .csproj in either of the two shapes
// this analyzer meets. An old-style (non-SDK) project states both outright: its explicit
// <Compile Include> items and <Reference Include> entries, where a <Reference> with a <HintPath>
// names an external assembly and one without names a bare framework reference (e.g. "System",
// "System.Data") that the GAC would have resolved at build time. An SDK-style project states
// almost nothing: its source files come from implicit globbing and its references from package
// references, both of which SdkProjectReader works out.
internal static class ProjectFileReader
{
    internal static ProjectFileDescription Read(string projectFile)
    {
        var project = ProjectXml.Load(projectFile);
        var projectDirectory = ProjectPaths.Directory(projectFile);
        return SdkProjectReader.SdkName(project) is null
            ? ReadOldStyle(project, projectDirectory)
            : ReadSdkStyle(project, projectDirectory);
    }

    private static ProjectFileDescription ReadOldStyle(ProjectXml project, string projectDirectory)
        => new(
            CompileItems: project.ItemValues("Compile", "Include")
                .Select(include => Path.GetFullPath(Path.Combine(
                    projectDirectory, include.Replace('\\', Path.DirectorySeparatorChar))))
                .Where(File.Exists)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList(),
            References: ReadReferences(project),
            ProjectReferences: ReadProjectReferences(project),
            IsSdkStyle: false,
            PackageReferences: Array.Empty<string>(),
            GlobalUsingsSource: null);

    private static ProjectFileDescription ReadSdkStyle(ProjectXml project, string projectDirectory)
        => new(
            CompileItems: SdkProjectReader.DiscoverCompileItems(projectDirectory, project),
            References: ReadReferences(project),
            ProjectReferences: ReadProjectReferences(project),
            IsSdkStyle: true,
            PackageReferences: SdkProjectReader.ReadPackageReferences(project),
            GlobalUsingsSource: SdkImplicitUsings.SourceFor(project));

    private static List<ProjectReferenceItem> ReadReferences(ProjectXml project)
        => project.Elements("Reference")
            .Select(element => new ProjectReferenceItem(
                (element.Attribute("Include")?.Value ?? "").Split(',')[0].Trim(),
                project.ChildValue(element, "HintPath")))
            .Where(reference => !string.IsNullOrWhiteSpace(reference.AssemblyName))
            .ToList();

    // <ProjectReference> names another project by path, not an assembly on disk; this ticket
    // does not resolve it (see ProjectCompilationResolver.ResolveProject), but it must still
    // be visible so its project isn't silently dropped from the reference list.
    private static List<string> ReadProjectReferences(ProjectXml project)
        => project.ItemValues("ProjectReference", "Include")
            .Select(include => Path.GetFileNameWithoutExtension(
                include.Replace('\\', Path.DirectorySeparatorChar)))
            .ToList();
}

internal sealed record ProjectReferenceItem(string AssemblyName, string? HintPath);

internal sealed record ProjectFileDescription(
    IReadOnlyList<string> CompileItems,
    IReadOnlyList<ProjectReferenceItem> References,
    IReadOnlyList<string> ProjectReferences,
    bool IsSdkStyle,
    IReadOnlyList<string> PackageReferences,
    string? GlobalUsingsSource);

/// <summary>One Semantic Binding Availability attempt for one project file (or, when a scan root
/// holds no project file, for the scan root itself). SourceFileCount is how many source files the
/// project reader found for it: an SDK-style project states none of them in its project file, so
/// the count is the only place a maintainer can see whether implicit globbing found the source a
/// project really builds, or whether a removal item took more of it than intended.</summary>
internal sealed record ProjectSemanticBinding(
    string ScanRoot,
    string? ProjectFile,
    string Availability,
    IReadOnlyList<string> UnresolvedReferences,
    CSharpCompilation? Compilation,
    int SourceFileCount)
{
    internal static ProjectSemanticBinding Available(
        string scanRoot, string projectFile, CSharpCompilation compilation, int sourceFileCount)
        => new(scanRoot, projectFile, "available", Array.Empty<string>(), compilation, sourceFileCount);

    internal static ProjectSemanticBinding Unavailable(
        string scanRoot,
        string? projectFile,
        string availability,
        IReadOnlyList<string>? unresolvedReferences = null,
        int sourceFileCount = 0)
        => new(
            scanRoot,
            projectFile,
            availability,
            unresolvedReferences ?? Array.Empty<string>(),
            null,
            sourceFileCount);
}
