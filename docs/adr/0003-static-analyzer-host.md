# Package Roslyn and ScriptDom Behind One Analyzer Host

Integrate the Roslyn and ScriptDom source projects behind one versioned StaticAnalyzerHost rather than making Python orchestrate two unrelated binaries. Source projects belong in the repository and build outputs belong in deployment artifacts, keeping runtime integration narrow without committing generated DLL, bin, or obj content.

## Consequences

Python calls one host with separate C# and SQL analysis commands and validates one JSON contract version. Analyzer availability and .NET runtime failures are reported before refresh or scan work begins.