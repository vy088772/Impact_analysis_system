using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

internal sealed class DecompilationAttemptCache
{
    private const int CacheVersion = 1;
    private readonly string root;

    // Computed once per cache instance, not once per TryGet/Save call: a refresh may
    // call decompile-wrapper for dozens of receiver types, each constructing its own
    // Program invocation, but within one such invocation the host binary never changes.
    private readonly string? hostIdentity;

    internal DecompilationAttemptCache(string? cacheRoot)
    {
        root = string.IsNullOrWhiteSpace(cacheRoot)
            ? DefaultRoot()
            : Path.GetFullPath(cacheRoot);
        hostIdentity = ComputeHostIdentity();
    }

    internal bool TryGet(
        string assemblyIdentity,
        string receiverType,
        out JsonElement response)
    {
        response = default;
        try
        {
            var path = CachePath(assemblyIdentity);
            if (!File.Exists(path))
                return false;
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var rootElement = document.RootElement;
            if (!IsCurrentDocument(rootElement, assemblyIdentity)
                || !rootElement.TryGetProperty("attempts", out var attempts)
                || !attempts.TryGetProperty(receiverType, out var attempt)
                || !AttemptMatchesHost(attempt)
                || !attempt.TryGetProperty("response", out var cachedResponse))
                return false;
            response = cachedResponse.Clone();
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    // host_identity is tracked per receiver-type attempt, not once for the whole
    // document: one DLL (e.g. IQCS's CommonLibrary.dll) can hold dozens of receiver
    // types cached in the same file, and a refresh re-verifies them one at a time.
    // Checking it at the document level would either wipe every sibling entry on the
    // first re-save, or let a still-stale sibling ride along as "fresh" once the
    // document's own field was bumped by an unrelated receiver type -- exactly the
    // silent staleness ADR-0026 exists to rule out. An entry with no host_identity at
    // all (written before this change) is a miss too, the same as a mismatch.
    private bool AttemptMatchesHost(JsonElement attempt)
        => hostIdentity is not null
            && attempt.TryGetProperty("host_identity", out var storedHostIdentity)
            && storedHostIdentity.GetString() == hostIdentity;

    internal void Save(
        string assemblyIdentity,
        string receiverType,
        JsonElement response)
    {
        string? temporaryPath = null;
        try
        {
            Directory.CreateDirectory(root);
            var document = LoadDocument(assemblyIdentity) ?? new JsonObject();
            document["cache_version"] = CacheVersion;
            document["assembly_identity"] = assemblyIdentity;
            var attempts = document["attempts"] as JsonObject ?? new JsonObject();
            document["attempts"] = attempts;
            attempts[receiverType] = new JsonObject
            {
                ["saved_at"] = DateTimeOffset.UtcNow.ToString("O"),
                ["host_identity"] = hostIdentity,
                ["response"] = JsonNode.Parse(response.GetRawText()),
            };

            var path = CachePath(assemblyIdentity);
            temporaryPath = path + $".{Guid.NewGuid():N}.tmp";
            File.WriteAllText(temporaryPath, document.ToJsonString(new JsonSerializerOptions
            {
                WriteIndented = true,
            }));
            File.Move(temporaryPath, path, true);
            temporaryPath = null;
        }
        catch (Exception)
        {
            return;
        }
        finally
        {
            if (temporaryPath is not null)
                File.Delete(temporaryPath);
        }
    }

    private JsonObject? LoadDocument(string assemblyIdentity)
    {
        var path = CachePath(assemblyIdentity);
        if (!File.Exists(path))
            return null;
        try
        {
            var document = JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
            return document is not null && IsCurrentDocument(document, assemblyIdentity)
                ? document
                : null;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private string CachePath(string assemblyIdentity)
        => Path.Combine(root, $"{assemblyIdentity}.json");

    private static bool IsCurrentDocument(JsonElement document, string assemblyIdentity)
        => document.TryGetProperty("cache_version", out var version)
            && version.GetInt32() == CacheVersion
            && document.TryGetProperty("assembly_identity", out var identity)
            && identity.GetString() == assemblyIdentity;

    private static bool IsCurrentDocument(JsonObject document, string assemblyIdentity)
        => document["cache_version"]?.GetValue<int>() == CacheVersion
            && document["assembly_identity"]?.GetValue<string>() == assemblyIdentity;

    private static string? ComputeHostIdentity()
    {
        try
        {
            var hostPath = Assembly.GetExecutingAssembly().Location;
            if (string.IsNullOrEmpty(hostPath))
                hostPath = Environment.ProcessPath;
            if (string.IsNullOrEmpty(hostPath) || !File.Exists(hostPath))
                return null;
            return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(hostPath))).ToLowerInvariant();
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static string DefaultRoot()
    {
        var configuredRoot = Environment.GetEnvironmentVariable("DECOMPILATION_CACHE_ROOT");
        var baseRoot = string.IsNullOrWhiteSpace(configuredRoot)
            ? Path.Combine(Directory.GetCurrentDirectory(), "data", "decompilation_cache")
            : configuredRoot;
        return Path.Combine(baseRoot, "host");
    }
}