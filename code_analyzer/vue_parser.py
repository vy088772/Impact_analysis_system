"""
Vue 解析器
用於解析 Vue 單檔案元件 (.vue)
提取 template、script、API 呼叫等
"""

import re
import json
from typing import List, Dict, Optional, Set
from pathlib import Path
from dataclasses import dataclass, field

from .models import FileAnalysisResult, FileType, FrameworkType, CodeLocation, APIEndpoint, HTTPMethod


@dataclass
class VueComponent:
    """Vue 元件資訊"""
    name: str
    props: List[str] = field(default_factory=list)
    data_properties: List[str] = field(default_factory=list)
    computed_properties: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    lifecycle_hooks: List[str] = field(default_factory=list)


@dataclass
class APICall:
    """API 呼叫"""
    method: str             # GET, POST, PUT, DELETE
    url: str                # API 端點
    line_number: int = 0


class VueParser:
    """Vue 解析器"""
    
    # Vue 生命週期鉤子
    LIFECYCLE_HOOKS = [
        'beforeCreate', 'created', 'beforeMount', 'mounted',
        'beforeUpdate', 'updated', 'beforeDestroy', 'destroyed',
        'activated', 'deactivated', 'errorCaptured'
    ]
    
    # API 呼叫模式
    API_PATTERNS = [
        r'axios\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]',
        r'fetch\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]',
        r'\$http\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]',
        r'this\.\$api\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]',
    ]
    
    def __init__(self):
        """初始化解析器"""
        self.current_file = None
        self.errors = []
        self.warnings = []
        
        print(f"✅ Vue 解析器已初始化")
    
    def parse_file(self, file_path: str) -> FileAnalysisResult:
        """
        解析 Vue 檔案
        
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
            file_type=FileType.VUE,
            framework=FrameworkType.VUE_WEBAPI,
            line_count=content.count('\n') + 1
        )
        
        # 提取各個區塊
        template = self._extract_section(content, 'template')
        script = self._extract_section(content, 'script')
        style = self._extract_section(content, 'style')
        
        # 解析 script 區塊
        if script:
            component = self._parse_component(script)
            
            # 儲存元件資訊
            result.dependencies.add(f"Component: {component.name}")
            result.dependencies.add(f"Props: {len(component.props)}")
            result.dependencies.add(f"Methods: {len(component.methods)}")
            result.dependencies.add(f"Computed: {len(component.computed_properties)}")
            
            # 提取 API 呼叫
            api_calls = self._extract_api_calls(script)
            result.dependencies.add(f"API_Calls: {len(api_calls)}")
            
            # 儲存到 referenced_files（API 端點）
            for api_call in api_calls:
                result.referenced_files.add(f"{api_call.method} {api_call.url}")
        
        result.errors = self.errors
        result.warnings.extend(self.warnings)
        
        return result
    
    def _extract_section(self, content: str, section_name: str) -> Optional[str]:
        """
        提取 Vue 檔案的區塊
        
        Args:
            content: 檔案內容
            section_name: 區塊名稱 (template, script, style)
        
        Returns:
            區塊內容
        """
        pattern = rf'<{section_name}[^>]*?>(.*?)</{section_name}>'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        
        if match:
            return match.group(1).strip()
        
        return None
    
    def _parse_component(self, script: str) -> VueComponent:
        """解析 Vue 元件"""
        component = VueComponent(name=self._extract_component_name(script))
        
        # 提取 props
        component.props = self._extract_props(script)
        
        # 提取 data
        component.data_properties = self._extract_data_properties(script)
        
        # 提取 computed
        component.computed_properties = self._extract_computed(script)
        
        # 提取 methods
        component.methods = self._extract_methods(script)
        
        # 提取生命週期鉤子
        component.lifecycle_hooks = self._extract_lifecycle_hooks(script)
        
        return component
    
    def _extract_component_name(self, script: str) -> str:
        """提取元件名稱"""
        # 從 export default { name: 'ComponentName' }
        pattern = r'name\s*:\s*[\'"`]([^\'"` ]+)[\'"`]'
        match = re.search(pattern, script)
        
        if match:
            return match.group(1)
        
        # 從檔案名稱推斷
        if self.current_file:
            return Path(self.current_file).stem
        
        return "UnknownComponent"
    
    def _extract_props(self, script: str) -> List[str]:
        """提取 props"""
        props = []
        
        # 模式 1: props: ['prop1', 'prop2']
        pattern1 = r'props\s*:\s*\[([^\]]+)\]'
        match1 = re.search(pattern1, script)
        if match1:
            props_str = match1.group(1)
            props = re.findall(r'[\'"`]([^\'"` ]+)[\'"`]', props_str)
        
        # 模式 2: props: { prop1: String, prop2: { type: Number } }
        pattern2 = r'props\s*:\s*\{([^}]+)\}'
        match2 = re.search(pattern2, script)
        if match2 and not props:
            props_str = match2.group(1)
            props = re.findall(r'(\w+)\s*:', props_str)
        
        return props
    
    def _extract_data_properties(self, script: str) -> List[str]:
        """提取 data 屬性"""
        properties = []
        
        # 尋找 data() { return { ... } }
        pattern = r'data\s*\(\s*\)\s*\{[^}]*return\s*\{([^}]+)\}'
        match = re.search(pattern, script, re.DOTALL)
        
        if match:
            data_str = match.group(1)
            properties = re.findall(r'(\w+)\s*:', data_str)
        
        return properties
    
    def _extract_computed(self, script: str) -> List[str]:
        """提取 computed 屬性"""
        computed = []
        
        pattern = r'computed\s*:\s*\{([^}]+)\}'
        match = re.search(pattern, script, re.DOTALL)
        
        if match:
            computed_str = match.group(1)
            computed = re.findall(r'(\w+)\s*(?:\(|:)', computed_str)
        
        return computed
    
    def _extract_methods(self, script: str) -> List[str]:
        """提取 methods"""
        methods = []
        
        # 尋找 methods: { methodName() { } }
        pattern = r'methods\s*:\s*\{(.*?)\n\s*\}'
        match = re.search(pattern, script, re.DOTALL)
        
        if match:
            methods_str = match.group(1)
            # 提取方法名稱
            methods = re.findall(r'(\w+)\s*(?:\(|:)', methods_str)
        
        return methods
    
    def _extract_lifecycle_hooks(self, script: str) -> List[str]:
        """提取生命週期鉤子"""
        hooks = []
        
        for hook in self.LIFECYCLE_HOOKS:
            pattern = rf'{hook}\s*\('
            if re.search(pattern, script):
                hooks.append(hook)
        
        return hooks
    
    def _extract_api_calls(self, script: str) -> List[APICall]:
        """提取 API 呼叫"""
        api_calls = []
        
        # axios.get('/api/users')
        pattern1 = r'axios\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]'
        matches1 = re.finditer(pattern1, script, re.IGNORECASE)
        for match in matches1:
            method = match.group(1).upper()
            url = match.group(2)
            line_num = script[:match.start()].count('\n') + 1
            
            api_calls.append(APICall(
                method=method,
                url=url,
                line_number=line_num
            ))
        
        # fetch('/api/users')
        pattern2 = r'fetch\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]'
        matches2 = re.finditer(pattern2, script, re.IGNORECASE)
        for match in matches2:
            url = match.group(1)
            line_num = script[:match.start()].count('\n') + 1
            
            api_calls.append(APICall(
                method='GET',  # fetch 預設是 GET
                url=url,
                line_number=line_num
            ))
        
        # this.$http.get('/api/users')
        pattern3 = r'\$http\.(get|post|put|delete|patch)\s*\(\s*[\'"`]([^\'"` ]+)[\'"`]'
        matches3 = re.finditer(pattern3, script, re.IGNORECASE)
        for match in matches3:
            method = match.group(1).upper()
            url = match.group(2)
            line_num = script[:match.start()].count('\n') + 1
            
            api_calls.append(APICall(
                method=method,
                url=url,
                line_number=line_num
            ))
        
        return api_calls
    
    def _create_error_result(self, file_path: str) -> FileAnalysisResult:
        """建立錯誤結果"""
        return FileAnalysisResult(
            file_path=file_path,
            file_type=FileType.VUE,
            framework=FrameworkType.VUE_WEBAPI,
            errors=self.errors
        )


# ============================================
# 測試程式碼
# ============================================

def main():
    """測試 Vue 解析器"""
    import sys
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("請輸入 Vue 檔案路徑 (.vue): ").strip()
    
    if not Path(file_path).exists():
        print(f"❌ 檔案不存在: {file_path}")
        return
    
    print("=" * 80)
    print("Vue 解析器測試")
    print("=" * 80)
    
    parser = VueParser()
    result = parser.parse_file(file_path)
    
    print(f"\n檔案: {result.file_path}")
    print(f"類型: {result.file_type.value}")
    print(f"框架: {result.framework.value}")
    print(f"總行數: {result.line_count}")
    
    print(f"\n相依性:")
    for dep in result.dependencies:
        print(f"   - {dep}")
    
    print(f"\nAPI 呼叫:")
    for ref in result.referenced_files:
        print(f"   - {ref}")
    
    if result.warnings:
        print(f"\n⚠️  警告:")
        for warning in result.warnings:
            print(f"   - {warning}")
    
    if result.errors:
        print(f"\n❌ 錯誤:")
        for error in result.errors:
            print(f"   - {error}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
