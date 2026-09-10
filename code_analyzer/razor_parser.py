"""
Razor 解析器
用於解析 ASP.NET MVC/Core 的 .cshtml 檔案
提取 Razor 語法、HTML 輔助方法、Tag Helpers、內嵌 C# 程式碼等
"""

import re
from typing import List, Dict, Optional, Set
from pathlib import Path
from dataclasses import dataclass, field

from .models import FileAnalysisResult, FileType, FrameworkType, CodeLocation, StoredProcedureCall


@dataclass
class RazorDirective:
    """Razor 指示詞"""
    directive_type: str     # 指示詞類型 (@model, @using, @inject 等)
    value: str              # 指示詞值
    line_number: int = 0


@dataclass
class RazorCodeBlock:
    """Razor 程式碼區塊"""
    block_type: str         # 區塊類型 (code, functions, section 等)
    code: str               # 程式碼內容
    line_number: int = 0


@dataclass
class RazorHelper:
    """Razor HTML 輔助方法"""
    helper_type: str        # 輔助方法類型 (Html, Url, Ajax 等)
    method_name: str        # 方法名稱 (TextBoxFor, ActionLink 等)
    parameters: List[str] = field(default_factory=list)
    line_number: int = 0


class RazorParser:
    """Razor 解析器"""
    
    # 正規表達式模式
    DIRECTIVE_PATTERN = r'@(model|using|inject|inherits|namespace|page|section|attribute|implements)\s+([^\n]+)'
    CODE_BLOCK_PATTERN = r'@\{([^}]*)\}'
    FUNCTIONS_BLOCK_PATTERN = r'@functions\s*\{([^}]*)\}'
    SECTION_PATTERN = r'@section\s+(\w+)\s*\{(.*?)\}'
    
    # HTML Helpers
    HTML_HELPER_PATTERN = r'@(Html|Url|Ajax)\.(\w+)\('
    
    # Tag Helpers (ASP.NET Core)
    TAG_HELPER_PATTERN = r'<(\w+)\s+([^>]*?)asp-([^>]*?)>'
    
    # 內嵌表達式
    INLINE_EXPRESSION_PATTERN = r'@(\w+(?:\.\w+)*)'
    
    # Razor 註解
    RAZOR_COMMENT_PATTERN = r'@\*.*?\*@'

    # 查詢/清單畫面的欄位標題（純 HTML，比照 ASPXParser 的 TH_PATTERN）
    TH_PATTERN = r'<th\b[^>]*>(.*?)</th>'
    # 欄位標籤。Core 慣例常見 <label asp-for="Prop">...</label>；asp-for 屬性存在時，
    # 即使標籤內沒有可讀文字（Core 的 LabelTagHelper 會在執行期依模型屬性的
    # [Display] attribute 自動產生文字，markup 裡因此完全看不到字面文字），仍要
    # 貢獻它命名的模型屬性，交由 razor_display_field_resolver 事後解析。
    LABEL_PATTERN = re.compile(r'<label\b([^>]*)>(.*?)</label>', re.IGNORECASE | re.DOTALL)
    ASP_FOR_PATTERN = re.compile(r'asp-for\s*=\s*"([^"]+)"', re.IGNORECASE)

    def __init__(self):
        """初始化解析器"""
        self.current_file = None
        self.errors = []
        self.warnings = []
        
        print(f"✅ Razor 解析器已初始化")
    
    def parse_file(self, file_path: str) -> FileAnalysisResult:
        """
        解析 Razor (.cshtml) 檔案
        
        Args:
            file_path: 檔案路徑
        
        Returns:
            FileAnalysisResult: 分析結果
        """
        self.current_file = file_path
        self.errors = []
        self.warnings = []
        
        # 讀取檔案內容
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.errors.append(f"讀取檔案失敗: {e}")
            return self._create_error_result(file_path)
        
        # 建立結果物件
        result = FileAnalysisResult(
            file_path=file_path,
            file_type=FileType.RAZOR,
            framework=self._detect_framework(content),
            line_count=content.count('\n') + 1
        )
        
        # 解析 Razor 內容
        directives = self._extract_directives(content)
        code_blocks = self._extract_code_blocks(content)
        helpers = self._extract_html_helpers(content)
        tag_helpers = self._extract_tag_helpers(content)
        
        # 提取 Model 類型
        model_type = self._extract_model_type(directives)
        if model_type:
            result.dependencies.add(f"Model: {model_type}")
        
        # 提取 using
        for directive in directives:
            if directive.directive_type == 'using':
                result.using_statements.append(directive.value.strip())
        
        # 儲存統計資訊
        result.dependencies.add(f"Directives: {len(directives)}")
        result.dependencies.add(f"CodeBlocks: {len(code_blocks)}")
        result.dependencies.add(f"HtmlHelpers: {len(helpers)}")
        result.dependencies.add(f"TagHelpers: {len(tag_helpers)}")

        # 畫面上實際顯示給使用者看的欄位文字，形狀比照 ASPXParser 的 ui_fields，
        # 讓 view-layer 摘要（service/analyze_service._view_layer_summary）不必
        # 為框架分支處理。
        result.ui_fields = self._extract_ui_fields(content)
        
        # 檢查是否有內嵌 SQL（不建議）
        inline_sql = self._check_inline_sql(content)
        if inline_sql:
            result.warnings.append(f"發現 {len(inline_sql)} 個內嵌 SQL 查詢（不建議在 View 中使用）")
        
        result.errors = self.errors
        result.warnings.extend(self.warnings)
        
        return result
    
    def _detect_framework(self, content: str) -> FrameworkType:
        """偵測使用的框架"""
        # ASP.NET Core 特徵
        if '@page' in content.lower() or 'asp-' in content:
            return FrameworkType.DOTNET_CORE
        
        # ASP.NET MVC (Framework)
        if '@Html.' in content or '@Url.' in content or '@Ajax.' in content:
            return FrameworkType.MVC
        
        return FrameworkType.MVC
    
    def _extract_directives(self, content: str) -> List[RazorDirective]:
        """提取 Razor 指示詞"""
        directives = []
        
        matches = re.finditer(self.DIRECTIVE_PATTERN, content, re.IGNORECASE)
        
        for match in matches:
            directive_type = match.group(1).lower()
            value = match.group(2).strip()
            line_num = content[:match.start()].count('\n') + 1
            
            directives.append(RazorDirective(
                directive_type=directive_type,
                value=value,
                line_number=line_num
            ))
        
        return directives
    
    def _extract_code_blocks(self, content: str) -> List[RazorCodeBlock]:
        """提取 Razor 程式碼區塊"""
        code_blocks = []
        
        # @{ ... } 區塊
        matches1 = re.finditer(self.CODE_BLOCK_PATTERN, content, re.DOTALL)
        for match in matches1:
            code = match.group(1).strip()
            line_num = content[:match.start()].count('\n') + 1
            
            code_blocks.append(RazorCodeBlock(
                block_type='code',
                code=code,
                line_number=line_num
            ))
        
        # @functions { ... } 區塊
        matches2 = re.finditer(self.FUNCTIONS_BLOCK_PATTERN, content, re.DOTALL)
        for match in matches2:
            code = match.group(1).strip()
            line_num = content[:match.start()].count('\n') + 1
            
            code_blocks.append(RazorCodeBlock(
                block_type='functions',
                code=code,
                line_number=line_num
            ))
        
        # @section Name { ... } 區塊
        matches3 = re.finditer(self.SECTION_PATTERN, content, re.DOTALL)
        for match in matches3:
            section_name = match.group(1)
            code = match.group(2).strip()
            line_num = content[:match.start()].count('\n') + 1
            
            code_blocks.append(RazorCodeBlock(
                block_type=f'section:{section_name}',
                code=code,
                line_number=line_num
            ))
        
        return code_blocks
    
    def _extract_html_helpers(self, content: str) -> List[RazorHelper]:
        """提取 HTML 輔助方法"""
        helpers = []
        
        matches = re.finditer(self.HTML_HELPER_PATTERN, content)
        
        for match in matches:
            helper_type = match.group(1)  # Html, Url, Ajax
            method_name = match.group(2)  # TextBoxFor, ActionLink 等
            line_num = content[:match.start()].count('\n') + 1
            
            helpers.append(RazorHelper(
                helper_type=helper_type,
                method_name=method_name,
                line_number=line_num
            ))
        
        return helpers
    
    def _extract_tag_helpers(self, content: str) -> List[Dict]:
        """提取 Tag Helpers (ASP.NET Core)"""
        tag_helpers = []
        
        matches = re.finditer(self.TAG_HELPER_PATTERN, content, re.IGNORECASE)
        
        for match in matches:
            tag_name = match.group(1)
            asp_attr = match.group(3)
            line_num = content[:match.start()].count('\n') + 1
            
            tag_helpers.append({
                'tag': tag_name,
                'attribute': f'asp-{asp_attr}',
                'line': line_num
            })
        
        return tag_helpers
    
    def _extract_model_type(self, directives: List[RazorDirective]) -> Optional[str]:
        """提取 @model 類型"""
        for directive in directives:
            if directive.directive_type == 'model':
                return directive.value
        return None

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """去除 HTML 標籤，只留下純文字內容。"""
        return re.sub(r'<[^>]+>', '', text).strip()

    def _extract_ui_fields(self, content: str) -> List[Dict]:
        """
        擷取畫面上實際顯示給使用者看的欄位文字，來源有二：

        1. 純 HTML 標記文字——`<th>` 欄位標題、`<label>` 內的文字。
        2. 模型繫結屬性（`asp-for="Prop"`）命名的模型屬性——當 `<label>` 完全沒有
           可讀文字時（Core 的 LabelTagHelper 會在執行期依模型屬性的 [Display]
           attribute 自動產生文字），仍貢獻它命名的屬性，讓「畫面上有這個欄位」
           這件事不會因為 markup 裡沒有字面文字就答不出來。這個屬性名稱是否能
           進一步解析出實際顯示文字，由 `razor_display_field_resolver`（讀取
           模型類別與 .resx 資源檔）在掃描完 C# 檔案後接手，這個解析器只看得到
           單一 .cshtml 檔案，看不到模型類別。
        """
        fields: List[Dict] = []

        for match in re.finditer(self.TH_PATTERN, content, re.IGNORECASE | re.DOTALL):
            text = self._strip_html_tags(match.group(1))
            if text:
                fields.append({'kind': 'header', 'text': text})

        for match in self.LABEL_PATTERN.finditer(content):
            attrs_str, inner = match.group(1), match.group(2)
            text = self._strip_html_tags(inner)
            asp_for = self.ASP_FOR_PATTERN.search(attrs_str)

            entry: Dict[str, str] = {'kind': 'label'}
            if text:
                entry['text'] = text
            if asp_for:
                entry['data_field'] = asp_for.group(1)
            if text or asp_for:
                fields.append(entry)

        return fields

    def _check_inline_sql(self, content: str) -> List[str]:
        """檢查內嵌 SQL（不建議做法）"""
        sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'EXEC', 'EXECUTE']
        inline_sql = []
        
        for keyword in sql_keywords:
            pattern = rf'["\'].*?{keyword}\s+.*?["\']'
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                inline_sql.append(match.group(0))
        
        return inline_sql
    
    def _create_error_result(self, file_path: str) -> FileAnalysisResult:
        """建立錯誤結果"""
        return FileAnalysisResult(
            file_path=file_path,
            file_type=FileType.RAZOR,
            framework=FrameworkType.MVC,
            errors=self.errors
        )
    
    def find_controller(self, razor_file: str) -> Optional[str]:
        """
        根據 Razor 檔案路徑推斷對應的 Controller
        
        例如:
        Views/Home/Index.cshtml -> HomeController
        Areas/Admin/Views/User/Edit.cshtml -> Areas/Admin/Controllers/UserController
        
        Args:
            razor_file: Razor 檔案路徑
        
        Returns:
            Controller 名稱
        """
        path = Path(razor_file)
        parts = path.parts
        
        # 找出 Views 的位置
        if 'Views' in parts:
            views_index = parts.index('Views')
            if views_index + 1 < len(parts):
                controller_name = parts[views_index + 1]
                return f"{controller_name}Controller"
        
        # 處理 Areas
        if 'Areas' in parts and 'Views' in parts:
            areas_index = parts.index('Areas')
            views_index = parts.index('Views')
            if views_index + 1 < len(parts):
                area_name = parts[areas_index + 1]
                controller_name = parts[views_index + 1]
                return f"Areas/{area_name}/Controllers/{controller_name}Controller"
        
        return None


# ============================================
# 測試程式碼
# ============================================

def main():
    """測試 Razor 解析器"""
    import sys
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("請輸入 Razor 檔案路徑 (.cshtml): ").strip()
    
    if not Path(file_path).exists():
        print(f"❌ 檔案不存在: {file_path}")
        return
    
    print("=" * 80)
    print("Razor 解析器測試")
    print("=" * 80)
    
    parser = RazorParser()
    result = parser.parse_file(file_path)
    
    print(f"\n檔案: {result.file_path}")
    print(f"類型: {result.file_type.value}")
    print(f"框架: {result.framework.value}")
    print(f"總行數: {result.line_count}")
    
    print(f"\nUsing 語句:")
    for using in result.using_statements:
        print(f"   - {using}")
    
    print(f"\n相依性:")
    for dep in result.dependencies:
        print(f"   - {dep}")
    
    if result.warnings:
        print(f"\n⚠️  警告:")
        for warning in result.warnings:
            print(f"   - {warning}")
    
    if result.errors:
        print(f"\n❌ 錯誤:")
        for error in result.errors:
            print(f"   - {error}")
    
    # 推斷 Controller
    controller = parser.find_controller(file_path)
    if controller:
        print(f"\n✅ 推斷的 Controller: {controller}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
