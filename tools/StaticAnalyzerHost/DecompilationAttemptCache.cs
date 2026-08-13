using System.Text.Json;
using System.Text.Json.Nodes;

internal sealed class DecompilationAttemptCache
{
    private const int CacheVersion = 1;
    private readonly string root;

    internal DecompilationAttemptCache(string? cacheRoot)
    {
        root = string.IsNullOrWhiteSpace(cacheRoot)
            ? DefaultRoot()
            : Path.GetFullPath(cacheRoot);
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

    private static string DefaultRoot()
    {
        var configuredRoot = Environment.GetEnvironmentVariable("DECOMPILATION_CACHE_ROOT");
        var baseRoot = string.IsNullOrWhiteSpace(configuredRoot)
            ? Path.Combine(Directory.GetCurrentDirectory(), "data", "decompilation_cache")
            : configuredRoot;
        return Path.Combine(baseRoot, "host");
    }
}