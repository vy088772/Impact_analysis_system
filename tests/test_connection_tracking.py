# 測試連線追蹤修復
import sys
sys.path.insert(0, 'D:\\pratice\\Python\\Impact_analysis_system')

from code_analyzer.db_connection_tracker import DBConnectionTracker

# 模擬 default.aspx.cs 的程式碼片段
test_code = """
using System;
using System.Data.SqlClient;
using System.Configuration;

public partial class _default : System.Web.UI.Page
{
    SQLObject obj = new SQLObject(ConfigurationManager.ConnectionStrings["PUR"].ConnectionString);
    
    void CheckDefaultPage()
    {
        SqlParameter[] par = new SqlParameter[1];
        par[0] = new SqlParameter("@Role", UserAccount.Role.Trim());
        object value = obj.GetFirstValue("Select M.Url From dbo.Roles as R inner join dbo.ModuleList as M on R.DefaultPageID = M.ItemID Where M.Status = 'Y' and Role = @Role", par);
        string url = "HomePageForCommon.aspx";
    }
}
"""

print("=" * 80)
print("測試連線追蹤 - SQLObject 模式")
print("=" * 80)

tracker = DBConnectionTracker()
connections = tracker.analyze_connections(test_code)

print(f"\n找到 {len(connections)} 個連線")

for var_name, conn_info in connections.items():
    print(f"\n變數名稱: {var_name}")
    print(f"  資料庫: {conn_info.database_name}")
    print(f"  連線字串 Key: {conn_info.connection_string_key}")
    print(f"  行號: {conn_info.line_number}")
    print(f"  作用域: {conn_info.scope}")

# 測試 get_database_source
db_source = tracker.get_database_source("obj")
print(f"\n✅ 測試結果:")
print(f"   tracker.get_database_source('obj') = {db_source}")

if db_source == "PUR":
    print(f"   ✅ 成功！obj 變數已正確識別為 PUR 資料庫")
else:
    print(f"   ❌ 失敗！預期 'PUR'，實際得到 '{db_source}'")
