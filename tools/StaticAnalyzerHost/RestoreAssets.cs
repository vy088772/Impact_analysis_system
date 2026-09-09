using System.Text.Json;

/// <summary>The assemblies an SDK-style project's restore assets resolved to, and the names of
/// everything the assets were expected to resolve but did not.</summary>
internal sealed record SdkReferenceResolution(
    IReadOnlyList<string> AssemblyPaths,
    IReadOnlyList<string> Unresolved)
{
    internal static SdkReferenceResolution Failed(string reason)
        => new(Array.Empty<string>(), new[] { reason });
}

// Resolves an SDK-style project's references through its restore assets: the file NuGet writes at
// obj/project.assets.json, which names the package folders on this machine, the exact compile-time
// assembly inside each restored package, and the exact targeting pack version the project's
// framework references resolve to. Everything a package reference needs is in that one file, so
// nothing here guesses at a NuGet layout or hunts through a .NET installation.
internal static class RestoreAssetsReader
{
    internal static string AssetsPath(string projectDirectory)
        => Path.Combine(projectDirectory, "obj", "project.assets.json");

    internal static SdkReferenceResolution Read(
        string assetsPath, IReadOnlyList<string> declaredPackageReferences)
    {
        JsonDocument assets;
        try
        {
            using var stream = File.OpenRead(assetsPath);
            assets = JsonDocument.Parse(stream);
        }
        catch (Exception exception)
        {
            return SdkReferenceResolution.Failed($"restore_assets_unreadable: {exception.Message}");
        }

        using (assets)
        {
            var root = assets.RootElement;
            var packageFolders = ReadPackageFolders(root);
            if (packageFolders.Count == 0)
                return SdkReferenceResolution.Failed(
                    "restore_assets_incomplete: no package folder is named");

            var unresolved = new List<string>();
            var target = FirstChild(root, "targets", out var targetName);
            var framework = MatchingFramework(root, targetName);

            // One assembly name may be offered by both a targeting pack and a package that still
            // ships a .NET Standard facade for it. Handing Roslyn both makes every type in them
            // ambiguous -- `System.Void` itself stops resolving -- so the first offer of a name
            // wins and the rest are dropped, exactly as MSBuild's own conflict resolution does.
            // The targeting packs go first, because a framework type belongs to the framework.
            var assemblies = new AssemblySet();
            ReadFrameworkAssemblies(framework, packageFolders, assemblies, unresolved);
            ReadPackageAssemblies(
                root, target, packageFolders, declaredPackageReferences, assemblies, unresolved);
            return new SdkReferenceResolution(assemblies.Paths, unresolved);
        }
    }

    // The assemblies gathered for one compilation, holding at most one file per assembly name.
    // When two offers share a name the higher assembly version wins, which is the rule MSBuild's
    // own conflict resolution follows: a targeting pack and a package both ship
    // Microsoft.Extensions.Logging, and keeping the older of the two breaks every package built
    // against the newer one.
    private sealed class AssemblySet
    {
        private readonly Dictionary<string, string> _byName = new(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, Version> _versions = new(StringComparer.OrdinalIgnoreCase);

        internal List<string> Paths => _byName
            .OrderBy(entry => entry.Key, StringComparer.OrdinalIgnoreCase)
            .Select(entry => entry.Value)
            .ToList();

        internal void Offer(string path)
        {
            var name = Path.GetFileName(path);
            if (!_byName.TryGetValue(name, out var claimed) || VersionOf(path) > VersionOf(claimed))
                _byName[name] = path;
        }

        // An assembly whose version cannot be read loses every comparison rather than winning one
        // on a version this never actually saw.
        private Version VersionOf(string path)
        {
            if (_versions.TryGetValue(path, out var cached))
                return cached;
            Version version;
            try
            {
                version = System.Reflection.AssemblyName.GetAssemblyName(path).Version
                    ?? new Version(0, 0);
            }
            catch (Exception)
            {
                version = new Version(0, 0);
            }
            _versions[path] = version;
            return version;
        }
    }

    private static void ReadPackageAssemblies(
        JsonElement root,
        JsonElement target,
        IReadOnlyList<string> packageFolders,
        IReadOnlyList<string> declaredPackageReferences,
        AssemblySet assemblies,
        List<string> unresolved)
    {
        var resolvedPackageIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (target.ValueKind != JsonValueKind.Object)
        {
            unresolved.AddRange(declaredPackageReferences);
            return;
        }
        root.TryGetProperty("libraries", out var libraries);
        foreach (var library in target.EnumerateObject())
        {
            // A "project" library is a <ProjectReference>, whose own output this ticket does not
            // build; it is reported unresolved through the project reference list instead.
            if (LibraryType(library.Value) != "package")
                continue;
            resolvedPackageIds.Add(library.Name.Split('/')[0]);
            var relativePath = LibraryPath(libraries, library.Name);
            if (relativePath is null)
            {
                unresolved.Add(library.Name);
                continue;
            }
            foreach (var compileItem in CompileItems(library.Value))
            {
                var resolved = ResolveInPackageFolders(packageFolders, relativePath, compileItem);
                if (resolved is null)
                    unresolved.Add($"{library.Name}/{compileItem}");
                else
                    assemblies.Offer(resolved);
            }
        }
        // A package the project declares but the assets never mention means the assets predate the
        // project file. Name it rather than compiling without it and calling that success.
        unresolved.AddRange(declaredPackageReferences.Where(id => !resolvedPackageIds.Contains(id)));
    }

    // A framework reference ("Microsoft.AspNetCore.App") resolves to a targeting pack, which
    // reaches a machine one of two ways. A pack for a framework the installed SDK does not ship is
    // downloaded during restore, and the assets pin its exact version as a download dependency
    // named "<framework reference>.Ref"; a pack the SDK does ship sits inside the .NET
    // installation, which the assets name through the runtime identifier graph they point at.
    // Both roads start at the restore assets, so neither guesses where .NET lives.
    private static void ReadFrameworkAssemblies(
        JsonElement framework,
        IReadOnlyList<string> packageFolders,
        AssemblySet assemblies,
        List<string> unresolved)
    {
        if (framework.ValueKind != JsonValueKind.Object
            || !framework.TryGetProperty("frameworkReferences", out var frameworkReferences)
            || frameworkReferences.ValueKind != JsonValueKind.Object)
            return;
        var targetAlias = framework.TryGetProperty("targetAlias", out var alias)
            ? alias.GetString()
            : null;
        var sdk = DotnetSdk.Locate();
        var installedPackRoots = InstalledPackRoots(framework, sdk).ToList();
        foreach (var frameworkReference in frameworkReferences.EnumerateObject())
        {
            var packName = frameworkReference.Name + ".Ref";
            var referenceDirectory = targetAlias is null
                ? null
                : DownloadedPackDirectory(framework, packageFolders, packName, targetAlias)
                    ?? InstalledPackDirectory(installedPackRoots, packName, targetAlias);
            if (referenceDirectory is null)
            {
                // A pack the restore never downloaded has to come from a .NET installation. When
                // there is none, that is the cause a maintainer needs, named the same way the
                // restore path names it -- not the pack, which is only the symptom.
                unresolved.Add(sdk.Executable is null
                    ? $"no_dotnet_sdk: {packName} needs a .NET installation, and {sdk.Detail}"
                    : packName);
                continue;
            }
            foreach (var assembly in Directory.EnumerateFiles(referenceDirectory, "*.dll"))
                assemblies.Offer(assembly);
        }
    }

    private static string? DownloadedPackDirectory(
        JsonElement framework,
        IReadOnlyList<string> packageFolders,
        string packName,
        string targetAlias)
    {
        var version = DownloadDependencyVersion(framework, packName);
        return version is null
            ? null
            : ResolveInPackageFolders(
                packageFolders,
                Path.Combine(packName.ToLowerInvariant(), version),
                Path.Combine("ref", targetAlias),
                expectDirectory: true);
    }

    // Only a pack version that carries the project's own target framework can serve it, so
    // filtering on that directory picks the right release line before the version comparison
    // picks the newest patch inside it.
    private static string? InstalledPackDirectory(
        IReadOnlyList<string> packRoots, string packName, string targetAlias)
        => packRoots
            .Select(root => Path.Combine(root, packName))
            .Where(Directory.Exists)
            .SelectMany(Directory.EnumerateDirectories)
            .Select(versionDirectory => (
                Version: PackVersion(Path.GetFileName(versionDirectory)),
                Directory: Path.Combine(versionDirectory, "ref", targetAlias)))
            .Where(candidate => Directory.Exists(candidate.Directory))
            .OrderByDescending(candidate => candidate.Version)
            .Select(candidate => candidate.Directory)
            .FirstOrDefault();

    // A pack directory is named by its version, sometimes with a prerelease suffix ("8.0.0-rc.1").
    // The comparison has to be numeric: 10.0.3 is a later pack than 8.0.24, and text ordering says
    // the opposite.
    private static Version PackVersion(string directoryName)
        => Version.TryParse(directoryName.Split('-')[0], out var version) ? version : new Version(0, 0);

    // The runtime identifier graph the assets point at lives at "<installation>/sdk/<version>/",
    // which names the .NET installation that restored this project -- and so the packs directory
    // holding every targeting pack that installation ships. The installation running this host is
    // a second candidate, for assets written without that path.
    private static IEnumerable<string> InstalledPackRoots(JsonElement framework, DotnetSdkLookup sdk)
    {
        var roots = new List<string>();
        if (framework.TryGetProperty("runtimeIdentifierGraphPath", out var graphPath))
        {
            var installation = InstallationRootAbove(graphPath.GetString());
            if (installation is not null)
                roots.Add(Path.Combine(installation, "packs"));
        }
        if (sdk.Executable is not null)
            roots.Add(Path.Combine(Path.GetDirectoryName(sdk.Executable)!, "packs"));
        return roots.Where(Directory.Exists).Distinct(StringComparer.OrdinalIgnoreCase);
    }

    private static string? InstallationRootAbove(string? sdkFilePath)
    {
        if (string.IsNullOrWhiteSpace(sdkFilePath))
            return null;
        var directory = Path.GetDirectoryName(Path.GetFullPath(sdkFilePath));
        while (directory is not null)
        {
            if (string.Equals(Path.GetFileName(directory), "sdk", StringComparison.OrdinalIgnoreCase))
                return Path.GetDirectoryName(directory);
            directory = Path.GetDirectoryName(directory);
        }
        return null;
    }

    // A download dependency pins one exact version, written as the degenerate range "[x, x]".
    private static string? DownloadDependencyVersion(JsonElement framework, string packName)
    {
        if (!framework.TryGetProperty("downloadDependencies", out var dependencies)
            || dependencies.ValueKind != JsonValueKind.Array)
            return null;
        foreach (var dependency in dependencies.EnumerateArray())
        {
            if (dependency.ValueKind != JsonValueKind.Object
                || !dependency.TryGetProperty("name", out var name)
                || !string.Equals(name.GetString(), packName, StringComparison.OrdinalIgnoreCase)
                || !dependency.TryGetProperty("version", out var version))
                continue;
            var pinned = (version.GetString() ?? "").Trim('[', ']', '(', ')').Split(',')[0].Trim();
            return pinned.Length > 0 ? pinned : null;
        }
        return null;
    }

    private static string? ResolveInPackageFolders(
        IReadOnlyList<string> packageFolders,
        string libraryPath,
        string relativePath,
        bool expectDirectory = false)
    {
        foreach (var packageFolder in packageFolders)
        {
            var candidate = Path.GetFullPath(Path.Combine(
                packageFolder,
                libraryPath.Replace('/', Path.DirectorySeparatorChar),
                relativePath.Replace('/', Path.DirectorySeparatorChar)));
            if (expectDirectory ? Directory.Exists(candidate) : File.Exists(candidate))
                return candidate;
        }
        return null;
    }

    private static IReadOnlyList<string> ReadPackageFolders(JsonElement root)
        => root.TryGetProperty("packageFolders", out var folders)
            && folders.ValueKind == JsonValueKind.Object
                ? folders.EnumerateObject().Select(folder => folder.Name).ToList()
                : new List<string>();

    private static string? LibraryType(JsonElement library)
        => library.ValueKind == JsonValueKind.Object && library.TryGetProperty("type", out var type)
            ? type.GetString()
            : null;

    private static string? LibraryPath(JsonElement libraries, string libraryName)
        => libraries.ValueKind == JsonValueKind.Object
            && libraries.TryGetProperty(libraryName, out var library)
            && library.TryGetProperty("path", out var path)
                ? path.GetString()
                : null;

    // A compile item ending in "_._" (as "lib/net6.0/_._" does) is NuGet's marker for "this
    // package deliberately contributes no compile-time assembly for this framework"; it names no
    // file and must not be looked for on disk.
    private static IEnumerable<string> CompileItems(JsonElement library)
        => library.TryGetProperty("compile", out var compile) && compile.ValueKind == JsonValueKind.Object
            ? compile.EnumerateObject()
                .Select(item => item.Name)
                .Where(name => !name.EndsWith("_._", StringComparison.Ordinal))
            : Enumerable.Empty<string>();

    // The first child of a JSON map, with its name. Both maps this reads -- targets and
    // frameworks -- hold exactly one entry for a single-target project, which every measured
    // project is; taking the first is how a multi-target project still resolves against one of
    // its frameworks rather than against none.
    private static JsonElement FirstChild(JsonElement root, string propertyName, out string? childName)
    {
        childName = null;
        if (!root.TryGetProperty(propertyName, out var container)
            || container.ValueKind != JsonValueKind.Object)
            return default;
        foreach (var child in container.EnumerateObject())
        {
            childName = child.Name;
            return child.Value;
        }
        return default;
    }

    // The frameworks map and the targets map are keyed the same way for a single-target project,
    // which every measured project is. Fall back to the only entry when they are not, so a
    // multi-target project resolves against something rather than nothing.
    private static JsonElement MatchingFramework(JsonElement root, string? targetName)
    {
        if (!root.TryGetProperty("project", out var project)
            || !project.TryGetProperty("frameworks", out var frameworks)
            || frameworks.ValueKind != JsonValueKind.Object)
            return default;
        if (targetName is not null && frameworks.TryGetProperty(targetName, out var matching))
            return matching;
        foreach (var framework in frameworks.EnumerateObject())
            return framework.Value;
        return default;
    }
}
