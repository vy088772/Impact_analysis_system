using System.IO.Compression;
using System.Xml.Linq;

// Restores an old-style (packages.config) project's declared NuGet packages into the directory
// its own <Reference HintPath> entries already point at, so a reference that names a package
// assembly resolves the same way it would after a normal Visual Studio restore. This is the
// old-style counterpart to the SDK-style project's restore-assets refresh: neither ships nuget.exe
// nor shells out to `dotnet restore` (which does not restore packages.config projects at all --
// verified against this host's own toolchain), so it fetches each declared package directly from
// the NuGet v3 flat container API, the same content a normal restore would have placed there.
internal static class PackageRestorer
{
    private static readonly HttpClient Http = new();

    /// <summary>
    /// Restores every package <paramref name="packagesConfigPath"/> declares that is not already
    /// present at its conventional location, into the directory <paramref name="references"/>'
    /// own HintPaths point at. Returns null on success (including "nothing declared"), or a
    /// string naming the cause on failure -- restore never throws, so a project whose restore
    /// fails still gets to report `unavailable_reference_resolution_failed` and name why, rather
    /// than crashing the whole semantic-binding attempt.
    /// </summary>
    internal static string? RestoreDeclaredPackages(
        string projectFile, string packagesConfigPath, IReadOnlyList<ProjectReferenceItem> references)
    {
        IReadOnlyList<(string Id, string Version)> packages;
        try
        {
            packages = PackagesConfigReader.Read(packagesConfigPath);
        }
        catch (Exception exception)
        {
            return $"packages_config_unreadable: {exception.Message}";
        }
        if (packages.Count == 0)
            return null;

        var packagesDirectory = DeterminePackagesDirectory(projectFile, references);
        var failures = new List<string>();
        foreach (var package in packages)
        {
            var targetDirectory = Path.Combine(packagesDirectory, $"{package.Id}.{package.Version}");
            if (Directory.Exists(targetDirectory))
                continue; // already restored from a prior run -- nothing to do
            try
            {
                DownloadAndExtract(package.Id, package.Version, targetDirectory);
            }
            catch (Exception exception)
            {
                failures.Add($"{package.Id}.{package.Version}: {exception.Message}");
            }
        }
        return failures.Count == 0
            ? null
            : $"package_restore_failed: {string.Join("; ", failures)}";
    }

    private static void DownloadAndExtract(string id, string version, string targetDirectory)
    {
        var idLower = id.ToLowerInvariant();
        var versionLower = version.ToLowerInvariant();
        var url = $"https://api.nuget.org/v3-flatcontainer/{idLower}/{versionLower}/{idLower}.{versionLower}.nupkg";

        byte[] packageBytes;
        using (var response = Http.GetAsync(url).GetAwaiter().GetResult())
        {
            if (!response.IsSuccessStatusCode)
                throw new InvalidOperationException(
                    $"download failed ({(int)response.StatusCode} {response.ReasonPhrase})");
            packageBytes = response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult();
        }

        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}.nupkg");
        // Extract into a staging directory first and rename into place only once complete: a
        // failed/interrupted extraction must never leave a half-populated directory behind for a
        // later run to mistake for "already restored" (the only check above is Directory.Exists).
        var stagingDirectory = $"{targetDirectory}.partial-{Guid.NewGuid():N}";
        try
        {
            File.WriteAllBytes(tempFile, packageBytes);
            Directory.CreateDirectory(stagingDirectory);
            ZipFile.ExtractToDirectory(tempFile, stagingDirectory);
            Directory.Move(stagingDirectory, targetDirectory);
        }
        finally
        {
            File.Delete(tempFile);
            if (Directory.Exists(stagingDirectory))
                Directory.Delete(stagingDirectory, recursive: true);
        }
    }

    // The HintPath convention for a restored package is "...\packages\{id}.{version}\lib\...":
    // walk up from any declared reference's own HintPath to find that "packages" directory, so
    // restore lands exactly where the project's own references already expect it. A project with
    // no such HintPath yet (nothing has ever been restored for it) falls back to the conventional
    // solution-level location, one directory above the project file.
    private static string DeterminePackagesDirectory(
        string projectFile, IReadOnlyList<ProjectReferenceItem> references)
    {
        foreach (var reference in references)
        {
            if (reference.HintPath is null)
                continue;
            var absoluteHintPath = ProjectPaths.ResolveRelative(projectFile, reference.HintPath);
            var packagesRoot = FindPackagesAncestor(absoluteHintPath);
            if (packagesRoot is not null)
                return packagesRoot;
        }
        return Path.GetFullPath(Path.Combine(ProjectPaths.Directory(projectFile), "..", "packages"));
    }

    private static string? FindPackagesAncestor(string absolutePath)
    {
        var directory = Path.GetDirectoryName(absolutePath);
        while (directory is not null)
        {
            if (string.Equals(Path.GetFileName(directory), "packages", StringComparison.OrdinalIgnoreCase))
                return directory;
            directory = Path.GetDirectoryName(directory);
        }
        return null;
    }
}

// Reads the declared package list straight from an old-style project's packages.config: the same
// list `nuget restore` would read, and the same one PackageRestorer restores from.
internal static class PackagesConfigReader
{
    internal static IReadOnlyList<(string Id, string Version)> Read(string packagesConfigPath)
    {
        var document = XDocument.Load(packagesConfigPath);
        return document.Descendants("package")
            .Select(element => (
                Id: element.Attribute("id")?.Value ?? "",
                Version: element.Attribute("version")?.Value ?? ""))
            .Where(package => package.Id.Length > 0 && package.Version.Length > 0)
            .ToList();
    }
}
