# code_analyzer/dependency_graph.py
"""
依賴關係圖生成器（完整版）
- 大型專案：摘要圖 + 統計圖
- 小型分析：詳細依賴圖
- 互動式 HTML 圖表
"""

import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime
from collections import Counter
from dataclasses import dataclass, field
import json


# ============================================
# 依賴關係圖生成器
# ============================================

class DependencyGraphGenerator:
    """依賴關係圖生成器"""
    
    # 節點數閾值
    THRESHOLD_SMALL = 30      # 小於此數量：完整圖表
    THRESHOLD_MEDIUM = 100    # 小於此數量：簡化圖表
    # 大於 MEDIUM：只產生摘要圖
    
    def __init__(self, scan_result):
        """
        初始化圖表生成器
        
        Args:
            scan_result: ProjectScanResult 物件
        """
        self.scan_result = scan_result
        self.graph = nx.DiGraph()
        self._setup_font()
        
        # 計算規模
        self.total_nodes = self._estimate_node_count()
        self.scale = self._determine_scale()
        
        print(f"📊 圖表生成器初始化")
        print(f"   預估節點數: {self.total_nodes}")
        print(f"   規模判定: {self.scale}")
    
    def _setup_font(self):
        """設定字型"""
        try:
            plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
        except:
            pass
    
    def _estimate_node_count(self) -> int:
        """估算節點數量"""
        unique_files = set()
        unique_sps = set()
        unique_tables = set()
        
        for r in self.scan_result.csharp_results:
            unique_files.add(Path(r.file_path).stem)
        
        for rel in self.scan_result.sp_relations:
            unique_sps.add(rel.sp_name)
            if rel.sp_info and rel.sp_info.referenced_tables:
                unique_tables.update(rel.sp_info.referenced_tables)
        
        return len(unique_files) + len(unique_sps) + len(unique_tables)
    
    def _determine_scale(self) -> str:
        """判定規模"""
        if self.total_nodes <= self.THRESHOLD_SMALL:
            return "small"
        elif self.total_nodes <= self.THRESHOLD_MEDIUM:
            return "medium"
        else:
            return "large"
    
    # ========================================
    # 智慧生成（根據規模自動選擇）
    # ========================================
    
    def generate_appropriate_graphs(self, output_dir: str = None) -> Dict[str, List[str]]:
        """
        根據專案規模自動選擇適合的圖表
        
        Args:
            output_dir: 輸出目錄
        
        Returns:
            {'graphs': [...], 'charts': [...], 'html': [...]}
        """
        if output_dir is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_dir = f"output/graphs/{self.scan_result.project_name}_{timestamp}"
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        result = {'graphs': [], 'charts': [], 'html': []}
        
        if self.scale == "small":
            # 小規模：完整圖表
            print("\n📊 小規模專案，生成完整依賴關係圖...")
            result['graphs'].extend(self._generate_full_graphs(output_dir))
        
        elif self.scale == "medium":
            # 中規模：簡化圖表 + 摘要
            print("\n📊 中規模專案，生成簡化圖表...")
            result['graphs'].extend(self._generate_simplified_graphs(output_dir))
        
        else:
            # 大規模：只有摘要圖 + 建議
            print("\n📊 大規模專案，生成摘要圖表...")
            result['graphs'].extend(self._generate_summary_graphs(output_dir))
            print("\n💡 建議：使用 analyze_related_files('模組名稱') 進行單一模組分析")
        
        # 所有規模都生成統計圖表
        print("\n📈 生成統計圖表...")
        stats_gen = StatisticsChartGenerator(self.scan_result)
        result['charts'].extend(stats_gen.generate_all_charts(output_dir))
        
        # 生成互動式 HTML 圖表
        print("\n🌐 生成互動式 HTML 圖表...")
        html_path = self._generate_interactive_html(output_dir)
        if html_path:
            result['html'].append(html_path)
        
        return result
    
    def _generate_full_graphs(self, output_dir: str) -> List[str]:
        """生成完整圖表（小規模專案）"""
        files = []
        
        # C# → SP
        path = self.visualize_csharp_to_sp(f"{output_dir}/csharp_to_sp.png")
        if path:
            files.append(path)
        
        # SP → Table
        path = self.visualize_sp_to_table(f"{output_dir}/sp_to_table.png")
        if path:
            files.append(path)
        
        # 完整圖
        path = self.visualize_full_dependency(f"{output_dir}/full_dependency.png")
        if path:
            files.append(path)
        
        return files
    
    def _generate_simplified_graphs(self, output_dir: str) -> List[str]:
        """生成簡化圖表（中規模專案）"""
        files = []
        
        # 只顯示 Top N 的簡化圖
        path = self.visualize_top_dependencies(f"{output_dir}/top_dependencies.png", top_n=20)
        if path:
            files.append(path)
        
        # 資料庫分組圖
        path = self.visualize_database_summary(f"{output_dir}/database_summary.png")
        if path:
            files.append(path)
        
        return files
    
    def _generate_summary_graphs(self, output_dir: str) -> List[str]:
        """生成摘要圖表（大規模專案）"""
        files = []
        
        # 只有資料庫層級的摘要
        path = self.visualize_database_summary(f"{output_dir}/database_summary.png")
        if path:
            files.append(path)
        
        # 高影響力節點圖
        path = self.visualize_high_impact_nodes(f"{output_dir}/high_impact_nodes.png", top_n=15)
        if path:
            files.append(path)
        
        return files
    
    # ========================================
    # 各種圖表類型
    # ========================================
    
    def visualize_csharp_to_sp(self, output_path: str) -> Optional[str]:
        """C# → SP 關係圖"""
        self.graph.clear()
        
        for rel in self.scan_result.sp_relations:
            csharp_node = Path(rel.csharp_file).stem
            sp_node = rel.sp_name
            
            if not self.graph.has_node(csharp_node):
                self.graph.add_node(csharp_node, node_type='csharp')
            
            if not self.graph.has_node(sp_node):
                self.graph.add_node(sp_node, node_type='sp')
            
            if not self.graph.has_edge(csharp_node, sp_node):
                self.graph.add_edge(csharp_node, sp_node, weight=1)
            else:
                self.graph[csharp_node][sp_node]['weight'] += 1
        
        return self._render_graph("C# 程式 → 預存程序", output_path)
    
    def visualize_sp_to_table(self, output_path: str) -> Optional[str]:
        """SP → Table 關係圖"""
        self.graph.clear()
        
        for rel in self.scan_result.sp_relations:
            if not rel.sp_info or not rel.sp_info.referenced_tables:
                continue
            
            sp_node = rel.sp_name
            
            if not self.graph.has_node(sp_node):
                self.graph.add_node(sp_node, node_type='sp')
            
            for table in rel.sp_info.referenced_tables:
                if not self.graph.has_node(table):
                    self.graph.add_node(table, node_type='table')
                
                if not self.graph.has_edge(sp_node, table):
                    self.graph.add_edge(sp_node, table)
        
        return self._render_graph("預存程序 → 資料表", output_path)
    
    def visualize_full_dependency(self, output_path: str) -> Optional[str]:
        """完整依賴圖"""
        self.graph.clear()
        
        for rel in self.scan_result.sp_relations:
            csharp_node = Path(rel.csharp_file).stem
            sp_node = rel.sp_name
            
            if not self.graph.has_node(csharp_node):
                self.graph.add_node(csharp_node, node_type='csharp')
            
            if not self.graph.has_node(sp_node):
                self.graph.add_node(sp_node, node_type='sp')
            
            if not self.graph.has_edge(csharp_node, sp_node):
                self.graph.add_edge(csharp_node, sp_node)
            
            if rel.sp_info and rel.sp_info.referenced_tables:
                for table in rel.sp_info.referenced_tables:
                    table_node = table
                    
                    if not self.graph.has_node(table_node):
                        self.graph.add_node(table_node, node_type='table')
                    
                    if not self.graph.has_edge(sp_node, table_node):
                        self.graph.add_edge(sp_node, table_node)
        
        return self._render_graph("完整依賴關係 (C# → SP → Table)", output_path)
    
    def visualize_top_dependencies(self, output_path: str, top_n: int = 20) -> Optional[str]:
        """Top N 依賴關係圖"""
        self.graph.clear()
        
        # 找出呼叫次數最多的 SP
        sp_counts = Counter(rel.sp_name for rel in self.scan_result.sp_relations)
        top_sps = set(sp for sp, _ in sp_counts.most_common(top_n))
        
        for rel in self.scan_result.sp_relations:
            if rel.sp_name not in top_sps:
                continue
            
            csharp_node = Path(rel.csharp_file).stem
            sp_node = rel.sp_name
            
            if not self.graph.has_node(csharp_node):
                self.graph.add_node(csharp_node, node_type='csharp')
            
            if not self.graph.has_node(sp_node):
                self.graph.add_node(sp_node, node_type='sp')
            
            if not self.graph.has_edge(csharp_node, sp_node):
                self.graph.add_edge(csharp_node, sp_node)
        
        return self._render_graph(f"Top {top_n} 熱門 SP 依賴關係", output_path)
    
    def visualize_database_summary(self, output_path: str) -> Optional[str]:
        """資料庫層級摘要圖"""
        # 按資料庫分組
        db_stats = {}
        for rel in self.scan_result.sp_relations:
            db = rel.sp_database
            if db not in db_stats:
                db_stats[db] = {'sps': set(), 'files': set(), 'tables': set()}
            
            db_stats[db]['sps'].add(rel.sp_name)
            db_stats[db]['files'].add(Path(rel.csharp_file).stem)
            
            if rel.sp_info and rel.sp_info.referenced_tables:
                db_stats[db]['tables'].update(rel.sp_info.referenced_tables)
        
        if not db_stats:
            print("⚠️  沒有資料庫統計資料")
            return None
        
        fig, ax = plt.subplots(figsize=(14, max(6, len(db_stats) * 2.5)))
        
        # 建立層次圖
        for i, (db, stats) in enumerate(db_stats.items()):
            db_y = i * 3
            
            # 資料庫節點
            ax.add_patch(plt.Rectangle((0, db_y), 2, 2, 
                                       facecolor='#9b59b6', edgecolor='white', linewidth=2))
            ax.text(1, db_y + 1, f"{db}", ha='center', va='center', 
                   fontsize=11, fontweight='bold', color='white')
            
            # SP 數量
            ax.add_patch(plt.Rectangle((3, db_y), 2, 2,
                                       facecolor='#2ecc71', edgecolor='white', linewidth=2))
            ax.text(4, db_y + 1, f"{len(stats['sps'])}\nSP", ha='center', va='center',
                   fontsize=10, fontweight='bold', color='white')
            
            # 檔案數量
            ax.add_patch(plt.Rectangle((6, db_y), 2, 2,
                                       facecolor='#3498db', edgecolor='white', linewidth=2))
            ax.text(7, db_y + 1, f"{len(stats['files'])}\nFiles", ha='center', va='center',
                   fontsize=10, fontweight='bold', color='white')
            
            # 資料表數量
            ax.add_patch(plt.Rectangle((9, db_y), 2, 2,
                                       facecolor='#f39c12', edgecolor='white', linewidth=2))
            ax.text(10, db_y + 1, f"{len(stats['tables'])}\nTables", ha='center', va='center',
                   fontsize=10, fontweight='bold', color='white')
            
            # 連線
            ax.annotate('', xy=(3, db_y + 1), xytext=(2, db_y + 1),
                       arrowprops=dict(arrowstyle='->', color='gray', lw=2))
            ax.annotate('', xy=(6, db_y + 1), xytext=(5, db_y + 1),
                       arrowprops=dict(arrowstyle='->', color='gray', lw=2))
            ax.annotate('', xy=(9, db_y + 1), xytext=(8, db_y + 1),
                       arrowprops=dict(arrowstyle='->', color='gray', lw=2))
        
        ax.set_xlim(-1, 12)
        ax.set_ylim(-1, len(db_stats) * 3 + 1)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title('資料庫依賴摘要', fontsize=14, fontweight='bold', pad=20)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ 資料庫摘要圖已生成: {output_path}")
        return output_path
    
    def visualize_high_impact_nodes(self, output_path: str, top_n: int = 15) -> Optional[str]:
        """高影響力節點圖"""
        # 計算影響力
        sp_impact = {}
        
        for rel in self.scan_result.sp_relations:
            sp = rel.sp_name
            if sp not in sp_impact:
                sp_impact[sp] = {
                    'call_count': 0,
                    'file_count': set(),
                    'table_count': 0,
                    'complexity': 'unknown'
                }
            
            sp_impact[sp]['call_count'] += 1
            sp_impact[sp]['file_count'].add(rel.csharp_file)
            
            if rel.sp_info:
                sp_impact[sp]['table_count'] = len(rel.sp_info.referenced_tables)
                sp_impact[sp]['complexity'] = rel.sp_info.estimated_complexity
        
        if not sp_impact:
            print("⚠️  沒有 SP 資料")
            return None
        
        # 計算總分
        for sp, data in sp_impact.items():
            data['file_count'] = len(data['file_count'])
            data['score'] = (data['call_count'] * 2 + 
                           data['file_count'] * 3 + 
                           data['table_count'])
        
        # 排序取 Top N
        top_sps = sorted(sp_impact.items(), key=lambda x: x[1]['score'], reverse=True)[:top_n]
        
        if not top_sps:
            return None
        
        fig, ax = plt.subplots(figsize=(14, 10))
        
        sps = [sp for sp, _ in top_sps]
        scores = [data['score'] for _, data in top_sps]
        call_counts = [data['call_count'] for _, data in top_sps]
        file_counts = [data['file_count'] for _, data in top_sps]
        
        # 複雜度顏色
        colors = []
        for _, data in top_sps:
            if data['complexity'] == '複雜':
                colors.append('#e74c3c')
            elif data['complexity'] == '中等':
                colors.append('#f39c12')
            else:
                colors.append('#2ecc71')
        
        # 氣泡圖
        scatter = ax.scatter(call_counts, file_counts, 
                            s=[max(s * 20, 100) for s in scores],
                            c=colors, alpha=0.7, edgecolors='white', linewidth=2)
        
        # 標籤
        for i, sp in enumerate(sps):
            ax.annotate(sp, (call_counts[i], file_counts[i]),
                       xytext=(5, 5), textcoords='offset points',
                       fontsize=8, fontweight='bold')
        
        ax.set_xlabel('呼叫次數', fontsize=12)
        ax.set_ylabel('使用的檔案數', fontsize=12)
        ax.set_title(f'高影響力 SP (Top {len(top_sps)})\n氣泡大小 = 影響力分數', 
                    fontsize=14, fontweight='bold', pad=20)
        
        # 圖例
        legend_elements = [
            mpatches.Patch(color='#2ecc71', label='簡單'),
            mpatches.Patch(color='#f39c12', label='中等'),
            mpatches.Patch(color='#e74c3c', label='複雜'),
        ]
        ax.legend(handles=legend_elements, loc='upper right', title='複雜度')
        
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ 高影響力節點圖已生成: {output_path}")
        return output_path
    
    def _render_graph(self, title: str, output_path: str) -> Optional[str]:
        """渲染圖表"""
        if len(self.graph.nodes) == 0:
            print(f"⚠️  {title}: 沒有資料")
            return None
        
        print(f"   生成: {title} ({len(self.graph.nodes)} 節點)")
        
        fig, ax = plt.subplots(figsize=(16, 12))
        
        # 選擇佈局
        if len(self.graph.nodes) < 30:
            pos = nx.spring_layout(self.graph, k=2.5, iterations=50, seed=42)
        else:
            pos = nx.kamada_kawai_layout(self.graph)
        
        # 分類節點
        node_types = nx.get_node_attributes(self.graph, 'node_type')
        
        csharp_nodes = [n for n, t in node_types.items() if t == 'csharp']
        sp_nodes = [n for n, t in node_types.items() if t == 'sp']
        table_nodes = [n for n, t in node_types.items() if t == 'table']
        
        # 繪製節點
        if csharp_nodes:
            nx.draw_networkx_nodes(self.graph, pos, nodelist=csharp_nodes,
                                  node_color='#3498db', node_size=1500,
                                  node_shape='s', alpha=0.9, ax=ax)
        
        if sp_nodes:
            nx.draw_networkx_nodes(self.graph, pos, nodelist=sp_nodes,
                                  node_color='#2ecc71', node_size=1200,
                                  node_shape='o', alpha=0.9, ax=ax)
        
        if table_nodes:
            nx.draw_networkx_nodes(self.graph, pos, nodelist=table_nodes,
                                  node_color='#f39c12', node_size=1000,
                                  node_shape='d', alpha=0.9, ax=ax)
        
        # 繪製邊
        nx.draw_networkx_edges(self.graph, pos, edge_color='#7f8c8d',
                              arrows=True, arrowsize=15, width=1.2,
                              alpha=0.6, ax=ax,
                              connectionstyle="arc3,rad=0.1")
        
        # 繪製標籤
        nx.draw_networkx_labels(self.graph, pos, font_size=8, ax=ax)
        
        # 圖例
        legend_elements = []
        if csharp_nodes:
            legend_elements.append(mpatches.Patch(color='#3498db', label=f'C# ({len(csharp_nodes)})'))
        if sp_nodes:
            legend_elements.append(mpatches.Patch(color='#2ecc71', label=f'SP ({len(sp_nodes)})'))
        if table_nodes:
            legend_elements.append(mpatches.Patch(color='#f39c12', label=f'Table ({len(table_nodes)})'))
        
        if legend_elements:
            ax.legend(handles=legend_elements, loc='upper left', fontsize=10)
        
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.axis('off')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"   ✅ 已儲存: {output_path}")
        return output_path
    
    # ========================================
    # 互動式 HTML 圖表
    # ========================================
    
    def _generate_interactive_html(self, output_dir: str) -> Optional[str]:
        """生成互動式 HTML 圖表（使用 vis.js）"""
        output_path = f"{output_dir}/interactive_graph.html"
        
        # 準備資料
        nodes = []
        edges = []
        node_id_map = {}
        
        for rel in self.scan_result.sp_relations:
            # C# 節點
            csharp_name = Path(rel.csharp_file).stem
            if csharp_name not in node_id_map:
                node_id_map[csharp_name] = len(node_id_map)
                nodes.append({
                    'id': node_id_map[csharp_name],
                    'label': csharp_name,
                    'group': 'csharp',
                    'title': f"C# File: {csharp_name}"
                })
            
            # SP 節點
            sp_name = rel.sp_name
            if sp_name not in node_id_map:
                node_id_map[sp_name] = len(node_id_map)
                complexity = rel.sp_info.estimated_complexity if rel.sp_info else 'unknown'
                tables = list(rel.sp_info.referenced_tables)[:5] if rel.sp_info and rel.sp_info.referenced_tables else []
                
                nodes.append({
                    'id': node_id_map[sp_name],
                    'label': sp_name,
                    'group': 'sp',
                    'title': f"SP: {sp_name}<br>DB: {rel.sp_database}<br>Complexity: {complexity}<br>Tables: {', '.join(tables)}"
                })
            
            # 邊
            edge_key = (node_id_map[csharp_name], node_id_map[sp_name])
            if edge_key not in [(e['from'], e['to']) for e in edges]:
                edges.append({
                    'from': node_id_map[csharp_name],
                    'to': node_id_map[sp_name],
                    'arrows': 'to'
                })
            
            # Table 節點
            if rel.sp_info and rel.sp_info.referenced_tables:
                for table in rel.sp_info.referenced_tables:
                    if table not in node_id_map:
                        node_id_map[table] = len(node_id_map)
                        nodes.append({
                            'id': node_id_map[table],
                            'label': table,
                            'group': 'table',
                            'title': f"Table: {table}"
                        })
                    
                    edge_key = (node_id_map[sp_name], node_id_map[table])
                    if edge_key not in [(e['from'], e['to']) for e in edges]:
                        edges.append({
                            'from': node_id_map[sp_name],
                            'to': node_id_map[table],
                            'arrows': 'to',
                            'dashes': True
                        })
        
        if not nodes:
            print("⚠️  沒有資料可生成互動式圖表")
            return None
        
        nodes_json = json.dumps(nodes, ensure_ascii=False)
        edges_json = json.dumps(edges, ensure_ascii=False)
        
        # 統計
        csharp_count = len([n for n in nodes if n['group'] == 'csharp'])
        sp_count = len([n for n in nodes if n['group'] == 'sp'])
        table_count = len([n for n in nodes if n['group'] == 'table'])
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>互動式依賴關係圖 - {self.scan_result.project_name}</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Microsoft YaHei', sans-serif; }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }}
        
        .header h1 {{ margin-bottom: 5px; }}
        
        .controls {{
            padding: 15px 20px;
            background: #f5f6fa;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            align-items: center;
        }}
        
        .control-group {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .control-group label {{
            font-weight: bold;
            color: #2c3e50;
        }}
        
        .control-group input[type="text"] {{
            padding: 8px 12px;
            border: 2px solid #ddd;
            border-radius: 6px;
            width: 200px;
        }}
        
        .control-group input[type="text"]:focus {{
            outline: none;
            border-color: #667eea;
        }}
        
        .control-group input[type="checkbox"] {{
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}
        
        .legend {{
            display: flex;
            gap: 20px;
            margin-left: auto;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        
        .legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
        }}
        
        #graph {{
            width: 100%;
            height: calc(100vh - 140px);
            border: 1px solid #ddd;
        }}
        
        .stats {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            font-size: 14px;
        }}
        
        .stats strong {{
            display: block;
            margin-bottom: 10px;
            color: #2c3e50;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔗 互動式依賴關係圖</h1>
        <p>{self.scan_result.project_name}</p>
    </div>
    
    <div class="controls">
        <div class="control-group">
            <label>🔍 搜尋:</label>
            <input type="text" id="searchInput" placeholder="輸入節點名稱..." onkeyup="searchNode()">
        </div>
        
        <div class="control-group">
            <label>顯示:</label>
            <input type="checkbox" id="showCsharp" checked onchange="filterNodes()"> C#
            <input type="checkbox" id="showSP" checked onchange="filterNodes()"> SP
            <input type="checkbox" id="showTable" checked onchange="filterNodes()"> Table
        </div>
        
        <div class="legend">
            <div class="legend-item">
                <div class="legend-color" style="background: #3498db;"></div>
                <span>C# Files ({csharp_count})</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #2ecc71;"></div>
                <span>Stored Procedures ({sp_count})</span>
            </div>
            <div class="legend-item">
                <div class="legend-color" style="background: #f39c12;"></div>
                <span>Tables ({table_count})</span>
            </div>
        </div>
    </div>
    
    <div id="graph"></div>
    
    <div class="stats">
        <strong>📊 統計</strong>
        節點: {len(nodes)}<br>
        連線: {len(edges)}
    </div>
    
    <script>
        var allNodes = {nodes_json};
        var allEdges = {edges_json};
        
        var nodes = new vis.DataSet(allNodes);
        var edges = new vis.DataSet(allEdges);
        
        var container = document.getElementById('graph');
        var data = {{ nodes: nodes, edges: edges }};
        
        var options = {{
            nodes: {{
                font: {{ size: 12 }},
                borderWidth: 2
            }},
            edges: {{
                smooth: {{
                    type: 'cubicBezier',
                    forceDirection: 'horizontal'
                }},
                color: {{ color: '#7f8c8d', opacity: 0.6 }}
            }},
            groups: {{
                csharp: {{
                    shape: 'circle',
                    color: {{ background: '#3498db', border: '#2980b9' }},
                    font: {{ color: 'black' }}
                }},
                sp: {{
                    shape: 'box',
                    color: {{ background: '#2ecc71', border: '#27ae60' }},
                    font: {{ color: 'black' }}
                }},
                table: {{
                    shape: 'database',
                    color: {{ background: '#f39c12', border: '#e67e22' }},
                    font: {{ color: 'black' }}
                }}
            }},
            physics: {{
                enabled: true,
                solver: 'forceAtlas2Based',
                forceAtlas2Based: {{
                    gravitationalConstant: -50,
                    centralGravity: 0.01,
                    springLength: 100,
                    springConstant: 0.08
                }},
                stabilization: {{
                    iterations: 100
                }}
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 100,
                navigationButtons: true,
                keyboard: true
            }}
        }};
        
        var network = new vis.Network(container, data, options);
        
        function searchNode() {{
            var searchText = document.getElementById('searchInput').value.toLowerCase();
            
            if (!searchText) {{
                nodes.update(allNodes.map(function(n) {{ return {{ id: n.id, hidden: false }}; }}));
                return;
            }}
            
            allNodes.forEach(function(node) {{
                var match = node.label.toLowerCase().includes(searchText);
                nodes.update({{ id: node.id, hidden: !match }});
            }});
        }}
        
        function filterNodes() {{
            var showCsharp = document.getElementById('showCsharp').checked;
            var showSP = document.getElementById('showSP').checked;
            var showTable = document.getElementById('showTable').checked;
            
            allNodes.forEach(function(node) {{
                var hidden = false;
                if (node.group === 'csharp' && !showCsharp) hidden = true;
                if (node.group === 'sp' && !showSP) hidden = true;
                if (node.group === 'table' && !showTable) hidden = true;
                
                nodes.update({{ id: node.id, hidden: hidden }});
            }});
        }}
    </script>
</body>
</html>"""
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        print(f"✅ 互動式圖表已生成: {output_path}")
        return output_path
    
    # ========================================
    # 匯出功能
    # ========================================
    
    def export_to_json(self, output_path: str = None) -> Optional[str]:
        """匯出圖表資料為 JSON"""
        # 建構圖表
        if len(self.graph.nodes) == 0:
            self.graph.clear()
            for rel in self.scan_result.sp_relations:
                csharp_node = Path(rel.csharp_file).stem
                sp_node = rel.sp_name
                
                self.graph.add_node(csharp_node, node_type='csharp')
                self.graph.add_node(sp_node, node_type='sp', database=rel.sp_database)
                self.graph.add_edge(csharp_node, sp_node)
                
                if rel.sp_info and rel.sp_info.referenced_tables:
                    for table in rel.sp_info.referenced_tables:
                        self.graph.add_node(table, node_type='table')
                        self.graph.add_edge(sp_node, table)
        
        if len(self.graph.nodes) == 0:
            print("⚠️  沒有資料可匯出")
            return None
        
        data = {
            'nodes': [],
            'edges': [],
            'metadata': {
                'project': self.scan_result.project_name,
                'generated_at': datetime.now().isoformat(),
                'total_nodes': len(self.graph.nodes),
                'total_edges': len(self.graph.edges)
            }
        }
        
        for node, attrs in self.graph.nodes(data=True):
            data['nodes'].append({
                'id': node,
                'label': node,
                **attrs
            })
        
        for source, target, attrs in self.graph.edges(data=True):
            data['edges'].append({
                'source': source,
                'target': target,
                **attrs
            })
        
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"output/graphs/{self.scan_result.project_name}_graph_{timestamp}.json"
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 圖表資料已匯出: {output_path}")
        return output_path


# ============================================
# 統計圖表生成器
# ============================================

class StatisticsChartGenerator:
    """統計圖表生成器"""
    
    def __init__(self, scan_result):
        """
        初始化統計圖表生成器
        
        Args:
            scan_result: ProjectScanResult 物件
        """
        self.scan_result = scan_result
        self._setup_font()
    
    def _setup_font(self):
        """設定字型"""
        try:
            plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
        except:
            pass
    
    def generate_all_charts(self, output_dir: str) -> List[str]:
        """生成所有統計圖表"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        output_files = []
        
        charts = [
            ('database_distribution', self._generate_database_chart),
            ('complexity_distribution', self._generate_complexity_chart),
            ('file_sp_ranking', self._generate_file_ranking),
            ('sp_frequency', self._generate_sp_frequency),
        ]
        
        for name, generator in charts:
            try:
                path = generator(f"{output_dir}/{name}.png")
                if path:
                    output_files.append(path)
            except Exception as e:
                print(f"⚠️  生成 {name} 失敗: {e}")
        
        return output_files
    
    def _generate_database_chart(self, output_path: str) -> Optional[str]:
        """資料庫分布圖"""
        db_counts = Counter(rel.sp_database for rel in self.scan_result.sp_relations)
        
        if not db_counts:
            print("⚠️  沒有資料庫統計資料")
            return None
        
        fig, ax = plt.subplots(figsize=(10, 8))
        
        colors = plt.cm.Set3(range(len(db_counts)))
        wedges, texts, autotexts = ax.pie(
            db_counts.values(), 
            labels=db_counts.keys(), 
            autopct='%1.1f%%',
            colors=colors,
            explode=[0.02] * len(db_counts)
        )
        
        ax.set_title('資料庫使用分布', fontsize=14, fontweight='bold', pad=20)
        
        # 圖例
        legend_labels = [f'{label}: {count} 次' for label, count in db_counts.items()]
        ax.legend(wedges, legend_labels, loc='center left', bbox_to_anchor=(1, 0.5))
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ 資料庫分布圖: {output_path}")
        return output_path
    
    def _generate_complexity_chart(self, output_path: str) -> Optional[str]:
        """複雜度分布圖"""
        complexity_counts = {'簡單': 0, '中等': 0, '複雜': 0}
        
        seen = set()
        for rel in self.scan_result.sp_relations:
            if rel.sp_info and rel.sp_name not in seen:
                seen.add(rel.sp_name)
                c = rel.sp_info.estimated_complexity
                if c in complexity_counts:
                    complexity_counts[c] += 1
        
        if sum(complexity_counts.values()) == 0:
            print("⚠️  沒有複雜度統計資料")
            return None
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        colors = ['#2ecc71', '#f39c12', '#e74c3c']
        bars = ax.bar(complexity_counts.keys(), complexity_counts.values(), color=colors, edgecolor='white', linewidth=2)
        
        # 在柱狀圖上顯示數值
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(height)}',
                   ha='center', va='bottom', fontsize=14, fontweight='bold')
        
        ax.set_title('SP 複雜度分布', fontsize=14, fontweight='bold', pad=20)
        ax.set_ylabel('數量', fontsize=12)
        ax.set_ylim(0, max(complexity_counts.values()) * 1.2 if max(complexity_counts.values()) > 0 else 1)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ 複雜度分布圖: {output_path}")
        return output_path
    
    def _generate_file_ranking(self, output_path: str, top_n: int = 15) -> Optional[str]:
        """檔案排名圖"""
        file_counts = Counter()
        for r in self.scan_result.csharp_results:
            file_counts[Path(r.file_path).stem] = len(r.stored_procedure_calls)
        
        # 取前 N 名（且有呼叫的）
        top = [(f, c) for f, c in file_counts.most_common(top_n) if c > 0]
        
        if not top:
            print("⚠️  沒有檔案排名資料")
            return None
        
        fig, ax = plt.subplots(figsize=(12, max(6, len(top) * 0.5)))
        
        files, counts = zip(*reversed(top))
        
        # 漸層顏色
        colors = plt.cm.Blues([0.4 + 0.5 * i / len(files) for i in range(len(files))])
        
        bars = ax.barh(files, counts, color=colors, edgecolor='white', linewidth=1)
        
        # 顯示數值
        for bar, count in zip(bars, counts):
            width = bar.get_width()
            ax.text(width + 0.3, bar.get_y() + bar.get_height()/2.,
                   f'{count}',
                   ha='left', va='center', fontsize=10, fontweight='bold')
        
        ax.set_title(f'檔案 SP 呼叫排名 (Top {len(top)})', fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('SP 呼叫次數', fontsize=12)
        ax.set_xlim(0, max(counts) * 1.15 if counts else 1)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ 檔案排名圖: {output_path}")
        return output_path
    
    def _generate_sp_frequency(self, output_path: str, top_n: int = 20) -> Optional[str]:
        """SP 頻率圖"""
        sp_counts = Counter(rel.sp_name for rel in self.scan_result.sp_relations)
        top = sp_counts.most_common(top_n)
        
        if not top:
            print("⚠️  沒有 SP 頻率資料")
            return None
        
        fig, ax = plt.subplots(figsize=(14, 8))
        
        sps, counts = zip(*top)
        
        # 漸層顏色
        colors = plt.cm.Greens([0.4 + 0.5 * i / len(sps) for i in range(len(sps))])
        
        bars = ax.bar(range(len(sps)), counts, color=colors, edgecolor='white', linewidth=1)
        
        ax.set_xticks(range(len(sps)))
        ax.set_xticklabels(sps, rotation=45, ha='right', fontsize=9)
        
        # 顯示數值
        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{count}',
                   ha='center', va='bottom', fontsize=9, fontweight='bold')
        
        ax.set_title(f'SP 呼叫頻率 (Top {len(top)})', fontsize=14, fontweight='bold', pad=20)
        ax.set_ylabel('呼叫次數', fontsize=12)
        ax.set_ylim(0, max(counts) * 1.15 if counts else 1)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
        
        print(f"✅ SP 頻率圖: {output_path}")
        return output_path


# ============================================
# 測試與使用範例
# ============================================

def main():
    """測試圖表生成"""
    from .project_scanner import ProjectScanner
    from config.settings import settings
    
    print("=" * 80)
    print("依賴關係圖與統計圖表測試")
    print("=" * 80)
    
    project_root = input("請輸入專案根目錄: ").strip()
    
    if not project_root or not Path(project_root).exists():
        print("❌ 專案路徑無效")
        return
    
    # 建立掃描器
    print("\n📂 掃描專案...")
    scanner = ProjectScanner(project_root)
    
    # 選擇模式
    print("\n請選擇模式:")
    print("  1. 測試模式（限制10個檔案）")
    print("  2. 完整掃描")
    print("  3. 單一模組分析")
    
    mode = input("\n請選擇 (1-3): ").strip()
    
    if mode == '1':
        result = scanner.scan_project(analyze_sp=True, max_files=10)
    elif mode == '2':
        result = scanner.scan_project(analyze_sp=True)
    elif mode == '3':
        module_name = input("請輸入模組名稱: ").strip()
        if not module_name:
            print("❌ 未輸入模組名稱")
            return
        
        analysis = scanner.analyze_related_files(module_name, connect_databases=True)
        
        if not analysis['file_analyses']:
            print("❌ 未找到相關檔案")
            return
        
        # 建立臨時的 ProjectScanResult
        from .project_scanner import ProjectScanResult, CSharpSPRelation
        
        result = ProjectScanResult(
            project_root=project_root,
            project_name=f"{scanner.project_name}_{module_name}",
            scan_time=datetime.now()
        )
        
        result.csharp_results = analysis['file_analyses']
        result.scanned_files = len(analysis['file_analyses'])
        result.total_files = len(analysis['file_analyses'])
        
        for sp_call in analysis['sp_calls']:
            sp_info = analysis['sp_details'].get(
                (sp_call.database_source or 'unknown', sp_call.procedure_name)
            )
            
            rel = CSharpSPRelation(
                csharp_file=sp_call.location.file_path,
                class_name="",
                method_name="",
                line_number=sp_call.location.line_number,
                sp_name=sp_call.procedure_name,
                sp_database=sp_call.database_source or 'unknown',
                sp_info=sp_info
            )
            result.sp_relations.append(rel)
    else:
        print("❌ 無效選項")
        return
    
    # 生成圖表
    print("\n📊 生成圖表...")
    graph_gen = DependencyGraphGenerator(result)
    output = graph_gen.generate_appropriate_graphs()
    
    # 彙總結果
    print("\n" + "=" * 80)
    print("✅ 生成完成")
    print("=" * 80)
    
    all_files = output['graphs'] + output['charts'] + output['html']
    
    print(f"\n📁 共生成 {len(all_files)} 個檔案:\n")
    
    if output['graphs']:
        print("📊 依賴關係圖:")
        for f in output['graphs']:
            print(f"   - {Path(f).name}")
    
    if output['charts']:
        print("\n📈 統計圖表:")
        for f in output['charts']:
            print(f"   - {Path(f).name}")
    
    if output['html']:
        print("\n🌐 互動式圖表:")
        for f in output['html']:
            print(f"   - {Path(f).name}")
    
    # 開啟結果
    print("\n" + "-" * 80)
    open_choice = input("\n要開啟什麼？(1=資料夾 / 2=互動式HTML / n=不開啟): ").strip()
    
    if open_choice == '1':
        import subprocess
        import platform
        
        if all_files:
            output_dir = Path(all_files[0]).parent.resolve()
            
            if platform.system() == 'Windows':
                subprocess.run(['explorer', str(output_dir)])
            elif platform.system() == 'Darwin':
                subprocess.run(['open', str(output_dir)])
            else:
                subprocess.run(['xdg-open', str(output_dir)])
    
    elif open_choice == '2' and output['html']:
        import webbrowser
        webbrowser.open(f"file://{Path(output['html'][0]).resolve()}")
    
    print("\n✅ 測試完成")


def example_usage():
    """
    使用範例
    """
    print("""
# ============================================
# 依賴關係圖生成器使用範例
# ============================================

# 範例 1: 完整專案掃描後生成圖表
# ------------------------------------------
from code_analyzer.project_scanner import ProjectScanner
from code_analyzer.dependency_graph import DependencyGraphGenerator

scanner = ProjectScanner("C:/Projects/MyProject")
result = scanner.scan_project(analyze_sp=True)

graph_gen = DependencyGraphGenerator(result)
output = graph_gen.generate_appropriate_graphs()

print(f"生成了 {len(output['graphs'])} 個依賴圖")
print(f"生成了 {len(output['charts'])} 個統計圖")
print(f"生成了 {len(output['html'])} 個互動式圖表")


# 範例 2: 單一模組分析
# ------------------------------------------
analysis = scanner.analyze_related_files("Customer")

# 建立臨時結果後生成圖表
from code_analyzer.project_scanner import ProjectScanResult, CSharpSPRelation

temp_result = ProjectScanResult(
    project_root=scanner.project_root,
    project_name=f"{scanner.project_name}_Customer",
    scan_time=datetime.now()
)
temp_result.csharp_results = analysis['file_analyses']

for sp_call in analysis['sp_calls']:
    rel = CSharpSPRelation(...)
    temp_result.sp_relations.append(rel)

graph_gen = DependencyGraphGenerator(temp_result)
graph_gen.generate_appropriate_graphs()


# 範例 3: 只生成特定類型圖表
# ------------------------------------------
graph_gen = DependencyGraphGenerator(result)

# 只生成 C# → SP 圖
graph_gen.visualize_csharp_to_sp("output/csharp_to_sp.png")

# 只生成資料庫摘要圖
graph_gen.visualize_database_summary("output/db_summary.png")

# 只生成高影響力節點圖
graph_gen.visualize_high_impact_nodes("output/high_impact.png", top_n=10)


# 範例 4: 匯出 JSON 供前端使用
# ------------------------------------------
graph_gen.export_to_json("output/graph_data.json")


# 範例 5: 只生成統計圖表
# ------------------------------------------
from code_analyzer.dependency_graph import StatisticsChartGenerator

stats_gen = StatisticsChartGenerator(result)
stats_gen.generate_all_charts("output/charts")
""")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--example':
        example_usage()
    else:
        main()