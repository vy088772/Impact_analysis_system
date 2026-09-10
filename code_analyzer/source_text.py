# code_analyzer/source_text.py
"""把一個 C# 原始檔的位元組解碼成文字，用 .NET 自己的規則。

只有一個理由會改動這個檔案：C# 原始檔的解碼規則。

實測的儲存庫證明嚴格解碼不可行：ETR 的 `Program.cs` 是 UTF-8 以外的編碼
（註解是 Big5），嚴格解碼會直接丟例外。讀不到那個檔案的後果不是少一行註
解，而是整個掃描根的連線解析安靜地消失——正是這份程式碼要防止的失敗模式。

無法解碼的位元組換成替代字元，讓程式碼本體（永遠是 ASCII）照樣讀得出來。
帶著位元組順序記號的 UTF-16／UTF-32 檔則先照它自己的編碼解，否則整份檔案
會變成亂碼，裡面的宣告與呼叫會一起消失。
"""

from __future__ import annotations


def decode_source_bytes(source_bytes: bytes) -> str:
    """Match .NET's BOM-aware source decoding for Roslyn span alignment."""
    if source_bytes.startswith(b"\xff\xfe\x00\x00") or source_bytes.startswith(b"\x00\x00\xfe\xff"):
        return source_bytes.decode("utf-32")
    if source_bytes.startswith(b"\xff\xfe") or source_bytes.startswith(b"\xfe\xff"):
        return source_bytes.decode("utf-16")
    return source_bytes.decode("utf-8-sig", errors="replace")
