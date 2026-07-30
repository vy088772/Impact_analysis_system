using System.Security.Cryptography;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

internal static class CSharpAnalyzer
{
    internal static CSharpAnalysis Analyze(string inputPath)
    {
        var bytes = File.ReadAllBytes(inputPath);
        var source = File.ReadAllText(inputPath);
        var root = CSharpSyntaxTree.ParseText(source, path: inputPath).GetCompilationUnitRoot();
        var methods = root.DescendantNodes().OfType<MethodDeclarationSyntax>().Select(method => new MethodSourceSpan(
            method.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault()?.Identifier.Text ?? "",
            method.Identifier.Text,
            method.SpanStart,
            method.Span.End)).ToList();

        return new CSharpAnalysis(
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            methods);
    }
}

internal sealed record CSharpAnalysis(string SourceId, List<MethodSourceSpan> Methods);
internal sealed record MethodSourceSpan(string ClassName, string MethodName, int StartOffset, int EndOffset);