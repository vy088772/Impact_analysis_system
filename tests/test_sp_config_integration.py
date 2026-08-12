# test_sp_config_integration.py
"""
測試預存程序設定檔整合
"""

from code_analyzer.csharp_parser import CSharpParser
from config.sp_detector_config import SPDetectionConfig
from pathlib import Path

def test_with_config():
    """測試使用設定檔"""
    
    print("=" * 80)
    print("測試預存程序偵測設定檔整合")
    print("=" * 80)
    
    # 1. 顯示設定
    print("\n���驟 1: 載入設定")
    print("-" * 40)
    config = SPDetectionConfig()
    config.print_config()
    
    # 2. 建立解析器（會自動使用設定）
    print("\n步驟 2: 建立解析器")
    print("-" * 40)
    parser = CSharpParser()  # 會自動載入預設設定檔
    
    # 3. 測試程式碼
    test_code = """
    using System;
    using System.Data;
    using System.Data.SqlClient;
    
    namespace TestApp
    {
        public class DataAccess
        {
            // 測試 1: ExeProcRead (設定檔中的方法)
            public void Test1()
            {
                SqlDataReader dr = obj.ExeProcRead("spAddNewCompany", par);
            }
            
            // 測試 2: CreateDataSet (設定檔中的方法)
            public void Test2()
            {
                DataSet ds = dbHelper.CreateDataSet("spGetCompanyList", parameters);
            }
            
            // 測試 3: SqlCommand (設定檔啟用)
            public DataSet Test3(string parentValue)
            {
                DataSet ds = new DataSet();
                using (SqlConnection cn = new SqlConnection(_connetStrRead))
                {
                    using (SqlCommand cmd = new SqlCommand("spCompany_DropLownListbyUserID", cn))
                    {
                        cmd.CommandType = CommandType.StoredProcedure;
                        cmd.Parameters.Add("@ParentType", SqlDbType.VarChar, 20).Value = "CRM";
                        cmd.Parameters.Add("@UserID", SqlDbType.VarChar, 20).Value = UserAccount.UserID;
                    }
                }
                return ds;
            }
            
            // 測試 4: 直接 EXEC (設定檔啟用)
            public void Test4(int userId)
            {
                _connection.Execute("EXEC sp_DeleteUser @userId", new { userId });
            }
            
            // 測試 5: 不符合命名規則的（應該被過濾）
            public void Test5()
            {
                var result = dbHelper.CreateDataSet("GetData", null);  // 不符合 sp 前綴
            }
        }
    }
    """
    
    # 4. 寫入測試檔案
    print("\n步驟 3: 解析測試程式碼")
    print("-" * 40)
    test_file = "test_sp_config.cs"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)
    
    # 5. 解析
    result = parser.parse_file(test_file)
    
    # 6. 顯示結果
    print(f"\n找到 {len(result.stored_procedure_calls)} 個預存程序呼叫:\n")
    
    for i, sp in enumerate(result.stored_procedure_calls, 1):
        print(f"{i}. {sp.procedure_name}")
        print(f"   位置: 第 {sp.location.line_number} 行")
        if sp.parameters:
            print(f"   參數: {', '.join(sp.parameters)}")
        print()
    
    # 7. 顯示警告
    if result.warnings:
        print("⚠️ 警告:")
        for warning in result.warnings:
            print(f"  - {warning}")
    
    # 8. 清理
    Path(test_file).unlink()
    
    print("\n" + "=" * 80)
    print("✅ 測試完成")
    print("=" * 80)


def test_custom_config():
    """測試自訂設定"""
    
    print("\n" + "=" * 80)
    print("測試自訂設定")
    print("=" * 80)
    
    # 1. 建立自訂設定
    print("\n建立自訂設定檔...")
    custom_config_path = "config/custom_sp_rules.json"
    
    import json
    custom_config = {
        "wrapper_methods": [
            "ExeProcRead",
            "MyCustomMethod",  # 自訂方法
            "CompanyExecuteProc"  # 公司特有方法
        ],
        "sp_name_patterns": [
            "^sp[A-Z_]",
            "^usp[A-Z_]"  # 加入 usp 前綴
        ],
        "detect_command_type": True,
        "detect_exec_statements": True,
        "require_sp_prefix": True,  # 要求必須有前綴
        "min_proc_name_length": 5
    }
    
    with open(custom_config_path, 'w', encoding='utf-8') as f:
        json.dump(custom_config, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 已建立自訂設定: {custom_config_path}")
    
    # 2. 使用自訂設定建立解析器
    print("\n使用自訂設定建立解析器...")
    parser = CSharpParser(sp_config_file=custom_config_path)
    
    # 3. 測試
    test_code = """
    public class Test
    {
        public void Method1()
        {
            // 應該被偵測到
            var result1 = obj.MyCustomMethod("spGetUsers", null);
            var result2 = obj.CompanyExecuteProc("uspAddRecord", params);
            
            // 不應該被偵測到（沒有前綴）
            var result3 = obj.MyCustomMethod("GetData", null);
        }
    }
    """
    
    test_file = "test_custom_config.cs"
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_code)
    
    result = parser.parse_file(test_file)
    
    print(f"\n找到 {len(result.stored_procedure_calls)} 個預存程序呼叫:")
    for sp in result.stored_procedure_calls:
        print(f"  - {sp.procedure_name}")
    
    # 清理
    Path(test_file).unlink()
    Path(custom_config_path).unlink()
    
    print("\n✅ 自訂設定測試完成")


if __name__ == "__main__":
    # 測試 1: 使用預設設定
    test_with_config()
    
    # 測試 2: 使用自訂設定
    test_custom_config()