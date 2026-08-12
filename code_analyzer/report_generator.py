# code_analyzer/report_generator.py
"""
報告生成器
生成 HTML 互動式報告和統計圖表
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from collections import Counter

from .project_scanner import ProjectScanResult, CSharpSPRelation, CSharpTableRelation


class HTMLReportGenerator:
    """HTML 報告生成器"""
    
    def __init__(self, scan_result: ProjectScanResult):
        self.scan_result = scan_result
        self.report_time = datetime.now()
    
    def generate_report(self, output_path: str = None) -> str:
        """
        生成完整的 HTML 報告
        
        Args:
            output_path: 輸出路徑
        
        Returns:
            輸出檔案路徑
        """
        if output_path is None:
            timestamp = self.report_time.strftime('%Y%m%d_%H%M%S')
            output_path = f"output/reports/{self.scan_result.project_name}_report_{timestamp}.html"
        
        # 轉換為絕對路徑
        output_path = str(Path(output_path).resolve())
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 生成 HTML
        html_content = self._build_html()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ HTML 報告已生成: {output_path}")
        return output_path
    
    def _build_html(self) -> str:
        """建構 HTML 內容"""
        result = self.scan_result
        result.calculate_statistics()
        
        # 準備資料
        summary_stats = self._get_summary_stats()
        db_stats = self._get_database_stats()
        complexity_stats = self._get_complexity_stats()
        sp_list = self._get_sp_list()
        table_list = self._get_table_list()
        file_list = self._get_file_list()
        
        html = f"""
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>專案分析報告 - {result.project_name}</title>
    <style>
        {self._get_css()}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container">
        <!-- 標題區 -->
        <header class="header">
            <h1>📊 專案分析報告</h1>
            <div class="project-info">
                <h2>{result.project_name}</h2>
                <p class="path">{result.project_root}</p>
                <p class="time">分析時間: {self.report_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
        </header>
        
        <!-- 摘要卡片 -->
        <section class="summary-cards">
            <div class="card">
                <div class="card-icon">📁</div>
                <div class="card-content">
                    <div class="card-value">{summary_stats['total_files']}</div>
                    <div class="card-label">C# 檔案</div>
                    <div class="card-sub">{summary_stats['success_rate']}% 成功率</div>
                </div>
            </div>
            <div class="card">
                <div class="card-icon">🗄️</div>
                <div class="card-content">
                    <div class="card-value">{summary_stats['databases']}</div>
                    <div class="card-label">資料庫</div>
                </div>
            </div>
            <div class="card">
                <div class="card-icon">📞</div>
                <div class="card-content">
                    <div class="card-value">{summary_stats['unique_sps']}</div>
                    <div class="card-label">預存程序</div>
                    <div class="card-sub">{summary_stats['total_sp_calls']} 次呼叫</div>
                </div>
            </div>
            <div class="card">
                <div class="card-icon">📊</div>
                <div class="card-content">
                    <div class="card-value">{summary_stats['unique_tables']}</div>
                    <div class="card-label">資料表</div>
                    <div class="card-sub">{summary_stats['total_sql_queries']} 個 SQL</div>
                </div>
            </div>
        </section>
        
        <!-- 圖表區 -->
        <section class="charts-section">
            <div class="chart-container">
                <h3>📈 資料庫使用分布</h3>
                <canvas id="dbChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>⚙️ SP 複雜度分布</h3>
                <canvas id="complexityChart"></canvas>
            </div>
        </section>
        
        <!-- 標籤頁 -->
        <section class="tabs-section">
            <div class="tabs">
                <button class="tab-btn active" onclick="openTab(event, 'spTab')">預存程序</button>
                <button class="tab-btn" onclick="openTab(event, 'tableTab')">資料表</button>
                <button class="tab-btn" onclick="openTab(event, 'fileTab')">檔案清單</button>
                <button class="tab-btn" onclick="openTab(event, 'warningTab')">警告</button>
            </div>
            
            <!-- SP 標籤頁 -->
            <div id="spTab" class="tab-content active">
                <div class="search-box">
                    <input type="text" id="spSearch" placeholder="🔍 搜尋預存程序..." onkeyup="filterTable('spTable', 'spSearch')">
                </div>
                <table id="spTable" class="data-table">
                    <thead>
                        <tr>
                            <th>狀態</th>
                            <th>資料庫</th>
                            <th>SP 名稱</th>
                            <th>呼叫次數</th>
                            <th>複雜度</th>
                            <th>涉及資料表</th>
                            <th>呼叫來源</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._generate_sp_rows(sp_list)}
                    </tbody>
                </table>
            </div>
            
            <!-- 資料表標籤頁 -->
            <div id="tableTab" class="tab-content">
                <div class="search-box">
                    <input type="text" id="tableSearch" placeholder="🔍 搜尋資料表..." onkeyup="filterTable('tableTable', 'tableSearch')">
                </div>
                <table id="tableTable" class="data-table">
                    <thead>
                        <tr>
                            <th>資料庫</th>
                            <th>資料表名稱</th>
                            <th>存取次數</th>
                            <th>操作類型</th>
                            <th>使用的檔案</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._generate_table_rows(table_list)}
                    </tbody>
                </table>
            </div>
            
            <!-- 檔案標籤頁 -->
            <div id="fileTab" class="tab-content">
                <div class="search-box">
                    <input type="text" id="fileSearch" placeholder="🔍 搜尋檔案..." onkeyup="filterTable('fileTable', 'fileSearch')">
                </div>
                <table id="fileTable" class="data-table">
                    <thead>
                        <tr>
                            <th>檔案名稱</th>
                            <th>類別數</th>
                            <th>方法數</th>
                            <th>SP 呼叫</th>
                            <th>SQL 查詢</th>
                            <th>行數</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._generate_file_rows(file_list)}
                    </tbody>
                </table>
            </div>
            
            <!-- 警告標籤頁 -->
            <div id="warningTab" class="tab-content">
                {self._generate_warnings()}
            </div>
        </section>
        
        <!-- 頁尾 -->
        <footer class="footer">
            <p>Generated by Impact Analysis System</p>
            <p>© {datetime.now().year}</p>
        </footer>
    </div>
    
    <script>
        {self._get_javascript(db_stats, complexity_stats)}
    </script>
</body>
</html>
"""
        return html
    
    def _get_css(self) -> str:
        """取得 CSS 樣式"""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Microsoft YaHei', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: #fff;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%);
            color: white;
            padding: 30px 40px;
        }
        
        .header h1 {
            font-size: 28px;
            margin-bottom: 15px;
        }
        
        .project-info h2 {
            font-size: 22px;
            font-weight: normal;
        }
        
        .project-info .path {
            opacity: 0.8;
            font-size: 14px;
            margin-top: 5px;
        }
        
        .project-info .time {
            opacity: 0.7;
            font-size: 12px;
            margin-top: 5px;
        }
        
        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px 40px;
            background: #f8f9fa;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: transform 0.3s, box-shadow 0.3s;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }
        
        .card-icon {
            font-size: 36px;
        }
        
        .card-value {
            font-size: 32px;
            font-weight: bold;
            color: #2c3e50;
        }
        
        .card-label {
            color: #7f8c8d;
            font-size: 14px;
        }
        
        .card-sub {
            color: #95a5a6;
            font-size: 12px;
        }
        
        .charts-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
            padding: 30px 40px;
        }
        
        .chart-container {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
        }
        
        .chart-container h3 {
            margin-bottom: 20px;
            color: #2c3e50;
        }
        
        .tabs-section {
            padding: 0 40px 40px;
        }
        
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
        }
        
        .tab-btn {
            padding: 10px 20px;
            border: none;
            background: #f0f0f0;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
        }
        
        .tab-btn:hover {
            background: #e0e0e0;
        }
        
        .tab-btn.active {
            background: #3498db;
            color: white;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .search-box {
            margin-bottom: 15px;
        }
        
        .search-box input {
            width: 100%;
            max-width: 400px;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #3498db;
        }
        
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        
        .data-table th {
            background: #2c3e50;
            color: white;
            padding: 12px 15px;
            text-align: left;
            position: sticky;
            top: 0;
        }
        
        .data-table td {
            padding: 10px 15px;
            border-bottom: 1px solid #e0e0e0;
        }
        
        .data-table tbody tr:hover {
            background: #f5f6fa;
        }
        
        .status-ok { color: #27ae60; }
        .status-error { color: #e74c3c; }
        .status-warning { color: #f39c12; }
        
        .complexity-simple { 
            background: #d5f4e6; 
            color: #27ae60; 
            padding: 3px 8px; 
            border-radius: 4px;
        }
        .complexity-medium { 
            background: #fef3cd; 
            color: #856404; 
            padding: 3px 8px; 
            border-radius: 4px;
        }
        .complexity-complex { 
            background: #f8d7da; 
            color: #721c24; 
            padding: 3px 8px; 
            border-radius: 4px;
        }
        
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin: 2px;
        }
        
        .badge-read { background: #e3f2fd; color: #1976d2; }
        .badge-insert { background: #e8f5e9; color: #388e3c; }
        .badge-update { background: #fff3e0; color: #f57c00; }
        .badge-delete { background: #ffebee; color: #d32f2f; }
        
        .warning-box {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px 20px;
            margin: 10px 0;
            border-radius: 0 8px 8px 0;
        }
        
        .warning-box h4 {
            color: #856404;
            margin-bottom: 10px;
        }
        
        .warning-item {
            margin: 5px 0;
            color: #856404;
        }
        
        .footer {
            background: #2c3e50;
            color: white;
            text-align: center;
            padding: 20px;
            font-size: 12px;
        }
        
        .footer p {
            margin: 5px 0;
            opacity: 0.8;
        }
        
        .tag-list {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        
        .file-link {
            color: #3498db;
            text-decoration: none;
        }
        
        .file-link:hover {
            text-decoration: underline;
        }
        """
    
    def _get_javascript(self, db_stats: Dict, complexity_stats: Dict) -> str:
        """取得 JavaScript"""
        db_labels = json.dumps(list(db_stats.keys()))
        db_values = json.dumps(list(db_stats.values()))
        
        complexity_labels = json.dumps(list(complexity_stats.keys()))
        complexity_values = json.dumps(list(complexity_stats.values()))
        
        return f"""
        // 標籤頁切換
        function openTab(evt, tabName) {{
            var tabContents = document.getElementsByClassName('tab-content');
            for (var i = 0; i < tabContents.length; i++) {{
                tabContents[i].classList.remove('active');
            }}
            
            var tabBtns = document.getElementsByClassName('tab-btn');
            for (var i = 0; i < tabBtns.length; i++) {{
                tabBtns[i].classList.remove('active');
            }}
            
            document.getElementById(tabName).classList.add('active');
            evt.currentTarget.classList.add('active');
        }}
        
        // 表格搜尋
        function filterTable(tableId, searchId) {{
            var input = document.getElementById(searchId);
            var filter = input.value.toUpperCase();
            var table = document.getElementById(tableId);
            var tr = table.getElementsByTagName('tr');
            
            for (var i = 1; i < tr.length; i++) {{
                var td = tr[i].getElementsByTagName('td');
                var found = false;
                
                for (var j = 0; j < td.length; j++) {{
                    if (td[j]) {{
                        var txtValue = td[j].textContent || td[j].innerText;
                        if (txtValue.toUpperCase().indexOf(filter) > -1) {{
                            found = true;
                            break;
                        }}
                    }}
                }}
                
                tr[i].style.display = found ? '' : 'none';
            }}
        }}
        
        // 資料庫使用圖表
        var dbCtx = document.getElementById('dbChart').getContext('2d');
        new Chart(dbCtx, {{
            type: 'doughnut',
            data: {{
                labels: {db_labels},
                datasets: [{{
                    data: {db_values},
                    backgroundColor: [
                        '#3498db', '#e74c3c', '#2ecc71', '#f39c12', 
                        '#9b59b6', '#1abc9c', '#34495e', '#e67e22'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }}
                }}
            }}
        }});
        
        // 複雜度分布圖表
        var complexityCtx = document.getElementById('complexityChart').getContext('2d');
        new Chart(complexityCtx, {{
            type: 'bar',
            data: {{
                labels: {complexity_labels},
                datasets: [{{
                    label: 'SP 數量',
                    data: {complexity_values},
                    backgroundColor: ['#2ecc71', '#f39c12', '#e74c3c']
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true
                    }}
                }}
            }}
        }});
        """
    
    def _get_summary_stats(self) -> Dict:
        """取得摘要統計"""
        result = self.scan_result
        
        success_rate = 0
        if result.total_files > 0:
            success_rate = int(result.scanned_files / result.total_files * 100)
        
        return {
            'total_files': result.total_files,
            'scanned_files': result.scanned_files,
            'failed_files': result.failed_files,
            'success_rate': success_rate,
            'databases': len(result.databases_used),
            'unique_sps': len(result.unique_sps),
            'total_sp_calls': result.total_sp_calls,
            'unique_tables': len(result.unique_tables),
            'total_sql_queries': result.total_sql_queries
        }
    
    def _get_database_stats(self) -> Dict:
        """取得資料庫統計"""
        db_counts = Counter(
            invocation["database"]
            for invocation in self.scan_result.iter_formal_sp_invocations()
        )
        return dict(db_counts)
    
    def _get_complexity_stats(self) -> Dict:
        """Return no complexity rating until SQL graph evidence is joined."""
        return {}
    
    def _get_sp_list(self) -> List[Dict]:
        """取得 raw Database Invocation 清單，避免猜測 SQL evidence。"""
        sp_groups = {}
        
        for invocation in self.scan_result.iter_formal_sp_invocations():
            sp_name = invocation["procedure_name"] or "<dynamic command text>"
            key = (invocation["database"], sp_name)
            
            if key not in sp_groups:
                sp_groups[key] = {
                    'database': invocation["database"],
                    'name': sp_name,
                    'exists': None,
                    'complexity': 'unrated',
                    'tables': [],
                    'call_count': 0,
                    'callers': []
                }
            
            sp_groups[key]['call_count'] += 1
            sp_groups[key]['callers'].append({
                'file': Path(invocation["source_file"]).name,
                'method': invocation["method_name"],
                'line': invocation["line_number"]
            })
        
        return list(sp_groups.values())
    
    def _get_table_list(self) -> List[Dict]:
        """取得資料表清單"""
        table_groups = {}
        
        for rel in self.scan_result.table_relations:
            key = (rel.database, rel.table_name)
            
            if key not in table_groups:
                table_groups[key] = {
                    'database': rel.database,
                    'name': rel.table_name,
                    'access_count': 0,
                    'access_types': set(),
                    'files': set()
                }
            
            table_groups[key]['access_count'] += 1
            table_groups[key]['access_types'].add(rel.access_type)
            table_groups[key]['files'].add(Path(rel.csharp_file).name)
        
        # 轉換 set 為 list
        for table in table_groups.values():
            table['access_types'] = list(table['access_types'])
            table['files'] = list(table['files'])
        
        return list(table_groups.values())
    
    def _get_file_list(self) -> List[Dict]:
        """取得檔案清單"""
        files = []
        
        for result in self.scan_result.csharp_results:
            files.append({
                'name': Path(result.file_path).name,
                'path': result.file_path,
                'classes': len(result.classes),
                'methods': sum(len(cls.methods) for cls in result.classes),
                'sp_calls': len(result.stored_procedure_calls),
                'sql_queries': len(result.sql_queries),
                'lines': result.line_count
            })
        
        # 按 SP 呼叫數排序
        files.sort(key=lambda x: x['sp_calls'], reverse=True)
        
        return files
    
    def _generate_sp_rows(self, sp_list: List[Dict]) -> str:
        """生成 SP 表格行"""
        rows = []
        
        for sp in sp_list:
            if sp['exists'] is True:
                status, status_class = '✅', 'status-ok'
            elif sp['exists'] is False:
                status, status_class = '❌', 'status-error'
            else:
                status, status_class = '?', 'status-unknown'
            
            # 複雜度
            complexity_map = {
                '簡單': 'complexity-simple',
                '中等': 'complexity-medium',
                '複雜': 'complexity-complex'
            }
            complexity_class = complexity_map.get(sp['complexity'], '')
            
            # 資料表
            tables = ', '.join(sp['tables'][:3])
            if len(sp['tables']) > 3:
                tables += f' ... (+{len(sp["tables"]) - 3})'
            
            # 呼叫來源
            callers = []
            for caller in sp['callers'][:3]:
                callers.append(f"{caller['file']}:{caller['line']}")
            caller_str = '<br>'.join(callers)
            if len(sp['callers']) > 3:
                caller_str += f'<br>... (+{len(sp["callers"]) - 3})'
            
            rows.append(f"""
            <tr>
                <td class="{status_class}">{status}</td>
                <td>{sp['database']}</td>
                <td><strong>{sp['name']}</strong></td>
                <td>{sp['call_count']}</td>
                <td><span class="{complexity_class}">{sp['complexity']}</span></td>
                <td>{tables if tables else '-'}</td>
                <td style="font-size: 12px;">{caller_str}</td>
            </tr>
            """)
        
        return '\n'.join(rows)
    
    def _generate_table_rows(self, table_list: List[Dict]) -> str:
        """生成資料表表格行"""
        rows = []
        
        for table in table_list:
            # 操作類型 badges
            badges = []
            for access_type in table['access_types']:
                badge_class = {
                    'SELECT': 'badge-read',
                    'INSERT': 'badge-insert',
                    'UPDATE': 'badge-update',
                    'DELETE': 'badge-delete'
                }.get(access_type, '')
                badges.append(f'<span class="badge {badge_class}">{access_type}</span>')
            
            # 檔案
            files = ', '.join(table['files'][:3])
            if len(table['files']) > 3:
                files += f' ... (+{len(table["files"]) - 3})'
            
            rows.append(f"""
            <tr>
                <td>{table['database']}</td>
                <td><strong>{table['name']}</strong></td>
                <td>{table['access_count']}</td>
                <td>{''.join(badges)}</td>
                <td style="font-size: 12px;">{files}</td>
            </tr>
            """)
        
        return '\n'.join(rows)
    
    def _generate_file_rows(self, file_list: List[Dict]) -> str:
        """生成檔案表格行"""
        rows = []
        
        for file in file_list:
            rows.append(f"""
            <tr>
                <td><strong>{file['name']}</strong></td>
                <td>{file['classes']}</td>
                <td>{file['methods']}</td>
                <td>{file['sp_calls']}</td>
                <td>{file['sql_queries']}</td>
                <td>{file['lines']}</td>
            </tr>
            """)
        
        return '\n'.join(rows)
    
    def _generate_warnings(self) -> str:
        """生成警告區域"""
        warnings = []
        
        # 未知資料庫
        unknown_db = [
            invocation
            for invocation in self.scan_result.iter_formal_sp_invocations()
            if invocation["database"] == "unknown"
        ]
        
        if unknown_db:
            warnings.append({
                'title': f'❓ 無法識別資料庫來源的呼叫 ({len(unknown_db)})',
                'items': [
                    f"{invocation['procedure_name'] or '<dynamic>'} in "
                    f"{Path(invocation['source_file']).name}"
                    for invocation in unknown_db[:10]
                ]
            })
        
        if not warnings:
            return '<p style="color: #27ae60;">✅ 沒有發現警告</p>'
        
        html = ''
        for warning in warnings:
            items_html = ''.join(f'<div class="warning-item">• {item}</div>' 
                                for item in warning['items'][:10])
            if len(warning['items']) > 10:
                items_html += f'<div class="warning-item">... 還有 {len(warning["items"]) - 10} 個</div>'
            
            html += f"""
            <div class="warning-box">
                <h4>{warning['title']}</h4>
                {items_html}
            </div>
            """
        
        return html


# ============================================
# 測試
# ============================================

def main():
    """測試報告生成"""
    from .project_scanner import ProjectScanner
    from config.settings import settings
    
    print("=" * 80)
    print("HTML 報告生成測試")
    print("=" * 80)
    
    project_root = input("請輸入專案根目錄: ").strip()
    
    if not project_root:
        print("❌ 未指定專案路徑")
        return
    
    # 掃描專案
    scanner = ProjectScanner(project_root)
    
    test_mode = input("是否啟用測試模式（限制10個檔案）？(y/n): ").strip().lower()
    max_files = 10 if test_mode == 'y' else None
    
    result = scanner.scan_project(analyze_sp=True, max_files=max_files)
    
    # 生成報告
    generator = HTMLReportGenerator(result)
    output_path = generator.generate_report()
    
    # 開啟報告
    open_report = input("\n是否開啟報告？(y/n): ").strip().lower()
    if open_report == 'y':
        import webbrowser
        # 使用 file:// 協議確保瀏覽器能正確開啟
        webbrowser.open(f'file:///{output_path}')
    
    print("\n✅ 測試完成")


if __name__ == "__main__":
    main()