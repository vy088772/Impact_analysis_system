"""
ASPX 解析器
用於解析 ASP.NET WebForms 的 .aspx 和 .ascx 檔案
提取後端程式碼引用、控制項、事件處理等
"""

import re
from typing import List, Dict, Optional, Set, Tuple
from pathlib import Path
from dataclasses import dataclass, field

from .models import FileAnalysisResult, FileType, FrameworkType, CodeLocation


@dataclass
class ASPXControl:
    """ASPX 控制項"""
    control_type: str       # 控制項類型 (例如: asp:TextBox, asp:Button)
    control_id: str         # 控制項 ID
    properties: Dict[str, str] = field(default_factory=dict)  # 屬性
    events: Dict[str, str] = field(default_factory=dict)      # 事件處理 (例如: OnClick="Button1_Click")
    line_number: int = 0
    start_pos: int = 0      # 開始標籤在檔案內容中的字元位移（供判斷是否落在某容器範圍內用）


@dataclass
class ASPXDirective:
    """ASPX 指示詞"""
    directive_type: str     # 指示詞類型 (例如: Page, Control, Master)
    attributes: Dict[str, str] = field(default_factory=dict)
    line_number: int = 0


@dataclass
class ASPXCodeBehind:
    """ASPX 後端程式碼參考"""
    code_file: str          # 後端程式碼檔案 (例如: Default.aspx.cs)
    class_name: str         # 類別名稱
    inherits: str = ""      # 繼承的基底類別


class ASPXParser:
    """ASPX 解析器"""
    
    # 正規表達式模式
    DIRECTIVE_PATTERN = r'<%@\s*(\w+)\s+([^%]*?)%>'
    CONTROL_PATTERN = r'<(asp|uc\d+):(\w+)\s+([^>]*?)/?>'
    SERVER_CONTROL_PATTERN = r'<(\w+)\s+runat="server"([^>]*?)/?>'
    INLINE_CODE_PATTERN = r'<%([^%]+)%>'
    DATABIND_PATTERN = r'<%#([^%]+)%>'
    SCRIPT_BLOCK_PATTERN = r'<script\s+runat="server"[^>]*?>(.*?)</script>'
    
    def __init__(self):
        """初始化解析器"""
        self.current_file = None
        self.errors = []
        self.warnings = []
        
        print(f"✅ ASPX 解析器已初始化")
    
    def parse_file(self, file_path: str) -> FileAnalysisResult:
        """
        解析 ASPX/ASCX 檔案
        
        Args:
            file_path: 檔案路徑
        
        Returns:
            FileAnalysisResult: 分析結果
        """
        self.current_file = file_path
        self.errors = []
        self.warnings = []
        
        file_path_obj = Path(file_path)
        
        # 讀取檔案內容
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.errors.append(f"讀取檔案失敗: {e}")
            return self._create_error_result(file_path)
        
        # 判斷檔案類型
        file_type = FileType.ASPX if file_path_obj.suffix == '.aspx' else FileType.ASCX
        
        # 建立結果物件
        result = FileAnalysisResult(
            file_path=file_path,
            file_type=file_type,
            framework=FrameworkType.WEBFORMS,
            line_count=content.count('\n') + 1
        )
        
        # 解析 ASPX 內容
        directives = self._extract_directives(content)
        controls = self._extract_controls(content)
        code_behind = self._extract_code_behind(directives, file_path)
        inline_code = self._extract_inline_code(content)
        
        # 提取事件處理方法
        event_handlers = self._extract_event_handlers(controls)
        
        # 提取畫面實際顯示給使用者看的欄位文字（GridView 欄位 HeaderText、Label.Text 等），
        # 並依所屬的 GridView/DataGrid 分組、附上該 Grid 的事件處理（OnRowCommand 等）
        result.ui_fields = self._extract_ui_fields(content, controls)
        
        # 儲存到結果（使用 dependencies 暫存）
        result.dependencies.add(f"CodeBehind: {code_behind.code_file if code_behind else 'N/A'}")
        result.dependencies.add(f"Controls: {len(controls)}")
        result.dependencies.add(f"EventHandlers: {len(event_handlers)}")
        
        # 如果有內嵌程式碼區塊
        if inline_code:
            result.warnings.append(f"發現 {len(inline_code)} 個內嵌程式碼區塊")
        
        result.errors = self.errors
        result.warnings.extend(self.warnings)
        
        return result
    
    def _extract_directives(self, content: str) -> List[ASPXDirective]:
        """提取 ASPX 指示詞"""
        directives = []
        
        matches = re.finditer(self.DIRECTIVE_PATTERN, content, re.IGNORECASE | re.DOTALL)
        
        for match in matches:
            directive_type = match.group(1)  # Page, Control, Master 等
            attributes_str = match.group(2)
            
            # 解析屬性
            attributes = self._parse_attributes(attributes_str)
            
            line_num = content[:match.start()].count('\n') + 1
            
            directives.append(ASPXDirective(
                directive_type=directive_type,
                attributes=attributes,
                line_number=line_num
            ))
        
        return directives
    
    def _extract_controls(self, content: str) -> List[ASPXControl]:
        """提取 ASP.NET 控制項"""
        controls = []
        
        # 模式 1: ASP.NET 標準控制項 <asp:TextBox ...>
        matches1 = re.finditer(self.CONTROL_PATTERN, content, re.IGNORECASE)
        
        for match in matches1:
            prefix = match.group(1)          # asp 或 uc1
            control_type = match.group(2)    # TextBox, Button 等
            attributes_str = match.group(3)
            
            attributes = self._parse_attributes(attributes_str)
            control_id = attributes.get('ID', attributes.get('id', 'unknown'))
            
            # 提取事件
            events = {}
            for key, value in attributes.items():
                if key.startswith('On'):
                    events[key] = value
            
            line_num = content[:match.start()].count('\n') + 1
            
            controls.append(ASPXControl(
                control_type=f"{prefix}:{control_type}",
                control_id=control_id,
                properties=attributes,
                events=events,
                line_number=line_num,
                start_pos=match.start()
            ))
        
        # 模式 2: HTML Server 控制項 <input runat="server" ...>
        matches2 = re.finditer(self.SERVER_CONTROL_PATTERN, content, re.IGNORECASE)
        
        for match in matches2:
            tag_name = match.group(1)
            attributes_str = match.group(2)
            
            attributes = self._parse_attributes(attributes_str)
            control_id = attributes.get('ID', attributes.get('id', 'unknown'))
            
            events = {}
            for key, value in attributes.items():
                if key.startswith('On') or key.startswith('on'):
                    events[key] = value
            
            line_num = content[:match.start()].count('\n') + 1
            
            controls.append(ASPXControl(
                control_type=f"html:{tag_name}",
                control_id=control_id,
                properties=attributes,
                events=events,
                line_number=line_num,
                start_pos=match.start()
            ))
        
        return controls
    
    def _extract_code_behind(
        self, 
        directives: List[ASPXDirective], 
        aspx_file: str
    ) -> Optional[ASPXCodeBehind]:
        """提取後端程式碼參考"""
        
        # 從 Page/Control 指示詞找出 CodeBehind 和 Inherits
        for directive in directives:
            if directive.directive_type.lower() in ['page', 'control', 'master']:
                code_file = directive.attributes.get('CodeBehind') or directive.attributes.get('CodeFile')
                inherits = directive.attributes.get('Inherits', '')
                
                if code_file or inherits:
                    # 推斷類別名稱
                    class_name = inherits.split('.')[-1] if inherits else ''
                    
                    # 如果沒有 CodeBehind，嘗試根據慣例推斷
                    if not code_file:
                        aspx_path = Path(aspx_file)
                        code_file = f"{aspx_path.stem}.aspx.cs"
                    
                    return ASPXCodeBehind(
                        code_file=code_file,
                        class_name=class_name,
                        inherits=inherits
                    )
        
        return None
    
    def _extract_event_handlers(self, controls: List[ASPXControl]) -> Set[str]:
        """提取所有事件處理方法名稱"""
        handlers = set()
        
        for control in controls:
            for event_name, handler_name in control.events.items():
                if handler_name:
                    handlers.add(handler_name)
        
        return handlers
    
    # 會在畫面上顯示欄位標題文字的控制項（GridView/DataGrid 欄位定義）
    _HEADER_TEXT_CONTROLS = {
        'boundfield', 'templatefield', 'hyperlinkfield',
        'checkboxfield', 'buttonfield', 'commandfield', 'imagefield',
    }
    # 本身就是顯示用文字的控制項（畫面上的標籤/按鈕文字）
    _DISPLAY_TEXT_CONTROLS = {
        'label', 'button', 'linkbutton', 'literal', 'checkbox', 'radiobutton',
    }
    # 會把欄位分組、且本身帶有 OnRowCommand/OnRowDataBound 等事件的容器控制項
    _GRID_CONTAINER_TYPES = {'gridview', 'datagrid'}

    def _compute_container_spans(self, content: str) -> Dict[int, int]:
        """
        找出每個 GridView/DataGrid 開始標籤的字元位移 → 對應結束標籤結尾位移。
        用堆疊配對同名開合標籤（處理同一頁多個/理論上巢狀的情形）；
        self-closing（無子節點）的容器不會有對應範圍，略過即可。
        """
        spans: Dict[int, int] = {}
        for type_name in self._GRID_CONTAINER_TYPES:
            open_pattern = re.compile(rf'<asp:{type_name}\b[^>]*?(/?)>', re.IGNORECASE)
            close_pattern = re.compile(rf'</asp:{type_name}\s*>', re.IGNORECASE)
            tagged: List[Tuple[int, str, int]] = []  # (位置, open/close, 結束位移)
            for m in open_pattern.finditer(content):
                if m.group(1) == '/':
                    continue  # self-closing，沒有子節點需要配對
                tagged.append((m.start(), 'open', m.end()))
            for m in close_pattern.finditer(content):
                tagged.append((m.start(), 'close', m.end()))
            tagged.sort(key=lambda t: t[0])
            
            stack: List[int] = []
            for pos, kind, end in tagged:
                if kind == 'open':
                    stack.append(pos)
                elif stack:
                    open_pos = stack.pop()
                    spans[open_pos] = end
        return spans

    def _extract_ui_fields(self, content: str, controls: List[ASPXControl]) -> List[Dict]:
        """
        從控制項清單挑出「畫面上實際顯示給使用者看的文字」，
        例如 GridView 欄位的 HeaderText、Label/Button 的 Text，並依 DataField 補上
        對應的資料欄位名稱。

        落在某個 GridView/DataGrid 範圍內的欄位會依該 Grid 的 ID 分組，並附上該
        Grid 本身的事件處理（例如 OnRowCommand="gvData_RowCommand"、
        OnRowDataBound="gvData_RowDataBound"），方便對照「按下某按鈕/資料繫結時
        會顯示/處理哪些欄位」。不屬於任何 Grid 的控制項（如頁面上的 Label）則
        以獨立項目列出。

        不含 TextBox/DropDownList 等純輸入控制項的 Text（那是預設值，不是欄位名稱），
        也不含只是傳資料用、沒有 HeaderText/Text/DataField 的控制項。
        """
        container_spans = self._compute_container_spans(content)
        
        # 建立每個 Grid 容器的分組（保留原始順序）
        grid_groups: List[Dict] = []
        grid_spans: List[Tuple[int, int, Dict]] = []  # (start, end, group)
        for control in controls:
            control_kind = control.control_type.split(':', 1)[-1].lower()
            if control_kind in self._GRID_CONTAINER_TYPES and control.start_pos in container_spans:
                group = {
                    'kind': 'grid',
                    'control': control.control_type,
                    'id': control.control_id,
                    'events': dict(control.events),
                    'fields': [],
                }
                grid_groups.append(group)
                grid_spans.append((control.start_pos, container_spans[control.start_pos], group))
        
        standalone: List[Dict] = []
        seen: Set[Tuple] = set()
        
        for control in controls:
            control_kind = control.control_type.split(':', 1)[-1].lower()
            
            if control_kind in self._HEADER_TEXT_CONTROLS:
                kind = 'header'
                text = control.properties.get('HeaderText', '').strip()
                data_field = control.properties.get('DataField', '').strip()
            elif control_kind in self._DISPLAY_TEXT_CONTROLS:
                kind = 'label'
                text = control.properties.get('Text', '').strip()
                data_field = ''
            else:
                continue
            
            if not text and not data_field:
                continue
            
            entry: Dict[str, str] = {'control': control.control_type, 'id': control.control_id, 'kind': kind}
            if text:
                entry['text'] = text
            if data_field:
                entry['data_field'] = data_field
            
            dedup_key = (control.control_type, control.control_id, text, data_field)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            
            # 找出此控制項落在哪個 Grid 範圍內；若巢狀重疊，取範圍最小（最貼近）的那個
            best_group = None
            best_span_len = None
            for start, end, group in grid_spans:
                if start <= control.start_pos < end:
                    span_len = end - start
                    if best_span_len is None or span_len < best_span_len:
                        best_group = group
                        best_span_len = span_len
            
            if best_group is not None:
                best_group['fields'].append(entry)
            else:
                standalone.append(entry)
        
        # 只保留有實際欄位內容的分組，避免空的 Grid 群組混入結果
        return [g for g in grid_groups if g['fields']] + standalone
    
    def _extract_inline_code(self, content: str) -> List[str]:
        """提取內嵌程式碼區塊"""
        inline_code = []
        
        # 提取 <% ... %> 區塊
        matches1 = re.finditer(self.INLINE_CODE_PATTERN, content, re.DOTALL)
        for match in matches1:
            code = match.group(1).strip()
            if code and not code.startswith('@') and not code.startswith('#'):
                inline_code.append(code)
        
        # 提取 <script runat="server"> 區塊
        matches2 = re.finditer(self.SCRIPT_BLOCK_PATTERN, content, re.IGNORECASE | re.DOTALL)
        for match in matches2:
            code = match.group(1).strip()
            if code:
                inline_code.append(code)
        
        return inline_code
    
    def _parse_attributes(self, attributes_str: str) -> Dict[str, str]:
        """
        解析屬性字串
        
        例如: ID="txtName" Text="Hello" OnClick="Button1_Click"
        """
        attributes = {}
        
        # 正規表達式: key="value" 或 key='value'
        pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']'
        matches = re.finditer(pattern, attributes_str)
        
        for match in matches:
            key = match.group(1)
            value = match.group(2)
            attributes[key] = value
        
        return attributes
    
    def _create_error_result(self, file_path: str) -> FileAnalysisResult:
        """建立錯誤結果"""
        return FileAnalysisResult(
            file_path=file_path,
            file_type=FileType.ASPX,
            framework=FrameworkType.WEBFORMS,
            errors=self.errors
        )
    
    def find_code_behind_file(self, aspx_file: str) -> Optional[str]:
        """
        尋找對應的後端程式碼檔案
        
        Args:
            aspx_file: ASPX 檔案路徑
        
        Returns:
            後端程式碼檔案路徑，如果找不到則返回 None
        """
        aspx_path = Path(aspx_file)
        
        # 可能的後端檔案名稱
        possible_names = [
            f"{aspx_path.stem}.aspx.cs",
            f"{aspx_path.stem}.ascx.cs",
            f"{aspx_path.stem}.cs"
        ]
        
        # 在同一目錄下搜尋
        for name in possible_names:
            code_file = aspx_path.parent / name
            if code_file.exists():
                return str(code_file)
        
        return None


# ============================================
# 測試程式碼
# ============================================

def main():
    """測試 ASPX 解析器"""
    import sys
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("請輸入 ASPX 檔案路徑: ").strip()
    
    if not Path(file_path).exists():
        print(f"❌ 檔案不存在: {file_path}")
        return
    
    print("=" * 80)
    print("ASPX 解析器測試")
    print("=" * 80)
    
    parser = ASPXParser()
    result = parser.parse_file(file_path)
    
    print(f"\n檔案: {result.file_path}")
    print(f"類型: {result.file_type.value}")
    print(f"框架: {result.framework.value}")
    print(f"總行數: {result.line_count}")
    
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
    
    # 嘗試找出後端檔案
    code_behind = parser.find_code_behind_file(file_path)
    if code_behind:
        print(f"\n✅ 找到後端程式碼: {code_behind}")
    else:
        print(f"\n⚠️  找不到後端程式碼檔案")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
