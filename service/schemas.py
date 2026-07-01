# service/schemas.py
"""
影響分析服務的請求/回應資料模型（Pydantic）。

對應設計書 §5.1 / §5.2。所有欄位皆為純靜態分析結果，不含 AI 推理。
"""
from __future__ import annotations

from typing import List, Dict
from pydantic import BaseModel, Field


class AzureSource(BaseModel):
    """原始碼來源（由 spec-rag 從 system_catalog.json 的 azure 區塊解析後帶入）。"""
    project: str = ""        # Azure DevOps 專案；留空時退回本機 PROJECT_ROOT
    repo: str = ""           # 儲存庫（可多系統共用）
    branch: str = ""         # 留空使用預設分支
    path: str = ""           # repo 內子資料夾，區分同 repo 的多系統；留空則整個 repo


class AnalyzeRequest(BaseModel):
    """POST /analyze 請求。"""
    system: str = ""                         # RAG 命中的系統 id（僅供記錄/快取鍵）
    source: AzureSource = Field(default_factory=AzureSource)
    program_names: List[str]                 # 要分析的程式名清單
    include_snippets: bool = True            # 是否回傳程式碼片段（S2b 實作）
    include_sp_defs: bool = False            # 是否連資料庫擷取 SP 完整定義（需 DB 連線）
    fk_depth: int = 1                        # FK 連動追蹤層數（S3 實作）
    database: str = ""                        # 資料庫簡稱（FK 查詢用；留空則用預設或跳過）
    refresh: bool = False                    # True → git pull + 重新解析，覆寫快取


class CodeSnippet(BaseModel):
    file: str
    label: str = ""          # 片段標籤（類別.方法名 或 "file head"）
    lines: str = ""          # 例如 "120-156"
    text: str = ""


class ProgramAnalysis(BaseModel):
    """單一程式（檔案）的靜態分析結果。"""
    program: str                             # 對應請求的程式名
    file: str                                # 實際定位到的檔案路徑（相對 repo）
    framework: str = ""
    methods: List[Dict] = Field(default_factory=list)
    stored_procedures: List[str] = Field(default_factory=list)
    tables: List[str] = Field(default_factory=list)
    related_tables: List[str] = Field(default_factory=list)  # FK 連動的相關資料表（S3）
    call_chains: List[List[str]] = Field(default_factory=list)
    code_snippets: List[CodeSnippet] = Field(default_factory=list)
    sp_definitions: List[Dict] = Field(default_factory=list)  # SP 完整定義（include_sp_defs=True 時）


class AnalyzeResponse(BaseModel):
    programs: List[ProgramAnalysis] = Field(default_factory=list)
    not_found: List[str] = Field(default_factory=list)
    source_root: str = ""                    # 實際分析的本機路徑（除錯用）


class RefreshRequest(BaseModel):
    """POST /refresh 請求：更新某系統的程式碼並重新解析。"""
    system: str = ""
    source: AzureSource = Field(default_factory=AzureSource)


class RefreshResponse(BaseModel):
    source_root: str = ""
    files: int = 0
    sp_relations: int = 0
    table_relations: int = 0
