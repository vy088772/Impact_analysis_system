# tools/list_azure_repos.py
"""
列出 Azure DevOps 專案底下的所有 Git 儲存庫（Repo）。

用途：
    協助盤點每個 Azure DevOps Project 包含哪些 Repo，作為填寫
    `AZURE_PROJECT_MAP`（system -> project/repo 映射）的依據。

設定來源（.env）：
    AZURE_DEVOPS_ORG       - 組織名稱（例如 topmost）
    AZURE_DEVOPS_PAT       - Personal Access Token（需要 Code: Read 權限）
    AZURE_DEVOPS_PROJECTS  - （選用）要列出的專案，逗號分隔；
                             例如 "System Dept 1,System Dept 2"。
                             留空時會自動列出組織內所有專案。
    SPEC_RAG_CATALOG_PATH  - （選用）spec-rag 的 system_catalog.json 路徑；
                             留空時預設讀取 ../llamaindex-spec-rag/catalog/system_catalog.json，
                             用來把 repo 名稱自動比對到 system_id。

輸出：
    - 終端機列出每個專案的所有 repo（含分支、大小、是否停用、比對到的 system）
    - 結構化 JSON：output/azure_repos.json（每個 repo 一筆，system 欄位可手動補）
    - 可直接貼進 .env 的 AZURE_PROJECT_MAP（僅含已比對且啟用的 repo）

執行：
    python tools/list_azure_repos.py

注意：PAT 為機密，請只寫在 .env，勿提交版控或貼到對話中。
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

API_VERSION = "7.1"
BASE = "https://dev.azure.com"

# 預設 spec-rag 的 system_catalog.json 位置（用來自動比對 system）
DEFAULT_CATALOG = (
    Path(__file__).resolve().parent.parent.parent
    / "llamaindex-spec-rag" / "catalog" / "system_catalog.json"
)
# 輸出 JSON 位置
OUTPUT_JSON = Path(__file__).resolve().parent.parent / "output" / "azure_repos.json"


def _load_env() -> tuple[str, str, list[str]]:
    """從 .env 讀取 org / pat / projects。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已載入環境設定: {env_path}")
    else:
        load_dotenv()
        print("⚠️  找不到 .env，改用系統環境變數")

    org = os.getenv("AZURE_DEVOPS_ORG", "").strip()
    pat = os.getenv("AZURE_DEVOPS_PAT", "").strip()

    raw_projects = os.getenv("AZURE_DEVOPS_PROJECTS", "").strip()
    projects = [p.strip() for p in raw_projects.split(",") if p.strip()]

    if not org:
        sys.exit("❌ 缺少 AZURE_DEVOPS_ORG")
    if not pat or pat in ("your_pat_here", "***"):
        sys.exit("❌ 缺少有效的 AZURE_DEVOPS_PAT（請在 .env 填入實際 PAT）")

    return org, pat, projects


def _auth_header(pat: str) -> dict[str, str]:
    """Azure DevOps 使用 Basic Auth：username 留空，password 放 PAT。"""
    token = base64.b64encode(f":{pat}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _api_get(url: str, headers: dict[str, str]) -> dict:
    """呼叫 REST API 並回傳 JSON，對常見錯誤給出清楚訊息。"""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 203):
            sys.exit("❌ 認證失敗（401/203）：請確認 PAT 正確且具備 Code: Read 權限")
        if e.code == 404:
            sys.exit(f"❌ 找不到資源（404）：{url}")
        sys.exit(f"❌ HTTP {e.code}：{e.reason}\n    URL: {url}")
    except urllib.error.URLError as e:
        sys.exit(f"❌ 連線失敗：{e.reason}")


def list_projects(org: str, headers: dict[str, str]) -> list[str]:
    """列出組織內所有專案名稱。"""
    url = f"{BASE}/{urllib.parse.quote(org)}/_apis/projects?api-version={API_VERSION}"
    data = _api_get(url, headers)
    return [p["name"] for p in data.get("value", [])]


def list_repos(org: str, project: str, headers: dict[str, str]) -> list[dict]:
    """列出單一專案底下的所有 Git Repo。"""
    url = (
        f"{BASE}/{urllib.parse.quote(org)}/{urllib.parse.quote(project)}"
        f"/_apis/git/repositories?api-version={API_VERSION}"
    )
    data = _api_get(url, headers)
    return data.get("value", [])


def _load_catalog_system_ids() -> list[str]:
    """從 spec-rag 的 system_catalog.json 載入 system_id 清單（用於自動比對）。"""
    catalog_path = Path(os.getenv("SPEC_RAG_CATALOG_PATH", str(DEFAULT_CATALOG)))
    if not catalog_path.exists():
        print(f"⚠️  找不到 system_catalog（{catalog_path}），略過 system 自動比對")
        return []
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        ids = [s.get("system_id", "") for s in data.get("systems", []) if s.get("system_id")]
        print(f"✅ 已載入 {len(ids)} 個 system 供比對：{catalog_path}")
        return ids
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  讀取 system_catalog 失敗（{e}），略過 system 自動比對")
        return []


def _match_system(repo_name: str, system_ids: list[str]) -> tuple[str, str]:
    """
    將 repo 名稱比對到 system_id。
    回傳 (system, source)；source 為 exact / contains / ""（未命中）。
    """
    rn = repo_name.lower()
    for sid in system_ids:
        if rn == sid.lower():
            return sid, "exact"
    for sid in system_ids:
        s = sid.lower()
        if s in rn or rn in s:
            return sid, "contains"
    return "", ""


def main() -> None:
    org, pat, projects = _load_env()
    headers = _auth_header(pat)
    system_ids = _load_catalog_system_ids()

    if not projects:
        print("ℹ️  未指定 AZURE_DEVOPS_PROJECTS，將列出組織內所有專案…")
        projects = list_projects(org, headers)

    print(f"\n組織：{org}")
    print(f"專案數：{len(projects)}\n")

    result: dict = {
        "org": org,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "projects": {},
    }
    total = active = matched = 0
    map_active: list[str] = []

    for project in projects:
        repos = list_repos(org, project, headers)
        repos.sort(key=lambda r: r.get("name", ""))
        entries: list[dict] = []
        print("=" * 70)
        print(f"📁 專案：{project}（{len(repos)} 個 repo）")
        print("-" * 70)
        for r in repos:
            name = r.get("name", "")
            branch = (r.get("defaultBranch") or "").replace("refs/heads/", "")
            size_mb = round(r.get("size", 0) / (1024 * 1024), 1)
            disabled = bool(r.get("isDisabled")) or name.startswith("ZZ_Disabled")
            system, source = _match_system(name, system_ids)

            total += 1
            if not disabled:
                active += 1
            if system:
                matched += 1
                if not disabled:
                    map_active.append(f"{system}:{project}/{name}")

            entries.append({
                "repo": name,
                "system": system,
                "system_source": source,
                "default_branch": branch,
                "size_mb": size_mb,
                "disabled": disabled,
                "web_url": r.get("webUrl", ""),
                "remote_url": r.get("remoteUrl", ""),
            })

            tag = f"→ {system}" if system else ""
            flag = "（停用）" if disabled else ""
            print(f"  • {name:<40} branch={branch or '-':<15} {size_mb}MB {flag}{tag}")
        result["projects"][project] = entries
        print()

    result["summary"] = {
        "projects": len(projects),
        "repos_total": total,
        "repos_active": active,
        "system_matched": matched,
    }

    # 寫出 JSON
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 70)
    print(f"📊 統計：共 {total} 個 repo（啟用 {active}、停用 {total - active}），"
          f"自動比對到 system 的有 {matched} 個")
    print(f"💾 已寫出：{OUTPUT_JSON}")
    print("-" * 70)
    print("📝 AZURE_PROJECT_MAP（僅含已比對且啟用的 repo，可直接貼進 .env）：")
    print("AZURE_PROJECT_MAP=" + ",".join(map_active))
    print()
    print("提示：未自動比對到的 repo，請打開上述 JSON 檔，手動補上 system 欄位。")


if __name__ == "__main__":
    main()
