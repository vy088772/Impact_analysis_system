"""
C# 程式碼解析器
用於解析 C# 程式碼的類別、方法、SQL 查詢、API 端點等
"""

import re
from typing import List, Optional, Set, Tuple, Dict
from pathlib import Path
from datetime import datetime
from config.sp_detector_config import SPDetectionConfig
from .db_connection_tracker import DBConnectionTracker
from .models import (
    FileAnalysisResult, ClassInfo, MethodInfo, ParameterInfo, PropertyInfo,
    SQLQuery, APIEndpoint, StoredProcedureCall, CodeLocation,
    FileType, FrameworkType, SQLQueryType, HTTPMethod
)


class CSharpParser:
    """C# 程式碼解析器"""
    
    # ============================================
    # 正規表達式模式
    # ============================================
    
    # 命名空間
    NAMESPACE_PATTERN = r'namespace\s+([\w\.]+)'
    
    # Using 引用
    USING_PATTERN = r'using\s+([\w\.]+)\s*;'
    
    # 類別定義
    CLASS_PATTERN = r'(public|internal|private|protected)?\s*(abstract|sealed|static|partial)?\s*class\s+(\w+)(?:\s*:\s*([\w\s,<>\.]+))?'
    
    # 方法定義
    # 存取修飾詞為 optional：C# 允許類別成員省略修飾詞（預設為 private），
    # 例如 WebForms code-behind 常見的 `void CheckQryData() { ... }`。
    # 錨定在行首（可有前導空白）以避免誤配到 `new Foo(...)`、`await Foo(...)`
    # 這類「兩個以空白分隔的識別字後接左括號」的陳述式。
    METHOD_PATTERN = r'^[ \t]*(public|private|protected|internal)?\s*(static\s+)?(virtual\s+)?(override\s+)?(abstract\s+)?(async\s+)?([\w\<\>\[\]]+)\s+(\w+)\s*\('

    # METHOD_PATTERN 錨定行首後，仍可能誤配到「關鍵字 識別字(」的陳述式
    # （例如 `new SqlParameter(...)`、`await FooAsync()`），故以傳回型別
    # 是否為下列關鍵字作為過濾依據。
    _METHOD_RETURN_TYPE_DENYLIST = {
        "new", "await", "return", "throw", "yield", "else", "do", "try",
        "using", "lock", "checked", "unchecked", "typeof", "sizeof",
        "nameof", "case", "goto", "break", "continue",
    }
    
    # 屬性定義
    PROPERTY_PATTERN = r'(public|private|protected|internal)\s+(static\s+)?([\w\<\>\[\]]+)\s+(\w+)\s*\{\s*(get|set)'
    
    # SQL 查詢（多種格式）
    SQL_PATTERNS = [
        # 逐字字串 @"..."
        r'@"([^"]*?(?:SELECT|INSERT|UPDATE|DELETE|EXEC|EXECUTE|CREATE|ALTER|DROP)[^"]*?)"',
        # 一般雙引號字串 "..."
        r'"([^"]*?(?:SELECT|INSERT|UPDATE|DELETE|EXEC|EXECUTE|CREATE|ALTER|DROP)[^"]*?)"',
        # 單引號字串 '...'
        r"'([^']*?(?:SELECT|INSERT|UPDATE|DELETE|EXEC|EXECUTE|CREATE|ALTER|DROP)[^']*?)'",
        # 多行字串（C# 11+ 的 raw string literals）
        r'"""([^"]*?(?:SELECT|INSERT|UPDATE|DELETE|EXEC|EXECUTE|CREATE|ALTER|DROP)[^"]*?)"""',
    ]
    
    # API 路由
    ROUTE_PATTERN = r'\[Route\(["\']([^"\']+)["\']\)\]'
    API_CONTROLLER_PATTERN = r'\[ApiController\]'
    
    # HTTP 方法屬性
    HTTP_METHOD_PATTERN = r'\[(HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch|HttpOptions|HttpHead)(?:\(["\']([^"\']*?)["\']\))?\]'
    
    # 認證與授權
    AUTHORIZE_PATTERN = r'\[Authorize(?:\(Roles\s*=\s*["\']([^"\']+)["\']\))?\]'
    
    def __init__(self, sp_config_file: Optional[str] = None):
        """
        初始化解析器
        
        Args:
            sp_config_file: 預存程序偵測設定檔路徑（可選）
        """
        self.current_file = None
        self.current_line = 0
        self.errors = []
        self.warnings = []
        
        # 載入預存程序偵測設定
        self.sp_config = SPDetectionConfig(sp_config_file)
        # 建立資料庫連線追蹤器
        self.db_tracker = DBConnectionTracker()
        
        print(f"✅ C# 解析器已初始化")
    
    def parse_file(self, file_path: str) -> FileAnalysisResult:
        """
        解析單一 C# 檔案
        
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
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            # 嘗試其他編碼
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()
            except Exception as e:
                return FileAnalysisResult(
                    file_path=file_path,
                    file_type=FileType.CSHARP,
                    framework=FrameworkType.UNKNOWN,
                    errors=[f"讀取檔案失敗: {e}"]
                )
        except Exception as e:
            return FileAnalysisResult(
                file_path=file_path,
                file_type=FileType.CSHARP,
                framework=FrameworkType.UNKNOWN,
                errors=[f"讀取檔案失敗: {e}"]
            )
        
        # 建立結果物件
        result = FileAnalysisResult(
            file_path=file_path,
            file_type=FileType.CSHARP,
            framework=self._detect_framework(content, file_path_obj.name),
            line_count=len(lines),
            analysis_time=datetime.now()
        )
        # 首先分析資料庫連線
        self.db_tracker.analyze_connections(content)
        
        # 解析各種元素
        result.namespaces = self._extract_namespaces(content)
        result.using_statements = self._extract_using_statements(content)
        result.classes = self._extract_classes(content, lines)
        result.sql_queries = self._extract_sql_queries(content, lines)  # 會使用 db_tracker
        result.stored_procedure_calls = self._extract_stored_procedure_calls(content, lines)  # 會使用 db_tracker
        result.api_endpoints = self._extract_api_endpoints(content, lines)
        result.dependencies = set(result.using_statements)
        
        # 統計行數
        counts = self._count_lines(lines)
        result.code_line_count = counts[0]
        result.comment_line_count = counts[1]
        result.blank_line_count = counts[2]
        
        # 記錄錯誤和警告
        result.errors = self.errors.copy()
        result.warnings = self.warnings.copy()
        
        return result
    
    def _detect_framework(self, content: str, filename: str) -> FrameworkType:
        """偵測框架類型"""
        # .NET Core / .NET 5+
        if any(ns in content for ns in ['using Microsoft.AspNetCore', 'using Microsoft.Extensions']):
            if 'using Microsoft.AspNetCore.Mvc' in content:
                return FrameworkType.MVC
            elif '[ApiController]' in content:
                return FrameworkType.WEBAPI
            return FrameworkType.DOTNET_CORE
        
        # MVC
        if 'using System.Web.Mvc' in content or ': Controller' in content:
            return FrameworkType.MVC
        
        # Web API
        if 'using System.Web.Http' in content or '[ApiController]' in content or 'ApiController' in content:
            return FrameworkType.WEBAPI
        
        # WebForms
        if 'using System.Web.UI' in content or filename.endswith('.aspx.cs'):
            return FrameworkType.WEBFORMS
        
        # Blazor
        if 'using Microsoft.AspNetCore.Components' in content:
            return FrameworkType.BLAZOR
        
        # .NET Framework (預設)
        return FrameworkType.DOTNET_FRAMEWORK
    
    def _extract_namespaces(self, content: str) -> List[str]:
        """提取命名空間"""
        namespaces = re.findall(self.NAMESPACE_PATTERN, content)
        return list(set(namespaces))  # 去重
    
    def _extract_using_statements(self, content: str) -> List[str]:
        """提取 using 引用"""
        usings = re.findall(self.USING_PATTERN, content)
        return list(set(usings))  # 去重
    
    def _extract_classes(self, content: str, lines: List[str]) -> List[ClassInfo]:
        """提取類別資訊"""
        classes = []
        
        # 找出所有類別定義
        class_matches = list(re.finditer(self.CLASS_PATTERN, content, re.MULTILINE))
        
        for match in class_matches:
            access_modifier = match.group(1) or 'internal'
            class_modifiers = (match.group(2) or '').strip()
            class_name = match.group(3)
            inheritance = match.group(4) or ''
            
            # 計算行號
            line_num = content[:match.start()].count('\n') + 1
            
            # 提取命名空間
            namespace = self._find_namespace_for_position(content, match.start())
            
            # 解析繼承與介面
            base_class = None
            interfaces = []
            if inheritance:
                parts = [p.strip() for p in inheritance.split(',')]
                # 簡單判斷：大寫開頭且含有 I 開頭的通常是介面
                for part in parts:
                    if part.startswith('I') and len(part) > 1 and part[1].isupper():
                        interfaces.append(part)
                    elif not base_class:
                        base_class = part
            
            # 建立類別資訊
            class_info = ClassInfo(
                name=class_name,
                namespace=namespace or '',
                file_path=self.current_file,
                base_class=base_class,
                interfaces=interfaces,
                access_modifier=access_modifier,
                location=CodeLocation(self.current_file, line_num)
            )
            
            # 解析類別修飾詞
            if 'static' in class_modifiers:
                class_info.is_static = True
            if 'abstract' in class_modifiers:
                class_info.is_abstract = True
            if 'sealed' in class_modifiers:
                class_info.is_sealed = True
            if 'partial' in class_modifiers:
                class_info.is_partial = True
            
            # 判斷類別類型
            class_info.is_controller = 'Controller' in class_name or base_class in ['Controller', 'ApiController', 'ControllerBase']
            class_info.is_model = any(kw in class_name for kw in ['Model', 'Entity', 'DTO', 'ViewModel'])
            class_info.is_service = any(kw in class_name for kw in ['Service', 'Manager', 'Helper'])
            class_info.is_repository = 'Repository' in class_name
            
            # 找出類別的範圍
            class_start = match.start()
            class_end = self._find_class_end(content, class_start)
            
            # 提取類別中的成員
            class_content = content[class_start:class_end]
            class_info.methods = self._extract_methods(class_content, class_start, content, lines)
            class_info.properties = self._extract_properties(class_content, class_start, content)
            
            classes.append(class_info)
        
        return classes
    
    def _find_namespace_for_position(self, content: str, position: int) -> Optional[str]:
        """找出特定位置所屬的命名空間"""
        content_before = content[:position]
        namespaces = re.findall(self.NAMESPACE_PATTERN, content_before)
        return namespaces[-1] if namespaces else None
    
    def _find_class_end(self, content: str, class_start: int) -> int:
        """找出類別的結束位置"""
        # 找到類別開始的大括號
        brace_start = content.find('{', class_start)
        if brace_start == -1:
            return len(content)
        
        # 計算大括號配對
        brace_count = 1
        pos = brace_start + 1
        
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        
        return pos
    
    def _extract_methods(
        self, 
        class_content: str, 
        class_start: int,
        full_content: str,
        lines: List[str]
    ) -> List[MethodInfo]:
        """提取類別中的方法"""
        methods = []
        
        method_matches = list(re.finditer(self.METHOD_PATTERN, class_content, re.MULTILINE))
        
        for match in method_matches:
            return_type = match.group(7)
            method_name = match.group(8)

            # METHOD_PATTERN 的存取修飾詞已改為 optional，錨定行首後仍可能誤配到
            # 「關鍵字 識別字(」的陳述式（如 new/await/return...），以傳回型別是否
            # 為關鍵字過濾掉這類誤判。
            if return_type in self._METHOD_RETURN_TYPE_DENYLIST:
                continue

            # C# 允許類別成員省略存取修飾詞，此時預設為 private。
            access_modifier = match.group(1) or "private"
            is_static = bool(match.group(2))
            is_virtual = bool(match.group(3))
            is_override = bool(match.group(4))
            is_abstract = bool(match.group(5))
            is_async = bool(match.group(6))
            
            # 計算實際行號
            line_num = full_content[:class_start + match.start()].count('\n') + 1
            
            # 提取參數
            params = self._extract_method_parameters(class_content, match.end())
            
            # 提取方法體
            method_start = match.start()
            method_body = self._extract_method_body(class_content, method_start)
            
            # 提取方法體中的 SQL 查詢
            sql_queries = self._extract_sql_in_text(method_body)
            
            # 提取方法呼叫
            method_calls = self._extract_method_calls(method_body)
            
            # 計算方法行數
            method_line_count = method_body.count('\n') + 1 if method_body else 0
            
            method_info = MethodInfo(
                name=method_name,
                access_modifier=access_modifier,
                return_type=return_type,
                parameters=params,
                location=CodeLocation(self.current_file, line_num),
                is_async=is_async,
                is_static=is_static,
                is_virtual=is_virtual,
                is_override=is_override,
                is_abstract=is_abstract,
                sql_queries=sql_queries,
                calls=method_calls,
                line_count=method_line_count
            )
            
            methods.append(method_info)
        
        return methods
    
    def _extract_method_parameters(self, content: str, start_pos: int) -> List[ParameterInfo]:
        """提取方法參數"""
        # 找出參數括號內的內容
        paren_count = 0
        param_start = -1
        param_end = -1
        
        for i in range(start_pos, min(start_pos + 1000, len(content))):
            if content[i] == '(':
                if paren_count == 0:
                    param_start = i + 1
                paren_count += 1
            elif content[i] == ')':
                paren_count -= 1
                if paren_count == 0:
                    param_end = i
                    break
        
        if param_start == -1 or param_end == -1:
            return []
        
        param_text = content[param_start:param_end].strip()
        if not param_text:
            return []
        
        # 解析參數
        parameters = []
        # 簡單分割（可能需要更複雜的解析處理泛型）
        for param in param_text.split(','):
            param = param.strip()
            if not param:
                continue
            
            # 處理預設值
            default_value = None
            if '=' in param:
                param, default_value = param.split('=', 1)
                param = param.strip()
                default_value = default_value.strip()
            
            # 分離型別和名稱
            parts = param.split()
            if len(parts) >= 2:
                # 處理修飾詞（out, ref, params, this）
                modifiers = []
                while parts[0] in ['out', 'ref', 'params', 'this', 'in']:
                    modifiers.append(parts[0])
                    parts.pop(0)
                
                if len(parts) >= 2:
                    param_type = ' '.join(parts[:-1])
                    param_name = parts[-1]
                    
                    parameters.append(ParameterInfo(
                        name=param_name,
                        type=param_type,
                        default_value=default_value,
                        is_optional=default_value is not None,
                        is_params='params' in modifiers
                    ))
        
        return parameters
    
    def _extract_method_body(self, content: str, method_start: int) -> str:
        """提取方法體"""
        # 找出方法的大括號
        brace_start = content.find('{', method_start)
        if brace_start == -1:
            # 可能是抽象方法或介面方法
            return ""
        
        brace_count = 1
        pos = brace_start + 1
        
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        
        return content[brace_start + 1:pos - 1]
    
    def _extract_properties(
        self,
        class_content: str,
        class_start: int,
        full_content: str
    ) -> List[PropertyInfo]:
        """提取屬性"""
        properties = []
        
        property_matches = list(re.finditer(self.PROPERTY_PATTERN, class_content, re.MULTILINE))
        
        for match in property_matches:
            access_modifier = match.group(1)
            is_static = bool(match.group(2))
            prop_type = match.group(3)
            prop_name = match.group(4)
            accessor = match.group(5)
            
            line_num = full_content[:class_start + match.start()].count('\n') + 1
            
            # 檢查是否有 get 和 set
            prop_text = class_content[match.start():match.end() + 50]
            has_getter = 'get' in prop_text
            has_setter = 'set' in prop_text
            is_auto = '=>' not in prop_text and '{' in prop_text and '}' in prop_text
            
            properties.append(PropertyInfo(
                name=prop_name,
                type=prop_type,
                access_modifier=access_modifier,
                has_getter=has_getter,
                has_setter=has_setter,
                is_auto_property=is_auto,
                location=CodeLocation(self.current_file, line_num)
            ))
        
        return properties
    
    def _extract_sql_in_text(self, text: str) -> List[str]:
        """提取文字中的 SQL 查詢"""
        sql_queries = []
        
        for pattern in self.SQL_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                sql = match.group(1).strip()
                # 過濾太短的或明顯不是 SQL 的
                if len(sql) > 15 and any(kw in sql.upper() for kw in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'EXEC']):
                    sql_queries.append(sql)
        
        return list(set(sql_queries))  # 去重
    
    def _extract_method_calls(self, method_body: str) -> List[str]:
        """提取方法呼叫。

        無限定子呼叫（如 `Foo()`）回傳 `"Foo"`；
        有限定子呼叫（如 `Bar.Foo()` 或 `bar.Foo()`）回傳 `"Bar.Foo"`（保留限定子）。
        保留限定子讓 reference_expander 能判斷該限定子是否恰為一個已知類別名，
        藉此精準解析 `ClassName.Method(...)` 這類靜態工具呼叫（如
        `CommonFunction.AlertMsg`），避免同名方法在多個不相干類別間誤配。
        呼叫端若需要純方法名（如 call_chain_builder 比對同檔案內部呼叫），
        可自行取 `.split('.')[-1]`，或直接用完整字串比對本類別自己的方法名
        （不含限定子的本地呼叫不受影響）。
        """
        # 找出 xxx() 或 xxx.yyy() 格式（限定子選用）
        pattern = r'(?:(\w+)\.)?(\w+)\s*\('
        matches = re.findall(pattern, method_body)

        # 過濾關鍵字和常見方法
        keywords = {
            'if', 'for', 'while', 'switch', 'catch', 'return', 'new', 'throw',
            'var', 'await', 'using', 'lock', 'yield', 'typeof', 'sizeof',
            'ToString', 'GetHashCode', 'Equals', 'GetType'  # 常見方法
        }

        calls: List[str] = []
        for qualifier, name in matches:
            if name in keywords:
                continue
            if qualifier in ("this", "base"):
                qualifier = ""
            calls.append(f"{qualifier}.{name}" if qualifier else name)
        return calls
    
    def _extract_sql_queries(self, content: str, lines: List[str]) -> List[SQLQuery]:
        """
        提取 SQL 查詢（加入資料庫來源追蹤）
        支援：
        1. 方法參數: CreateReader("SELECT ..."), Execute("SELECT ...")  
        2. 變數賦值: string sql = "SELECT ..."
        """
        queries = []
        seen_queries = set()  # 避免重複
        
        # ============================================
        # 🔧 模式 1（優先）: 方法參數中的 SQL
        # 這個模式可以追蹤變數，優先處理
        # ============================================
        method_sql_queries = self._extract_sql_from_method_calls(content)
        
        for sql_info in method_sql_queries:
            sql_text = sql_info['sql']
            
            # 避免重複
            if sql_text in seen_queries:
                continue
            
            seen_queries.add(sql_text)
            
            query_type = self._determine_sql_type(sql_text)
            
            if query_type != SQLQueryType.UNKNOWN:
                tables = self._extract_tables_from_sql(sql_text)
                is_parameterized = '@' in sql_text or '{' in sql_text
                has_join = 'JOIN' in sql_text.upper()
                has_subquery = sql_text.upper().count('SELECT') > 1

                # 追蹤資料庫來源（使用捕獲的變數名稱）
                db_source, conn_var = self._identify_database_source(
                    content, 
                    sql_info['line'], 
                    sql_info.get('variable', '')
                )

                queries.append(SQLQuery(
                    query_text=sql_text,
                    query_type=query_type,
                    tables=tables,
                    location=CodeLocation(self.current_file, sql_info['line']),
                    is_parameterized=is_parameterized,
                    has_join=has_join,
                    has_subquery=has_subquery,
                    database_source=db_source,
                    connection_variable=conn_var
                ))
        
        # ============================================
        # 模式 2: 直接的 SQL 字串（作為後備）
        # ============================================
        for pattern in self.SQL_PATTERNS:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
            
            for match in matches:
                sql_text = match.group(1).strip()
                
                # 過濾太短的
                if len(sql_text) < 10:
                    continue
                
                # 避免重複
                if sql_text in seen_queries:
                    continue
                
                query_type = self._determine_sql_type(sql_text)
                
                if query_type == SQLQueryType.UNKNOWN:
                    continue
                
                seen_queries.add(sql_text)
                
                line_num = content[:match.start()].count('\n') + 1
                tables = self._extract_tables_from_sql(sql_text)
                is_parameterized = '@' in sql_text or '{' in sql_text
                has_join = 'JOIN' in sql_text.upper()
                has_subquery = sql_text.count('SELECT') > 1
                
                # 🔧 修復：即使模式 1 也嘗試追蹤資料庫來源
                # 雖然模式 1 通常捕獲的是字串賦值，但也可能捕獲方法參數中的 SQL
                db_source = None
                conn_var = None
                
                queries.append(SQLQuery(
                    query_text=sql_text,
                    query_type=query_type,
                    tables=tables,
                    location=CodeLocation(self.current_file, line_num),
                    is_parameterized=is_parameterized,
                    has_join=has_join,
                    has_subquery=has_subquery,
                    database_source=db_source,
                    connection_variable=conn_var
                ))
        
        # ============================================
        # 模式 2: 方法參數中的 SQL（新增）
        # ============================================
        # 支援：CreateReader("SELECT ..."), Execute("SELECT ...") 等
        method_sql_queries = self._extract_sql_from_method_calls(content)
        
        for sql_info in method_sql_queries:
            sql_text = sql_info['sql']
            
            # 避免重複
            if sql_text in seen_queries:
                continue
            
            seen_queries.add(sql_text)
            
            query_type = self._determine_sql_type(sql_text)
            
            if query_type != SQLQueryType.UNKNOWN:
                tables = self._extract_tables_from_sql(sql_text)
                is_parameterized = '@' in sql_text or '{' in sql_text
                has_join = 'JOIN' in sql_text.upper()
                has_subquery = sql_text.upper().count('SELECT') > 1

                # 追蹤資料庫來源
                db_source, conn_var = self._identify_database_source(
                    content, 
                    sql_info['line'], 
                    sql_info.get('variable', '')
                )

                queries.append(SQLQuery(
                    query_text=sql_text,
                    query_type=query_type,
                    tables=tables,
                    location=CodeLocation(self.current_file, sql_info['line']),
                    is_parameterized=is_parameterized,
                    has_join=has_join,
                    has_subquery=has_subquery,
                    database_source=db_source,      # 追蹤資料庫
                    connection_variable=conn_var    # 追蹤資料庫
                ))
        
        return queries

    def _extract_sql_from_method_calls(self, content: str) -> List[Dict]:
        """
        從方法呼叫中提取 SQL 查詢
        支援模式：
        1. CreateReader("SELECT ...")
        2. CreateDataSet("SELECT ...")
        3. Execute("SELECT ...")
        4. ExecuteReader("SELECT ...")
        5. Query("SELECT ...")
        等等
        """
        sql_queries = []
        
        # 定義可能包含 SQL 的方法名稱
        sql_methods = [
            'CreateReader',
            'CreateDataSet',
            'CreateTable',
            'Execute',
            'ExecuteReader',
            'ExecuteScalar',
            'ExecuteNonQuery',
            'Query',
            'QueryAsync',
            'QueryFirst',
            'QuerySingle',
            'ExeProcRead',
            'GetDataReader',
            'GetDataSet',
            'GetDataTable',
            'GetFirstValue',      # 🆕 新增：用於取得第一個值
            'Fill',
            'SqlQuery'
        ]
        
        for method_name in sql_methods:
            # 建立正規表達式：方法名稱 + 括號 + SQL 字串
            # 支援多種字串格式：
            # 1. "SELECT ..."
            # 2. @"SELECT ..."  (逐字字串)
            # 3. 'SELECT ...'   (單引號)
            # 捕獲呼叫變數: objPUR.CreateReader(...)

            patterns = [
                # 模式 1: variable.Method("SQL")
                rf'(\w+)\s*\.\s*{method_name}\s*\(\s*"([^"]*?(?:SELECT|INSERT|UPDATE|DELETE)[^"]*?)"',
                # 模式 2: variable.Method(@"SQL")
                rf'(\w+)\s*\.\s*{method_name}\s*\(\s*@"([^"]*?(?:SELECT|INSERT|UPDATE|DELETE)[^"]*?)"',
            ]
            
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
                
                for match in matches:
                    variable_name = match.group(1)  # 捕獲變數名稱
                    sql_text = match.group(2).strip()
                    
                    # 清理 SQL 文字
                    sql_text = self._clean_sql_text(sql_text)
                    
                    # 過濾太短的或明顯不是 SQL 的
                    if len(sql_text) < 10:
                        continue
                    
                    # 必須包含 SQL 關鍵字
                    sql_upper = sql_text.upper()
                    if not any(kw in sql_upper for kw in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'EXEC', 'FROM', 'WHERE']):
                        continue
                    
                    line_num = content[:match.start()].count('\n') + 1
                    
                    sql_queries.append({
                        'sql': sql_text,
                        'line': line_num,
                        'method': method_name,
                        'variable': variable_name  # 儲存變數名稱
                    })
        
        return sql_queries

    def _clean_sql_text(self, sql: str) -> str:
        """
        清理 SQL 文字
        移除多餘的空白、換行等
        """
        # 移除前後空白
        sql = sql.strip()
        
        # 將多個空白合併為一個
        sql = re.sub(r'\s+', ' ', sql)
        
        # 移除註解標記（如果有）
        sql = sql.replace('--', '')
        
        return sql

    def _determine_sql_type(self, sql: str) -> SQLQueryType:
        """判斷 SQL 類型（保持不變）"""
        sql_upper = sql.upper().strip()
        
        # 移除前導空白和註解
        sql_upper = re.sub(r'^\s*--.*?\n', '', sql_upper, flags=re.MULTILINE)
        sql_upper = sql_upper.strip()
        
        if sql_upper.startswith('SELECT'):
            return SQLQueryType.SELECT
        elif sql_upper.startswith('INSERT'):
            return SQLQueryType.INSERT
        elif sql_upper.startswith('UPDATE'):
            return SQLQueryType.UPDATE
        elif sql_upper.startswith('DELETE'):
            return SQLQueryType.DELETE
        elif sql_upper.startswith(('EXEC', 'EXECUTE')):
            return SQLQueryType.PROCEDURE
        elif sql_upper.startswith('CREATE'):
            return SQLQueryType.CREATE
        elif sql_upper.startswith('ALTER'):
            return SQLQueryType.ALTER
        elif sql_upper.startswith('DROP'):
            return SQLQueryType.DROP
        else:
            return SQLQueryType.UNKNOWN
    
    def _extract_tables_from_sql(self, sql: str) -> Set[str]:
        """從 SQL 提取資料表名稱（增強版）"""
        tables = set()
        
        # 清理 SQL
        sql_clean = sql.upper()
        
        # FROM 子句（支援多種格式）
        # FROM TableName
        # FROM [TableName]
        # FROM dbo.TableName
        # FROM [dbo].[TableName]
        from_patterns = [
            r'FROM\s+\[?(\w+)\]?\.\[?(\w+)\]?',  # schema.table（優先匹配）
            r'FROM\s+\[?(\w+)\]?(?:\s+(?:AS\s+)?\w+|\s+|$)',  # table [as alias]，但排除後面有. 的情況
        ]
        
        for pattern in from_patterns:
            matches = re.findall(pattern, sql_clean)
            for match in matches:
                if isinstance(match, tuple):
                    # schema.table 格式，取 table
                    table_name = match[1] if len(match) > 1 and match[1] else match[0]
                else:
                    table_name = match
                
                table_name = self._clean_table_name(table_name)
                # 過濾掉常見的 schema 名稱
                if table_name and len(table_name) > 1 and table_name.upper() not in ('DBO', 'SYS', 'INFORMATION_SCHEMA'):
                    tables.add(table_name)
        
        # JOIN 子句
        join_patterns = [
            r'JOIN\s+\[?(\w+)\]?\.\[?(\w+)\]?',  # schema.table（優先匹配）
            r'JOIN\s+\[?(\w+)\]?(?:\s+(?:AS\s+)?\w+|\s+|$)',  # table [as alias]
        ]
        
        for pattern in join_patterns:
            matches = re.findall(pattern, sql_clean)
            for match in matches:
                if isinstance(match, tuple):
                    table_name = match[1] if len(match) > 1 and match[1] else match[0]
                else:
                    table_name = match
                
                table_name = self._clean_table_name(table_name)
                # 過濾掉常見的 schema 名稱
                if table_name and len(table_name) > 1 and table_name.upper() not in ('DBO', 'SYS', 'INFORMATION_SCHEMA'):
                    tables.add(table_name)
        
        # INSERT INTO（支援 schema.table 格式）
        insert_patterns = [
            r'INSERT\s+INTO\s+\[?(\w+)\]?\.\[?(\w+)\]?',  # schema.table
            r'INSERT\s+INTO\s+\[?(\w+)\]?'                 # table
        ]
        for pattern in insert_patterns:
            insert_matches = re.findall(pattern, sql_clean)
            for match in insert_matches:
                if isinstance(match, tuple):
                    table_name = match[1] if len(match) > 1 and match[1] else match[0]
                else:
                    table_name = match
                table_name = self._clean_table_name(table_name)
                if table_name and len(table_name) > 1 and table_name.upper() not in ('DBO', 'SYS', 'INFORMATION_SCHEMA'):
                    tables.add(table_name)
        
        # UPDATE（支援 schema.table 格式）
        update_patterns = [
            r'UPDATE\s+\[?(\w+)\]?\.\[?(\w+)\]?',  # schema.table
            r'UPDATE\s+\[?(\w+)\]?'                 # table
        ]
        for pattern in update_patterns:
            update_matches = re.findall(pattern, sql_clean)
            for match in update_matches:
                if isinstance(match, tuple):
                    table_name = match[1] if len(match) > 1 and match[1] else match[0]
                else:
                    table_name = match
                table_name = self._clean_table_name(table_name)
                if table_name and len(table_name) > 1 and table_name.upper() not in ('DBO', 'SYS', 'INFORMATION_SCHEMA'):
                    tables.add(table_name)
        
        # DELETE FROM（支援 schema.table 格式）
        delete_patterns = [
            r'DELETE\s+FROM\s+\[?(\w+)\]?\.\[?(\w+)\]?',  # schema.table
            r'DELETE\s+FROM\s+\[?(\w+)\]?'                 # table
        ]
        for pattern in delete_patterns:
            delete_matches = re.findall(pattern, sql_clean)
            for match in delete_matches:
                if isinstance(match, tuple):
                    table_name = match[1] if len(match) > 1 and match[1] else match[0]
                else:
                    table_name = match
                table_name = self._clean_table_name(table_name)
                if table_name and len(table_name) > 1 and table_name.upper() not in ('DBO', 'SYS', 'INFORMATION_SCHEMA'):
                    tables.add(table_name)
        
        return tables

    def _clean_table_name(self, table: str) -> str:
        """清理資料表名稱"""
        if not table:
            return ""
        
        # 移除方括號
        table = table.replace('[', '').replace(']', '')
        
        # 如果有 schema，只取表格名稱
        if '.' in table:
            parts = table.split('.')
            table = parts[-1]
        
        # 移除空白
        table = table.strip()
        
        return table
    
    
    def _extract_stored_procedure_calls(self, content: str, lines: List[str]) -> List[StoredProcedureCall]:
        """
        提取預存程序呼叫（使用設定檔）（加入資料庫來源追蹤）（支援 Service 層）
        """
        calls = []
        
        # ============================================
        # 0. 先建立 SP 名稱變數映射表（支援 MVC 專案的變數賦值模式）
        # ============================================
        sp_variable_map = self._build_sp_variable_map(content)
        
        # ============================================
        # 1. 處理所有封裝方法（從設定檔載入）
        # ============================================
        for method_name in self.sp_config.wrapper_methods:
            # 支援 @"..." 和 schema.name
            pattern = rf'(\w+)\s*\.\s*{method_name}\s*\(\s*(?:@?"([\w\.\[\]]+)"|\'([\w\.\[\]]+)\')'
            matches = re.finditer(pattern, content, re.IGNORECASE)
            
            for match in matches:
                variable_name = match.group(1)  # 捕獲變數名稱
                proc_name = match.group(2) or match.group(3)
                
                # 忽略明顯的 SQL 語句
                if any(kw in proc_name.upper() for kw in ['SELECT ', 'INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'ALTER ', 'DROP ']):
                    continue
                
                # 驗證預存程序名稱
                if not self.sp_config.is_valid_sp_name(proc_name):
                    self.warnings.append(f"預存程序名稱可能無效: {proc_name}")
                    continue
                
                line_num = content[:match.start()].count('\n') + 1
                call_info = self._extract_method_call_detail(content, match.start(), match.end())
                 #  追蹤資料庫來源
                db_source, conn_var = self._identify_database_source(
                    content, 
                    line_num, 
                    variable_name
                )

                calls.append(StoredProcedureCall(
                    procedure_name=proc_name,
                    parameters=call_info['parameters'],
                    location=CodeLocation(self.current_file, line_num),
                    database_source=db_source,      # 追蹤資料庫來源
                    connection_variable=conn_var    # 追蹤資料庫來源
                ))
        
        # ============================================
        # 1.5 處理變數方式傳入的 SP 名稱（MVC 專案常見）
        # ============================================
        variable_calls = self._extract_variable_sp_calls(content, sp_variable_map)
        calls.extend(variable_calls)
        
        # ============================================
        # 2. SqlCommand 模式（根據設定決定是否啟用）
        # ============================================
        if self.sp_config.detect_command_type:
            sqlcommand_calls = self._extract_sqlcommand_stored_procedures(content)
            calls.extend(sqlcommand_calls)
        
        # ============================================
        # 3. 直接 EXEC 模式（根據設定決定是否啟用）
        # ============================================
        if self.sp_config.detect_exec_statements:
            exec_calls = self._extract_direct_exec_calls(content)
            calls.extend(exec_calls)
        # ============================================
        # 4. Dapper 模式（Service 層常用）
        # ============================================
        dapper_calls = self._extract_dapper_sp_calls(content)
        calls.extend(dapper_calls)

        # ============================================
        # 5. Entity Framework 原生 SQL
        # ============================================
        ef_calls = self._extract_ef_sp_calls(content)
        calls.extend(ef_calls)

        # 去重
        return self._deduplicate_sp_calls(calls)
    
    def _build_sp_variable_map(self, content: str) -> Dict[str, str]:
        """
        建立 SP 名稱變數映射表
        
        例如:
        _spName = "usp_ORD_OrdFileSpecMtn_Qry";
        string spName = "usp_GetUser";
        var procName = "usp_GetData";
        
        Returns:
            Dict[變數名稱, SP名稱]
        """
        sp_map = {}
        
        # 模式 1: _spName = "usp_xxx"
        pattern1 = r'(\w+)\s*=\s*"((?:sp|usp|proc)[\w_]+)"'
        matches1 = re.finditer(pattern1, content, re.IGNORECASE)
        for match in matches1:
            var_name = match.group(1)
            sp_name = match.group(2)
            if self.sp_config.is_valid_sp_name(sp_name):
                sp_map[var_name] = sp_name
        
        # 模式 2: string spName = "usp_xxx"
        pattern2 = r'(?:string|var)\s+(\w+)\s*=\s*"((?:sp|usp|proc)[\w_]+)"'
        matches2 = re.finditer(pattern2, content, re.IGNORECASE)
        for match in matches2:
            var_name = match.group(1)
            sp_name = match.group(2)
            if self.sp_config.is_valid_sp_name(sp_name):
                sp_map[var_name] = sp_name
        
        return sp_map
    
    def _extract_variable_sp_calls(self, content: str, sp_variable_map: Dict[str, str]) -> List[StoredProcedureCall]:
        """
        提取使用變數方式傳入的 SP 呼叫
        
        常見模式:
        _spName = "usp_XXX";
        await _db.usp_ExecCmdGetDataTableAsync(_spName, ...);
        
        Args:
            content: 檔案內容
            sp_variable_map: SP 變數映射表
        """
        calls = []
        
        # 支援的自訂 DbContext 方法
        custom_db_methods = [
            'usp_ExecCmdGetDataTableAsync',
            'ExecCmdGetDataTableAsync',
            'ExecuteStoredProcedureAsync',
            'ExecuteStoredProcedure',
            'ExecuteProcedureAsync',
            'ExecuteProcedure',
            'CallStoredProcedure',
            'CallStoredProcedureAsync'
        ]
        
        # 加入原本設定檔中的方法
        all_methods = set(custom_db_methods + self.sp_config.wrapper_methods)
        
        for method_name in all_methods:
            # 模式: _db.Method(variableName, ...)
            pattern = rf'(\w+)\s*\.\s*{method_name}\s*\(\s*(\w+)'
            matches = re.finditer(pattern, content, re.IGNORECASE)
            
            for match in matches:
                db_var = match.group(1)  # 例如: _TOPCSCY_db
                param_var = match.group(2)  # 例如: _spName
                
                # 找出這個呼叫之前「所有」對該變數的賦值，而不是只找最近一次。
                # 常見寫法是「宣告預設值 → 依條件（下拉選單/參數）重新賦值 → 呼叫」
                # （例如 `string sql = "spA"; if (cond) { sql = "spB"; }
                # obj.CreateTable(sql, ...);`）——這種呼叫點實際上依執行期分支可能
                # 呼叫到 spA 或 spB 兩者之一，只回傳「最接近呼叫點的那次賦值」會讓
                # 條件不成立時實際會呼叫到的那個 SP（例如 spA／預設值）完全從分析
                # 結果中消失，使用者問「這個條件為真/為假分別會查到什麼」時就只看
                # 得到其中一個分支的定義。故改為對同一呼叫點的每個候選 SP 名稱各自
                # 建立一筆 StoredProcedureCall（同一行號），讓下游（Impact /analyze
                # 的 SP 定義擷取）能把兩個分支的完整 SQL 定義都撈出來。
                call_position = match.start()
                proc_names = self._find_all_variable_assignments(content, param_var, call_position)
                
                if proc_names:
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # 追蹤資料庫來源
                    db_source, conn_var = self._identify_database_source(
                        content, 
                        line_num, 
                        db_var
                    )
                    
                    for proc_name in proc_names:
                        calls.append(StoredProcedureCall(
                            procedure_name=proc_name,
                            location=CodeLocation(self.current_file, line_num),
                            database_source=db_source,
                            connection_variable=db_var
                        ))
        
        return calls
    
    def _find_all_variable_assignments(self, content: str, var_name: str, position: int) -> List[str]:
        """
        找出「呼叫位置之前」對該變數的所有候選賦值（依原始碼位置排序、去重），
        而不是只取最接近呼叫點的一筆——同一變數若因條件分支（例如依下拉選單值）
        在呼叫前被重新賦值成不同 SP 名稱，這裡會把每個實際出現過的候選值都列出
        （呼叫端 `_extract_variable_sp_calls` 會為每個候選值各自建立一筆呼叫紀錄），
        讓下游可以同時取得所有分支各自實際呼叫的 SP 完整定義，而不是只看到其中一個
        分支、遺漏「條件不成立時預設會呼叫哪個 SP」。

        Args:
            content: 檔案內容
            var_name: 變數名稱
            position: 呼叫位置

        Returns:
            候選 SP 名稱清單（依出現順序去重；找不到任何賦值則回傳空清單）
        """
        content_before = content[:position]

        # 模式 1: varName = "usp_xxx"（含宣告時的初始賦值與後續條件式重新賦值）
        pattern1 = rf'{var_name}\s*=\s*"((?:sp|usp|proc)[\w_]+)"'
        matches1 = list(re.finditer(pattern1, content_before, re.IGNORECASE))

        # 模式 2: string/var varName = "usp_xxx"（僅宣告，理論上是 matches1 的子集，
        # 保留是為了與既有 _find_nearest_variable_assignment 行為一致、避免遺漏
        # 極少數 matches1 pattern 沒吃到但 matches2 吃到的邊界情況）
        pattern2 = rf'(?:string|var)\s+{var_name}\s*=\s*"((?:sp|usp|proc)[\w_]+)"'
        matches2 = list(re.finditer(pattern2, content_before, re.IGNORECASE))

        # 依實際在原始碼中的位置排序，確保「依出現順序去重」是可信的
        all_matches = sorted(matches1 + matches2, key=lambda m: m.start())

        seen: set = set()
        result: List[str] = []
        for m in all_matches:
            sp_name = m.group(1)
            if sp_name in seen:
                continue
            if not self.sp_config.is_valid_sp_name(sp_name):
                continue
            seen.add(sp_name)
            result.append(sp_name)

        return result
    
    def _find_nearest_variable_assignment(self, content: str, var_name: str, position: int) -> Optional[str]:
        """
        找出特定位置之前最近的變數賦值
        
        Args:
            content: 檔案內容
            var_name: 變數名稱
            position: 呼叫位置
        
        Returns:
            SP 名稱或 None
        """
        # 只搜尋呼叫位置之前的內容
        content_before = content[:position]
        
        # 找出所有對該變數的賦值（從後往前找）
        # 模式 1: varName = "usp_xxx"
        pattern1 = rf'{var_name}\s*=\s*"((?:sp|usp|proc)[\w_]+)"'
        matches1 = list(re.finditer(pattern1, content_before, re.IGNORECASE))
        
        # 模式 2: string/var varName = "usp_xxx"
        pattern2 = rf'(?:string|var)\s+{var_name}\s*=\s*"((?:sp|usp|proc)[\w_]+)"'
        matches2 = list(re.finditer(pattern2, content_before, re.IGNORECASE))
        
        # 合併所有匹配。matches1（不要求 string/var 關鍵字，可比對到後續重新賦值，
        # 例如 if 分支內的 `sql = "spSelMasterQryV3";`）與 matches2（僅比對到宣告，
        # 例如 `string sql = "spSelMasterQryV2";`）在文字位置上可能重疊——matches2
        # 命中的宣告，matches1 一定也會命中（同一段文字同時符合兩個 pattern）。
        # 直接 `matches1 + matches2` 串接後取 `[-1]`，並不代表「文字位置最後一筆」，
        # 而是「串接後清單的最後一筆」：一旦程式碼有「宣告 → 條件式重新賦值 → 呼叫」
        # 這種常見寫法（例如依下拉選單值切換要呼叫的 SP），matches2 恰好只會命中
        # 最前面的宣告，串接後反而排在 matches1 找到的重新賦值後面，`[-1]` 就會誤取
        # 到「最前面的宣告」而非「最接近呼叫點的重新賦值」，導致條件分支實際呼叫的
        # SP（例如 spSelMasterQryV3）被忽略、只抓到 if 判斷之前的預設值
        # （spSelMasterQryV2）。修正：依實際在原始碼中的位置（match.start()）排序後
        # 再取最後一筆，才是真正「最接近呼叫位置」的那次賦值。
        all_matches = sorted(matches1 + matches2, key=lambda m: m.start())
        
        if all_matches:
            # 取最後一個（最接近呼叫位置的）
            last_match = all_matches[-1]
            sp_name = last_match.group(1)
            
            # 驗證 SP 名稱
            if self.sp_config.is_valid_sp_name(sp_name):
                return sp_name
        
        return None
    
    def _extract_dapper_sp_calls(self, content: str) -> List[StoredProcedureCall]:
        """
        提取 Dapper 風格的 SP 呼叫
        
        常見模式:
        1. connection.Query<T>("spName", param, commandType: CommandType.StoredProcedure)
        2. connection.Execute("spName", param, commandType: CommandType.StoredProcedure)
        3. connection.QueryAsync<T>("spName", ...)
        4. _db.Query("spName", ...)
        """
        calls = []
        
        # Dapper 方法清單
        dapper_methods = [
            'Query', 'QueryAsync',
            'QueryFirst', 'QueryFirstAsync',
            'QuerySingle', 'QuerySingleAsync',
            'Execute', 'ExecuteAsync',
            'ExecuteScalar', 'ExecuteScalarAsync'
        ]
        
        for method in dapper_methods:
            # 模式: connection.Query<T>("spName", ...)
            # 或: _db.Query("spName", ...)
            pattern = rf'(\w+)\s*\.\s*{method}\s*(?:<[^>]+>)?\s*\(\s*(?:@?"([\w\.\[\]]+)"|\'([\w\.\[\]]+)\')'
            matches = re.finditer(pattern, content, re.IGNORECASE)
            
            for match in matches:
                connection_var = match.group(1)
                proc_name = match.group(2) or match.group(3)
                
                # 檢查是否為 SP（後續有 CommandType.StoredProcedure）
                context_start = match.end()
                context_end = min(context_start + 200, len(content))
                context = content[context_start:context_end]
                
                # 判斷是否為 SP
                is_sp = False
                
                # 1. 明確指定 CommandType
                if 'CommandType.StoredProcedure' in context:
                    is_sp = True
                # 2. SP 命名慣例
                elif proc_name.startswith('sp') or proc_name.startswith('SP') or proc_name.startswith('usp'):
                    is_sp = True
                # 3. 如果只是 SELECT/INSERT/UPDATE/DELETE，不是 SP
                elif any(kw in proc_name.upper() for kw in ['SELECT', 'INSERT', 'UPDATE', 'DELETE']):
                    is_sp = False
                
                if not is_sp:
                    continue
                
                line_num = content[:match.start()].count('\n') + 1
                
                # 提取參數
                params = self._extract_dapper_parameters(context)
                
                # 識別資料庫來源
                db_source = self.db_tracker.get_database_source(connection_var)
                
                calls.append(StoredProcedureCall(
                    procedure_name=proc_name,
                    parameters=params,
                    location=CodeLocation(self.current_file, line_num),
                    database_source=db_source,
                    connection_variable=connection_var
                ))
        
        return calls
    
    def _extract_dapper_parameters(self, context: str) -> List[str]:
        """提取 Dapper 參數"""
        params = []
        
        # 模式 1: new { paramName = value, ... }
        anon_match = re.search(r'new\s*\{([^}]+)\}', context)
        if anon_match:
            param_text = anon_match.group(1)
            # 提取參數名稱
            param_names = re.findall(r'(\w+)\s*=', param_text)
            params.extend([f"@{name}" for name in param_names])
        
        # 模式 2: new DynamicParameters()
        # 模式 3: parameters 物件
        
        return params
    
    def _extract_ef_sp_calls(self, content: str) -> List[StoredProcedureCall]:
        """
        提取 Entity Framework 的 SP 呼叫
        
        常見模式:
        1. context.Database.ExecuteSqlCommand("spName", ...)
        2. context.Database.SqlQuery<T>("spName", ...)
        3. FromSqlRaw("EXEC spName @param")
        """
        calls = []
        
        # EF 方法清單
        ef_methods = [
            'ExecuteSqlCommand', 'ExecuteSqlCommandAsync',
            'ExecuteSqlRaw', 'ExecuteSqlRawAsync',
            'SqlQuery', 'SqlQueryRaw',
            'FromSqlRaw', 'FromSqlInterpolated'
        ]
        
        for method in ef_methods:
            # 模式 1: 直接呼叫 SP 名稱
            pattern1 = rf'{method}\s*(?:<[^>]+>)?\s*\(\s*(?:@?"([\w\.\[\]]+)"|\'([\w\.\[\]]+)\')'
            matches1 = re.finditer(pattern1, content, re.IGNORECASE)
            
            for match in matches1:
                proc_name = match.group(1) or match.group(2)
                
                # SP 命名慣例判斷
                if proc_name.startswith('sp') or proc_name.startswith('SP') or proc_name.startswith('usp'):
                    line_num = content[:match.start()].count('\n') + 1
                    
                    calls.append(StoredProcedureCall(
                        procedure_name=proc_name,
                        location=CodeLocation(self.current_file, line_num),
                        database_source=None  # EF 通常從 context 判斷
                    ))
            
            # 模式 2: EXEC spName
            pattern2 = rf'{method}\s*(?:<[^>]+>)?\s*\(\s*(?:@?"EXEC\s+([\w\.\[\]]+)"|\'EXEC\s+([\w\.\[\]]+)\')'
            matches2 = re.finditer(pattern2, content, re.IGNORECASE)
            
            for match in matches2:
                proc_name = match.group(1) or match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                calls.append(StoredProcedureCall(
                    procedure_name=proc_name,
                    location=CodeLocation(self.current_file, line_num),
                    database_source=None
                ))
        
        return calls

    def _extract_sqlcommand_stored_procedures(self, content: str) -> List[StoredProcedureCall]:
        """
        提取 SqlCommand 模式的預存程序呼叫（加入連線追蹤）
        """
        calls = []
        
        #  捕獲 SqlConnection 變數
        pattern = r'SqlConnection\s+(\w+)\s*=\s*new\s+SqlConnection\s*\(([^)]+)\)'
        connection_matches = list(re.finditer(pattern, content, re.IGNORECASE))
        
        # 找出 SqlCommand
        cmd_pattern = r'SqlCommand\s+(\w+)\s*=\s*new\s+SqlCommand\s*\(\s*(?:@?"([\w\.\[\]]+)"|\'([\w\.\[\]]+)\')\s*,\s*(\w+)\s*\)'
        cmd_matches = list(re.finditer(cmd_pattern, content, re.IGNORECASE))
        
        for match in cmd_matches:
            cmd_var = match.group(1)
            proc_name = match.group(2) or match.group(3)
            connection_var = match.group(4)  #  連線變數
            
            # 驗證名稱
            if not self.sp_config.is_valid_sp_name(proc_name):
                continue
            
            # 檢查是否為預存程序
            context_start = match.start()
            context_end = min(match.end() + 1000, len(content))
            context = content[context_start:context_end]
            
            is_stored_proc = False
            
            # 檢查 1: 明確指定 CommandType
            if 'CommandType.StoredProcedure' in context or 'CommandType = CommandType.StoredProcedure' in context:
                is_stored_proc = True
            
            # 檢查 2: 根據命名模式判斷
            elif any(pattern.match(proc_name) for pattern in self.sp_config.compiled_patterns):
                is_stored_proc = True
            
            if is_stored_proc:
                line_num = content[:match.start()].count('\n') + 1
                params = self._extract_sqlcommand_parameters_detailed(context)
                # 追蹤資料庫來源
                db_source = self.db_tracker.get_database_source(connection_var)

                calls.append(StoredProcedureCall(
                    procedure_name=proc_name,
                    parameters=params,
                    location=CodeLocation(self.current_file, line_num),
                    database_source=db_source,          # 追蹤資料庫來源
                    connection_variable=connection_var  # 追蹤資料庫來源
                ))
        
        return calls
    
    def _identify_database_source(
        self, 
        content: str, 
        line_number: int, 
        variable_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        識別資料庫來源
        
        Args:
            content: 檔案內容
            line_number: SQL 所在行號
            variable_name: 變數名稱 (例如: "objPUR", "cn")
            
        Returns:
            (資料庫名稱, 連線變數名稱)
        """
        # 從追蹤器取得
        db_source = self.db_tracker.get_database_source(variable_name)
        
        if db_source:
            return (db_source, variable_name)
        
        # 如果找不到，可能是直接使用的變數，嘗試向上追溯
        # 例如: var result = obj.CreateReader(...) 中的 obj
        
        return (None, variable_name)

    def _extract_sqlcommand_parameters_detailed(self, context: str) -> List[str]:
        """詳細提取 SqlCommand 參數"""
        params = []
        
        # 模式 1: Parameters.Add
        pattern1 = r'Parameters\.Add\s*\(\s*["\']@?(\w+)["\'](?:\s*,\s*SqlDbType\.(\w+))?(?:\s*,\s*(\d+))?\s*\)'
        matches1 = re.finditer(pattern1, context, re.IGNORECASE)
        
        for match in matches1:
            param_name = match.group(1)
            param_type = match.group(2)
            param_length = match.group(3)
            
            param_info = f"@{param_name}"
            if param_type:
                param_info += f" ({param_type}"
                if param_length:
                    param_info += f", {param_length}"
                param_info += ")"
            
            params.append(param_info)
        
        # 模式 2: Parameters.AddWithValue
        pattern2 = r'Parameters\.AddWithValue\s*\(\s*["\']@?(\w+)["\']'
        matches2 = re.finditer(pattern2, context, re.IGNORECASE)
        
        for match in matches2:
            param_name = match.group(1)
            params.append(f"@{param_name}")
        
        return params
    
    def _extract_direct_exec_calls(self, content: str) -> List[StoredProcedureCall]:
        """提取直接 EXEC 呼叫"""
        calls = []
        
        pattern = r'(?:EXEC|EXECUTE)\s+([\w\.\[\]]+)'
        matches = re.finditer(pattern, content, re.IGNORECASE)
        
        for match in matches:
            proc_name = match.group(1)
            
            # 驗證名稱
            if not self.sp_config.is_valid_sp_name(proc_name):
                continue
            
            line_num = content[:match.start()].count('\n') + 1
            params = self._extract_exec_parameters(content, match.end())
            
            calls.append(StoredProcedureCall(
                procedure_name=proc_name,
                parameters=params,
                location=CodeLocation(self.current_file, line_num)
            ))
        
        return calls
    
    def _extract_exec_parameters(self, content: str, start_pos: int) -> List[str]:
        """提取 EXEC 語句的參數"""
        params = []
        
        end_pos = content.find(';', start_pos)
        if end_pos == -1:
            end_pos = content.find('\n', start_pos)
        if end_pos == -1:
            end_pos = start_pos + 200
        
        param_text = content[start_pos:end_pos]
        param_matches = re.findall(r'@(\w+)', param_text)
        params.extend(param_matches)
        
        return params
    
    def _extract_method_call_detail(self, content: str, call_start: int, proc_name_end: int) -> Dict:
        """提取方法呼叫的詳細資訊"""
        paren_count = 0
        call_end = proc_name_end
        started = False
        
        for i in range(proc_name_end, min(proc_name_end + 500, len(content))):
            if content[i] == '(':
                paren_count += 1
                started = True
            elif content[i] == ')':
                paren_count -= 1
                if paren_count == 0 and started:
                    call_end = i
                    break
        
        param_section = content[proc_name_end:call_end]
        
        params = []
        if ',' in param_section:
            parts = param_section.split(',')
            if len(parts) > 1:
                for param in parts[1:]:
                    param = param.strip().strip('"\'').strip(')')
                    if param:
                        params.append(param)
        
        return {
            'parameters': params,
            'call_text': content[call_start:call_end+1]
        }
    
    def _deduplicate_sp_calls(self, calls: List[StoredProcedureCall]) -> List[StoredProcedureCall]:
        """去除重複的預存程序呼叫"""
        unique_calls = []
        seen = set()
        
        for call in calls:
            key = (call.procedure_name, str(call.location))
            if key not in seen:
                seen.add(key)
                unique_calls.append(call)
        
        return unique_calls    

    def _extract_api_endpoints(self, content: str, lines: List[str]) -> List[APIEndpoint]:
        """提取 API 端點"""
        endpoints = []
        
        # 檢查是否為 API Controller
        is_api_controller = re.search(self.API_CONTROLLER_PATTERN, content) is not None
        
        # 找出類別層級的 Route
        class_route = ""
        class_route_match = re.search(r'class\s+\w+.*?\n.*?\[Route\(["\']([^"\']+)["\']\)\]', content, re.DOTALL)
        if not class_route_match:
            class_route_match = re.search(r'\[Route\(["\']([^"\']+)["\']\)\].*?class\s+\w+', content, re.DOTALL)
        
        if class_route_match:
            class_route = class_route_match.group(1)
        
        # 找出所有 HTTP Method 屬性
        http_matches = list(re.finditer(self.HTTP_METHOD_PATTERN, content, re.MULTILINE))
        
        for match in http_matches:
            http_method_str = match.group(1).replace('Http', '').upper()
            try:
                http_method = HTTPMethod[http_method_str]
            except KeyError:
                continue
            
            route_param = match.group(2) or ''
            
            # 找出對應的方法
            method_start = match.end()
            method_match = re.search(
                self.METHOD_PATTERN,
                content[method_start:method_start + 500],
                re.MULTILINE,
            )
            
            if not method_match:
                continue
            if method_match.group(7) in self._METHOD_RETURN_TYPE_DENYLIST:
                continue
            
            action_name = method_match.group(8)
            return_type = method_match.group(7)
            
            # 找出 Controller 名稱
            controller_name = self._find_controller_name(content, match.start())
            
            # 建立完整路由
            route = class_route
            if route_param:
                route = f"{route}/{route_param.strip()}" if route else route_param.strip()
            elif not route:
                route = f"api/{controller_name}/{action_name}" if is_api_controller else f"{controller_name}/{action_name}"
            
            # 清理路由
            route = route.strip('/').replace('//', '/')
            
            # 提取參數
            params = self._extract_method_parameters(content[method_start:], method_match.end())
            
            # 檢查是否需要授權
            auth_match = re.search(self.AUTHORIZE_PATTERN, content[max(0, match.start() - 200):match.start()])
            requires_auth = auth_match is not None
            roles = []
            if auth_match and auth_match.group(1):
                roles = [r.strip() for r in auth_match.group(1).split(',')]
            
            line_num = content[:match.start()].count('\n') + 1
            
            endpoints.append(APIEndpoint(
                route=f"/{route}",
                http_method=http_method,
                controller=controller_name or 'Unknown',
                action=action_name,
                parameters=params,
                return_type=return_type,
                requires_auth=requires_auth,
                roles=roles,
                location=CodeLocation(self.current_file, line_num)
            ))
        
        return endpoints
    
    def _find_controller_name(self, content: str, position: int) -> Optional[str]:
        """找出 Controller 名稱"""
        content_before = content[:position]
        class_matches = re.findall(self.CLASS_PATTERN, content_before)
        
        for match in reversed(class_matches):
            class_name = match[2]
            if 'Controller' in class_name:
                return class_name.replace('Controller', '')
        
        return None
    
    def _count_lines(self, lines: List[str]) -> Tuple[int, int, int]:
        """
        計算程式碼行數、註解行數、空白行數
        
        Returns:
            (code_lines, comment_lines, blank_lines)
        """
        code_lines = 0
        comment_lines = 0
        blank_lines = 0
        in_block_comment = False
        
        for line in lines:
            stripped = line.strip()
            
            # 空白行
            if not stripped:
                blank_lines += 1
                continue
            
            # 區塊註解開始
            if '/*' in stripped:
                in_block_comment = True
                comment_lines += 1
                continue
            
            # 區塊註解結束
            if '*/' in stripped:
                in_block_comment = False
                comment_lines += 1
                continue
            
            # 在區塊註解中
            if in_block_comment:
                comment_lines += 1
                continue
            
            # 單行註解
            if stripped.startswith('//'):
                comment_lines += 1
                continue
            
            # 程式碼行
            code_lines += 1
        
        return code_lines, comment_lines, blank_lines


# ============================================
# 測試程式碼
# ============================================

if __name__ == "__main__":
    print("=" * 80)
    print("C# 解析器測試")
    print("=" * 80)
    
    # 建立測試檔案
    sample_code = """
using System;
using System.Web.Mvc;
using System.Data.SqlClient;

namespace MyApp.Controllers
{
    /// <summary>
    /// 使用者控制器
    /// </summary>
    [Route("api/users")]
    [Authorize]
    public class UserController : Controller
    {
        // 資料庫連線
        private readonly SqlConnection _connection;
        
        public string ConnectionString { get; set; }
        
        /// <summary>
        /// 取得使用者
        /// </summary>
        [HttpGet("{id}")]
        public async Task<ActionResult> GetUser(int id)
        {
            string sql = @"SELECT UserId, UserName, Email 
                          FROM Users 
                          WHERE UserId = @id AND IsActive = 1";
            
            var user = await _connection.QueryAsync(sql, new { id });
            return Json(user);
        }
        
        [HttpPost]
        [Authorize(Roles = "Admin")]
        public ActionResult CreateUser(string name, string email)
        {
            string sql = "INSERT INTO Users (UserName, Email) VALUES (@name, @email)";
            _connection.Execute(sql, new { name, email });
            return Ok();
        }
        
        [HttpPut("{id}")]
        public void UpdateUser(int id, string name)
        {
            string sql = "UPDATE Users SET UserName = @name WHERE UserId = @id";
            _connection.Execute(sql, new { id, name });
        }
        
        [HttpDelete("{id}")]
        public void DeleteUser(int id)
        {
            // 執行預存程序
            _connection.Execute("EXEC sp_DeleteUser @userId", new { userId = id });
        }
    }
}
"""
    
    # 寫入測試檔案
    test_file = "D:\\PUR\\TTPUR\\Evaluate\\CusEvaMan.aspx.cs"
    """with open(test_file, 'w', encoding='utf-8') as f:
        f.write(sample_code)
    """

    # 解析
    parser = CSharpParser()
    result = parser.parse_file(test_file)
    
    # 顯示結果
    print(f"\n檔案: {result.file_path}")
    print(f"框架: {result.framework.value}")
    print(f"總行數: {result.line_count}")
    print(f"程式碼行數: {result.code_line_count}")
    print(f"註解行數: {result.comment_line_count}")
    print(f"空白行數: {result.blank_line_count}")
    
    print(f"\n命名空間 ({len(result.namespaces)}):")
    for ns in result.namespaces:
        print(f"  - {ns}")
    
    print(f"\nUsing 引用 ({len(result.using_statements)}):")
    for using in result.using_statements[:5]:  # 只顯示前 5 個
        print(f"  - {using}")
    
    print(f"\n類別 ({len(result.classes)}):")
    for cls in result.classes:
        print(f"\n  類別: {cls.full_name}")
        print(f"    修飾詞: {cls.access_modifier}")
        print(f"    基底類別: {cls.base_class}")
        print(f"    是 Controller: {cls.is_controller}")
        print(f"    方法數: {len(cls.methods)}")
        print(f"    屬性數: {len(cls.properties)}")
        
        print(f"\n    屬性:")
        for prop in cls.properties:
            print(f"      - {prop}")
        
        print(f"\n    方法:")
        for method in cls.methods:
            print(f"      - {method}")
            print(f"        位置: {method.location}")
            print(f"        參數: {len(method.parameters)}")
            if method.sql_queries:
                print(f"        SQL 查詢: {len(method.sql_queries)}")
    
    print(f"\nSQL 查詢 ({len(result.sql_queries)}):")
    for i, sql in enumerate(result.sql_queries, 1):
        print(f"\n  {i}. {sql.query_type.value}")
        print(f"     位置: {sql.location}")
        print(f"     資料表: {', '.join(sql.tables)}")
        print(f"     資料庫來源: {sql.database_source}")
        print(f"     參數化: {sql.is_parameterized}")
        print(f"     內容: {sql.query_text[:60]}...")
    
    print(f"\n預存程序呼叫 ({len(result.stored_procedure_calls)}):")
    for sp in result.stored_procedure_calls:
        print(f"  - {sp.procedure_name}, 資料庫來源: {sp.database_source} at {sp.location}")
    
    print(f"\nAPI 端點 ({len(result.api_endpoints)}):")
    for api in result.api_endpoints:
        print(f"\n  {api.http_method.value} {api.route}")
        print(f"    Controller: {api.controller}")
        print(f"    Action: {api.action}")
        print(f"    需要授權: {api.requires_auth}")
        if api.roles:
            print(f"    角色: {', '.join(api.roles)}")
        print(f"    參數: {len(api.parameters)}")
        print(f"    位置: {api.location}")
    
    # 清理測試檔案
    """import os
    os.remove(test_file)"""
    
    print("\n" + "=" * 80)
    print("✅ C# 解析器測試完成")
    print("=" * 80)