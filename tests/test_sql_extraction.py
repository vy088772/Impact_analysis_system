# 測試 SQL 查詢提取
import sys
sys.path.insert(0, 'D:\\pratice\\Python\\Impact_analysis_system')

from code_analyzer.csharp_parser import CSharpParser

# 模擬 default.aspx.cs 的程式碼
test_code = """
using System;
using System.Data.SqlClient;

public partial class _default : System.Web.UI.Page
{
    SQLObject obj = new SQLObject(ConfigurationManager.ConnectionStrings["PUR"].ConnectionString);
    
    void CheckDefaultPage()
    {
        SqlParameter[] par = new SqlParameter[1];
        par[0] = new SqlParameter("@Role", UserAccount.Role.Trim());
        object value = obj.GetFirstValue("Select M.Url From dbo.Roles as R inner join dbo.ModuleList as M on R.DefaultPageID = M.ItemID Where M.Status = 'Y' and Role = @Role", par);
    }
}
"""

parser = CSharpParser()
parser.current_file = "test_default.cs"

# 解析資料庫連線
parser.db_tracker.analyze_connections(test_code)

print("=" * 80)
print("資料庫連線追蹤結果")
print("=" * 80)
for var_name, conn_info in parser.db_tracker.connections.items():
    print(f"變數: {var_name} -> 資料庫: {conn_info.database_name}")

# 提取 SQL 查詢
lines = test_code.split('\n')
sql_queries = parser._extract_sql_queries(test_code, lines)

print("\n" + "=" * 80)
print("SQL 查詢提取結果")
print("=" * 80)
print(f"找到 {len(sql_queries)} 個 SQL 查詢\n")

for i, query in enumerate(sql_queries, 1):
    print(f"查詢 {i}:")
    print(f"  SQL: {query.query_text[:80]}...")
    print(f"  類型: {query.query_type.value}")
    print(f"  資料表: {query.tables}")
    print(f"  資料庫來源: {query.database_source}")
    print(f"  連線變數: {query.connection_variable}")
    print(f"  行號: {query.location.line_number if query.location else 'N/A'}")
