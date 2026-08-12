# 測試完整流程
import sys
sys.path.insert(0, 'D:\\pratice\\Python\\Impact_analysis_system')

from code_analyzer.csharp_parser import CSharpParser

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

# 1. 分析連線
print("=" * 80)
print("步驟 1：分析資料庫連線")
print("=" * 80)
parser.db_tracker.analyze_connections(test_code)
for var_name, conn in parser.db_tracker.connections.items():
    print(f"  {var_name} -> {conn.database_name}")

# 2. 提取 SQL from method calls
print("\n" + "=" * 80)
print("步驟 2：提取 SQL from method calls")
print("=" * 80)
sql_list = parser._extract_sql_from_method_calls(test_code)
for sql_info in sql_list:
    print(f"  變數: {sql_info.get('variable')}")
    print(f"  行號: {sql_info.get('line')}")
    print(f"  SQL: {sql_info.get('sql')[:60]}...")

# 3. 識別資料庫來源
print("\n" + "=" * 80)
print("步驟 3：識別資料庫來源")
print("=" * 80)
for sql_info in sql_list:
    var_name = sql_info.get('variable', '')
    line_num = sql_info.get('line')
    
    db_source, conn_var = parser._identify_database_source(test_code, line_num, var_name)
    
    print(f"  變數: {var_name}")
    print(f"  行號: {line_num}")
    print(f"  資料庫來源: {db_source}")
    print(f"  連線變數: {conn_var}")

# 4. 完整的 SQL 查詢提取
print("\n" + "=" * 80)
print("步驟 4：完整 SQL 查詢提取")
print("=" * 80)
lines = test_code.split('\n')
sql_queries = parser._extract_sql_queries(test_code, lines)
for query in sql_queries:
    print(f"  資料庫來源: {query.database_source}")
    print(f"  連線變數: {query.connection_variable}")
    print(f"  資料表: {query.tables}")
