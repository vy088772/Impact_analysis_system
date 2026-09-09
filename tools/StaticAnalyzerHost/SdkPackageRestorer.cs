using System.Diagnostics;
using System.Runtime.InteropServices;

/// <summary>Where the .NET SDK that restores a project was found, or why none was.</summary>
internal sealed record DotnetSdkLookup(string? Executable, string Detail)
{
    internal static DotnetSdkLookup Found(string executable) => new(executable, executable);

    internal static DotnetSdkLookup Missing(string detail) => new(null, detail);
}

internal static class DotnetSdk
{
    /// <summary>
    /// Locates the .NET SDK this host restores with. DOTNET_ROOT is the documented way to name the
    /// .NET installation a process must use, so when it is set it decides: an installation named
    /// there that holds no SDK is a missing SDK, never a reason to go looking for a second one.
    /// Otherwise the installation already running this host is the one that restores.
    /// </summary>
    internal static DotnetSdkLookup Locate()
    {
        var declaredRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT");
        if (!string.IsNullOrWhiteSpace(declaredRoot))
            return Inspect(declaredRoot, "DOTNET_ROOT names");
        var hostRoot = HostInstallationRoot();
        return hostRoot is null
            ? DotnetSdkLookup.Missing("no .NET installation could be located")
            : Inspect(hostRoot, "the .NET installation running this host is");
    }

    private static DotnetSdkLookup Inspect(string root, string source)
    {
        var executable = Path.Combine(root, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet");
        if (!File.Exists(executable))
            return DotnetSdkLookup.Missing($"{source} {root}, which holds no dotnet executable");
        var sdkDirectory = Path.Combine(root, "sdk");
        if (!Directory.Exists(sdkDirectory) || Directory.GetDirectories(sdkDirectory).Length == 0)
            return DotnetSdkLookup.Missing($"{source} {root}, which holds no .NET SDK");
        return DotnetSdkLookup.Found(executable);
    }

    // GetRuntimeDirectory is "<installation root>/shared/Microsoft.NETCore.App/<version>/".
    private static string? HostInstallationRoot()
    {
        var root = Path.GetFullPath(Path.Combine(
            RuntimeEnvironment.GetRuntimeDirectory(), "..", "..", ".."));
        return Directory.Exists(root) ? root : null;
    }
}

// Restores one SDK-style project so it gains the restore assets its references resolve through.
// This is the SDK-style counterpart to PackageRestorer, which fetches an old-style project's
// packages.config packages by hand because `dotnet restore` does not restore that shape at all.
// Here the SDK does the work, so this only has to find it, run it once, and report what happened.
internal static class SdkPackageRestorer
{
    // A cold NuGet cache restoring a project with two dozen packages is the slow case this bounds.
    // A restore still running after it is treated as failed and named, rather than holding the
    // whole scan open indefinitely.
    private const int RestoreTimeoutMilliseconds = 600_000;

    /// <summary>
    /// Restores <paramref name="projectFile"/> once. Returns null on success, or a string naming
    /// the cause on failure -- restore never throws, so a project whose restore fails still gets
    /// to report `unavailable_reference_resolution_failed` and name why.
    /// </summary>
    internal static string? Restore(string projectFile)
    {
        var sdk = DotnetSdk.Locate();
        if (sdk.Executable is null)
            return $"no_dotnet_sdk: {sdk.Detail}";

        var startInfo = new ProcessStartInfo(sdk.Executable)
        {
            WorkingDirectory = ProjectPaths.Directory(projectFile),
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
        };
        startInfo.ArgumentList.Add("restore");
        // The full path, because the restore runs in the project's own directory: a project file
        // named relative to this host's working directory would not be found from there.
        startInfo.ArgumentList.Add(Path.GetFullPath(projectFile));
        startInfo.ArgumentList.Add("--nologo");
        // The reported cause is read by a maintainer and compared across machines, so pin the SDK's
        // own message language rather than letting the operator's locale decide what it says.
        startInfo.Environment["DOTNET_CLI_UI_LANGUAGE"] = "en";

        try
        {
            using var process = Process.Start(startInfo);
            if (process is null)
                return "restore_failed: the .NET SDK could not be started";
            // Both streams are drained while the process runs: a restore writing more than one
            // pipe buffer would otherwise block forever on a full pipe nobody is reading.
            var standardOutput = process.StandardOutput.ReadToEndAsync();
            var standardError = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(RestoreTimeoutMilliseconds))
            {
                process.Kill(entireProcessTree: true);
                return $"restore_failed: no result after {RestoreTimeoutMilliseconds / 1000} seconds";
            }
            if (process.ExitCode == 0)
                return null;
            return $"restore_failed: {Condense(standardError.Result, standardOutput.Result)}";
        }
        catch (Exception exception)
        {
            return $"restore_failed: {exception.Message}";
        }
    }

    // A failed restore prints its diagnosis in the last few lines; the rest is progress noise that
    // would bury the cause in the reported reason.
    private static string Condense(string standardError, string standardOutput)
    {
        var lines = (standardError.Trim().Length > 0 ? standardError : standardOutput)
            .Split('\n')
            .Select(line => line.Trim())
            .Where(line => line.Length > 0)
            .ToList();
        var tail = string.Join("; ", lines.TakeLast(3));
        return tail.Length > 400 ? tail[..400] : tail.Length > 0 ? tail : "no diagnostic output";
    }
}
